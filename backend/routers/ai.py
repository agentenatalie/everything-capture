from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
from models import AiConversation, AiMemory, Folder, Item, ItemFolderLink, ItemPageNote, ItemTagLink, Settings, Tag
from schemas import (
    AiAskRequest,
    AiAskResponse,
    AiApprovalRequest,
    AiApprovalResponse,
    AiAssistantRequest,
    AiAssistantResponse,
    AiCitationResponse,
    AiConversationListResponse,
    AiConversationResponse,
    AiConversationSaveRequest,
    AiConversationStoredMessage,
    AiConversationSummaryResponse,
    AiItemAnalysisResponse,
    AiPendingApprovalResponse,
    AiRelatedNotesResponse,
    AiToolEventResponse,
    ItemResponse,
)
from security import decrypt_secret
from services.ai_client import (
    AiClientError,
    chat_completion,
    create_embeddings,
    create_chat_completion,
    extract_assistant_message,
    extract_message_text,
    extract_tool_calls,
    stream_chat_completion,
)
import logging

from services.ai_defaults import (
    AI_AGENT_DEFAULT_CAN_EXECUTE_COMMANDS,
    AI_AGENT_DEFAULT_CAN_MANAGE_FOLDERS,
    AI_AGENT_DEFAULT_CAN_PARSE_CONTENT,
    AI_AGENT_DEFAULT_CAN_RUN_COMPUTER_COMMANDS,
    AI_AGENT_DEFAULT_CAN_SYNC_NOTION,
    AI_AGENT_DEFAULT_CAN_SYNC_OBSIDIAN,
    AI_AGENT_DEFAULT_CAN_WEB_SEARCH,
    AI_DEFAULT_BASE_URL,
    AI_DEFAULT_MODEL,
    coerce_bool,
)
from services.knowledge_base import (
    KnowledgeBaseNote,
    KnowledgeBaseSnapshot,
    expand_query_from_top_results,
    extract_terms,
    prepare_note_for_similarity,
    rank_notes_for_expanded_queries,
    rank_related_notes,
)
from tenant import get_current_user_id

router = APIRouter(prefix="/api/ai", tags=["ai"])

_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")
_CITATION_INDEX_PATTERN = re.compile(r"\[(\d{1,3})\]")
_CITATION_PLACEHOLDER_PATTERN = re.compile(r"\[(?:编号|引用编号|序号|ref|REF|index|INDEX)\]")
_TITLE_ALIAS_SPLIT_PATTERN = re.compile(r"[：:|｜—\-·•/!！?？,，。；;]+")
_TITLE_LEADING_LATIN_ALIAS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 .+#_-]{2,}")
_TITLE_NORMALIZE_PATTERN = re.compile(r"[\s\u3000`*_~\"'“”‘’「」『』《》【】\[\]\(\)（）:：;；,，.!！？?、\-—_|/·•]+")
_URL_PATTERN = re.compile(r"https?://[^\s<>\]\)）,，]+", re.IGNORECASE)
_CONTEXT_ALIAS_LINE_PATTERN = re.compile(r"(?im)^(?:[#>*\-\s]+)?([A-Za-z][A-Za-z0-9]*(?:[- ][A-Za-z0-9]+){0,3})\s*[：:]\s*")
_ALIAS_STOP_WORDS = {
    "github", "git", "star", "stars", "agent", "agents", "rag", "react",
    "openai", "claude", "deepseek", "gemini", "qwen", "ollama", "llm",
    "python", "typescript", "javascript", "technical lead", "research mode",
}
_URL_HOST_STOP_WORDS = {"www", "app", "docs", "github", "localhost", "com", "org", "net", "dev", "ai"}
_CHAT_HISTORY_LIMIT = 10
_SAVED_CHAT_HISTORY_LIMIT = 120
_AGENT_TOOL_REPEAT_LIMIT = 3

_RAG_CHUNK_CHAR_LIMIT = 1100
_RAG_CHUNK_OVERLAP_CHAR_LIMIT = 180
_RAG_MAX_CHUNKS_PER_NOTE = 12
_RAG_VECTOR_CANDIDATE_MULTIPLIER = 4
_RAG_VECTOR_MIN_CANDIDATES = 10
_RAG_MAX_SNIPPETS_PER_NOTE = 2
_RAG_EMBED_BATCH_SIZE = 24
_RAG_CONTEXT_SNIPPET_LIMIT = 420

_SEMANTIC_INDEX_CACHE: dict[str, tuple[str, "SemanticChunkIndex"]] = {}

# ── Computer command approval system ──────────────────────────────────
_pending_approvals: dict[str, dict[str, Any]] = {}
_APPROVAL_EXPIRY_SECONDS = 600  # 10 minutes
_COMPUTER_CMD_TIMEOUT = 120
_COMPUTER_CMD_MAX_OUTPUT = 65536
_COMPUTER_CMD_BANNED_PATTERNS = [
    "rm -rf /", "rm -rf ~", "rm -rf /*",
    "sudo rm", "mkfs", "dd if=", "> /dev/",
    ":(){ :|:& };:",  # fork bomb
]
_REAL_COMPUTER_COMMAND_PATTERNS = [
    re.compile(r"(^|\s)git\s+clone(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)brew\s+install(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)(npm|pnpm|bun)\s+.*(?:\s|^)(-g|--global)(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)yarn\s+global\s+add(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)(pip|pip3|pipx)\s+install(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)uv\s+(tool\s+install|pip\s+install)(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)cargo\s+install(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)go\s+install(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)gem\s+install(\s|$)", re.IGNORECASE),
    re.compile(r"(^|\s)(npm|pnpm|bun)\s+(create|dlx)(\s|$)", re.IGNORECASE),
]
_REAL_COMPUTER_PATH_PREFIXES = (
    "~",
    "/Users/",
    "/Applications/",
    "/Applications",
    "/usr/local/",
    "/opt/homebrew/",
    "/Library/",
)


@dataclass
class SemanticChunk:
    chunk_id: str
    note: KnowledgeBaseNote
    text: str
    title: str
    summary: str
    chunk_index: int
    total_chunks: int
    term_weights: dict[str, float] = field(default_factory=dict, repr=False)
    term_norm: float = field(default=0.0, repr=False)


@dataclass
class SemanticChunkIndex:
    chunks: list[SemanticChunk]
    embeddings: list[list[float]] = field(default_factory=list, repr=False)
    mode: str = "lexical"
    embedding_model: str | None = None
    loaded_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RagGroundedContext:
    context_text: str
    ranked_notes: list[tuple[KnowledgeBaseNote, float]]
    note_count: int
    insufficient_context: bool
    retrieval_mode: str


def _clean_optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cleanup_expired_approvals() -> None:
    now = datetime.utcnow()
    expired_ids: list[str] = []

    for approval_id, approval in list(_pending_approvals.items()):
        created_at = approval.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                expired_ids.append(approval_id)
                continue
        if not isinstance(created_at, datetime):
            expired_ids.append(approval_id)
            continue
        if (now - created_at).total_seconds() > _APPROVAL_EXPIRY_SECONDS:
            expired_ids.append(approval_id)

    for approval_id in expired_ids:
        _pending_approvals.pop(approval_id, None)


def _create_pending_approval(
    *,
    command: str,
    description: str,
    working_directory: str | None,
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    approval_id = str(uuid.uuid4())
    approval_payload: dict[str, Any] = {
        "command": command,
        "description": description,
        "working_directory": working_directory,
        "created_at": datetime.utcnow(),
    }
    if extra_fields:
        approval_payload.update(extra_fields)
    _pending_approvals[approval_id] = approval_payload
    _cleanup_expired_approvals()
    return {
        "status": "pending_approval",
        "approval_id": approval_id,
        "command": command,
        "description": description,
        "working_directory": working_directory,
    }


def _get_user_settings(db: Session, user_id: str) -> Settings | None:
    return db.query(Settings).filter(Settings.user_id == user_id).first()


def _get_user_item(db: Session, user_id: str, item_id: str) -> Item | None:
    return db.query(Item).filter(Item.user_id == user_id, Item.id == item_id).first()


def _get_item_page_notes(db: Session, user_id: str, item_id: str) -> list[ItemPageNote]:
    return db.query(ItemPageNote).filter(ItemPageNote.user_id == user_id, ItemPageNote.item_id == item_id).all()


def _get_setting_secret(settings: Settings | None, field_name: str) -> str | None:
    if not settings:
        return None
    try:
        return _clean_optional_string(decrypt_secret(getattr(settings, field_name, None)))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Stored secret {field_name} is unreadable") from exc


def _is_real_computer_command(command: str | None) -> bool:
    normalized = _clean_optional_string(command)
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _REAL_COMPUTER_COMMAND_PATTERNS)


def _looks_like_real_computer_path(path_value: str | None) -> bool:
    normalized = _clean_optional_string(path_value)
    if not normalized:
        return False

    if normalized.startswith(_REAL_COMPUTER_PATH_PREFIXES):
        return True

    if normalized.startswith("/"):
        candidate = Path(os.path.expanduser(normalized))
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return True
        allowed_roots = []
        try:
            from paths import DATA_ROOT

            allowed_roots.append(DATA_ROOT.resolve())
        except Exception:
            allowed_roots = []
        allowed_roots.append(Path("/tmp").resolve())
        return not any(str(resolved).startswith(str(root)) for root in allowed_roots)

    return False


def _sandbox_command_requires_real_computer(action: str, arguments: dict[str, Any]) -> str | None:
    normalized_action = _clean_optional_string(action) or ""

    if normalized_action == "git_clone":
        return "克隆仓库应该直接落到用户电脑上的真实目录，不应该进入 exports 沙箱。"

    if normalized_action == "run_command":
        if _is_real_computer_command(arguments.get("command")):
            return "软件安装、全局安装或项目初始化应该在用户电脑上执行，不应该进入 exports 沙箱。"

    if normalized_action == "batch":
        operations = arguments.get("operations") or []
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            nested_action = _clean_optional_string(operation.get("action")) or ""
            nested_reason = _sandbox_command_requires_real_computer(nested_action, operation)
            if nested_reason:
                return nested_reason

    for candidate in (
        arguments.get("path"),
        arguments.get("output_filename"),
    ):
        if _looks_like_real_computer_path(candidate):
            return "用户指定了真实电脑目录，不能继续在 exports 沙箱里执行。"

    return None


def _tool_call_signature(tool_name: str, arguments: dict[str, Any]) -> str:
    try:
        serialized_arguments = json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        serialized_arguments = str(arguments)
    return f"{tool_name}:{serialized_arguments}"


def _resolve_ai_config(settings: Settings | None) -> dict[str, str]:
    api_key = _get_setting_secret(settings, "ai_api_key")
    base_url = _clean_optional_string(settings.ai_base_url if settings else None) or _clean_optional_string(AI_DEFAULT_BASE_URL)
    model = _clean_optional_string(settings.ai_model if settings else None) or AI_DEFAULT_MODEL
    embedding_model = (
        _clean_optional_string(getattr(settings, "ai_embedding_model", None) if settings else None)
        or _clean_optional_string(os.getenv("AI_EMBEDDING_MODEL"))
        or "text-embedding-3-small"
    )
    missing_fields: list[str] = []
    if not api_key:
        missing_fields.append("ai_api_key")
    if not base_url:
        missing_fields.append("ai_base_url")
    if missing_fields:
        raise HTTPException(status_code=400, detail=f"AI settings are incomplete: {', '.join(missing_fields)}")
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "embedding_model": embedding_model,
    }


def _ai_request_failed(exc: AiClientError) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


def _truncate_text(value: str | None, limit: int) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _normalize_multiline_text(value: str | None) -> str:
    return re.sub(r"\n{3,}", "\n\n", str(value or "").replace("\r\n", "\n").replace("\r", "\n")).strip()


def _load_frame_texts(item: Item) -> list[str]:
    raw = getattr(item, "frame_texts_json", None)
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    texts: list[str] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        text = _clean_optional_string(entry.get("text") or entry.get("content"))
        if text:
            texts.append(text)
    return texts


def _serialize_citations(
    db: Session,
    user_id: str,
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
) -> list[AiCitationResponse]:
    item_ids = [note.item_id for note, _ in ranked_notes if note.item_id]
    library_item_ids = {
        row[0]
        for row in db.query(Item.id)
        .filter(Item.user_id == user_id, Item.id.in_(item_ids))
        .all()
    } if item_ids else set()

    citations: list[AiCitationResponse] = []
    for note, score in ranked_notes:
        citations.append(
            AiCitationResponse(
                note_id=note.note_id,
                reference_index=None,
                library_item_id=note.item_id if note.item_id in library_item_ids else None,
                title=note.title,
                summary=note.summary or None,
                folder=note.folder or None,
                tags=note.tags or [],
                source=note.source,
                relative_path=note.relative_path,
                created_at=note.created_at,
                score=score,
                excerpt=note.excerpt or None,
            )
        )
    return citations


def _serialize_citation_matches(
    db: Session,
    user_id: str,
    citation_matches: list[tuple[int, KnowledgeBaseNote, float]],
) -> list[AiCitationResponse]:
    item_ids = [note.item_id for _, note, _ in citation_matches if note.item_id]
    library_item_ids = {
        row[0]
        for row in db.query(Item.id)
        .filter(Item.user_id == user_id, Item.id.in_(item_ids))
        .all()
    } if item_ids else set()

    citations: list[AiCitationResponse] = []
    for reference_index, note, score in citation_matches:
        citations.append(
            AiCitationResponse(
                reference_index=reference_index,
                note_id=note.note_id,
                library_item_id=note.item_id if note.item_id in library_item_ids else None,
                title=note.title,
                summary=note.summary or None,
                folder=note.folder or None,
                tags=note.tags or [],
                source=note.source,
                relative_path=note.relative_path,
                created_at=note.created_at,
                score=score,
                excerpt=note.excerpt or None,
            )
        )
    return citations


def _extract_citation_positions(answer_text: str | None, ranked_note_count: int) -> list[int]:
    if ranked_note_count <= 0:
        return []

    referenced_positions: list[int] = []
    seen_positions: set[int] = set()
    for raw_index in _CITATION_INDEX_PATTERN.findall(str(answer_text or "")):
        try:
            index = int(raw_index)
        except ValueError:
            continue
        if index < 1 or index > ranked_note_count or index in seen_positions:
            continue
        referenced_positions.append(index)
        seen_positions.add(index)
    return referenced_positions


def _collect_citation_matches(
    answer_text: str | None,
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
    directory_notes: list[KnowledgeBaseNote] | None = None,
) -> list[tuple[int, KnowledgeBaseNote, float]]:
    referenced_positions = _extract_citation_positions(answer_text, len(ranked_notes))
    return [(index, *ranked_notes[index - 1]) for index in referenced_positions]


def _has_invalid_citation_markers(answer_text: str | None, ranked_note_count: int) -> bool:
    if _CITATION_PLACEHOLDER_PATTERN.search(str(answer_text or "")):
        return True
    for raw_index in _CITATION_INDEX_PATTERN.findall(str(answer_text or "")):
        try:
            index = int(raw_index)
        except ValueError:
            continue
        if index < 1 or index > ranked_note_count:
            return True
    return False


def _normalize_title_for_citation_match(value: str | None) -> str:
    return _TITLE_NORMALIZE_PATTERN.sub("", str(value or "")).strip().lower()


def _note_identity(note: KnowledgeBaseNote) -> str:
    return note.item_id or note.note_id


def _build_note_title_aliases(note: KnowledgeBaseNote) -> list[str]:
    raw_title = _clean_optional_string(note.title) or ""
    if not raw_title:
        return []

    aliases: list[str] = [raw_title]
    seen: set[str] = {_normalize_title_for_citation_match(raw_title)}

    for part in _TITLE_ALIAS_SPLIT_PATTERN.split(raw_title):
        candidate = _clean_optional_string(part)
        normalized = _normalize_title_for_citation_match(candidate)
        if candidate and len(normalized) >= 4 and normalized not in seen:
            aliases.append(candidate)
            seen.add(normalized)

    leading_match = _TITLE_LEADING_LATIN_ALIAS_PATTERN.match(raw_title)
    if leading_match:
        candidate = _clean_optional_string(leading_match.group(0))
        normalized = _normalize_title_for_citation_match(candidate)
        if candidate and len(normalized) >= 4 and normalized not in seen:
            aliases.append(candidate)
            seen.add(normalized)

    for candidate in _build_note_context_aliases(note):
        normalized = _normalize_title_for_citation_match(candidate)
        if candidate and len(normalized) >= 4 and normalized not in seen:
            aliases.append(candidate)
            seen.add(normalized)

    return aliases


def _is_useful_alias(candidate: str | None) -> bool:
    value = _clean_optional_string(candidate)
    if not value:
        return False
    normalized = _normalize_title_for_citation_match(value)
    if len(normalized) < 4:
        return False
    if normalized in _ALIAS_STOP_WORDS:
        return False
    return True


def _extract_aliases_from_urls(text: str | None) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for raw_url in _URL_PATTERN.findall(str(text or "")):
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").strip().lower()
        if not host:
            continue

        if host.endswith("github.com"):
            segments = [segment for segment in parsed.path.split("/") if segment]
            if len(segments) >= 2:
                repo = re.sub(r"\.git$", "", segments[1]).strip()
                repo_normalized = _normalize_title_for_citation_match(repo)
                if _is_useful_alias(repo) and repo_normalized not in seen:
                    aliases.append(repo)
                    seen.add(repo_normalized)

        for label in host.split("."):
            if label in _URL_HOST_STOP_WORDS or len(label) < 4:
                continue
            normalized = _normalize_title_for_citation_match(label)
            if _is_useful_alias(label) and normalized not in seen:
                aliases.append(label)
                seen.add(normalized)
                break
    return aliases


def _build_note_context_aliases(note: KnowledgeBaseNote) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    context_text = "\n".join(
        part
        for part in [
            _clean_optional_string(note.source),
            _clean_optional_string(note.excerpt),
            _clean_optional_string(note.extracted_text),
        ]
        if part
    )
    if not context_text:
        return aliases

    for candidate in _extract_aliases_from_urls(context_text):
        normalized = _normalize_title_for_citation_match(candidate)
        if normalized not in seen:
            aliases.append(candidate)
            seen.add(normalized)

    for match in _CONTEXT_ALIAS_LINE_PATTERN.finditer(context_text):
        candidate = _clean_optional_string(match.group(1))
        normalized = _normalize_title_for_citation_match(candidate)
        if _is_useful_alias(candidate) and normalized not in seen:
            aliases.append(candidate)
            seen.add(normalized)

    return aliases


def _extract_answer_candidate_labels(answer_text: str | None) -> list[tuple[int, str]]:
    text = str(answer_text or "")
    if not text:
        return []

    labels: list[tuple[int, str]] = []
    seen_positions: set[int] = set()

    for match in re.finditer(r"(?m)^\|(.+?)\|$", text):
        raw_line = match.group(0)
        cells = [cell.strip() for cell in raw_line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells):
            continue
        first_cell = re.sub(r"\s*\[\d{1,3}\]\s*$", "", cells[0]).strip()
        if first_cell in {"内容", "条目", "标题", "名称"}:
            continue
        label_pos = text.find(first_cell, match.start())
        if label_pos >= 0 and label_pos not in seen_positions:
            labels.append((label_pos, first_cell))
            seen_positions.add(label_pos)

    for match in re.finditer(r"(?m)^\s*[-*]\s+(.+?)(?:\s+[—\-:：]\s+.*)?$", text):
        label = re.sub(r"\s*\[\d{1,3}\]\s*$", "", match.group(1)).strip()
        label = re.sub(r"\s+[（(][^)）]{0,24}[)）]\s*$", "", label).strip()
        if len(_normalize_title_for_citation_match(label)) < 4:
            continue
        label_pos = text.find(label, match.start())
        if label_pos >= 0 and label_pos not in seen_positions:
            labels.append((label_pos, label))
            seen_positions.add(label_pos)

    for match in re.finditer(r"(?m)^(?!\s*[\-|*#|>])\s*(.+?)\s+[—\-:：]\s+.+$", text):
        label = _clean_optional_string(match.group(1))
        label = re.sub(r"\s*\[\d{1,3}\]\s*$", "", label).strip()
        if label in {"内容", "条目", "标题", "名称", "核心主题", "主题"}:
            continue
        if len(_normalize_title_for_citation_match(label)) < 4:
            continue
        label_pos = text.find(label, match.start())
        if label_pos >= 0 and label_pos not in seen_positions:
            labels.append((label_pos, label))
            seen_positions.add(label_pos)

    labels.sort(key=lambda entry: entry[0])
    return labels


def _extract_answer_alias_mentions(
    answer_text: str | None,
    candidate_notes: list[tuple[KnowledgeBaseNote, float]],
    used_note_ids: set[str],
) -> list[tuple[int, str, KnowledgeBaseNote, float]]:
    text = str(answer_text or "")
    if not text:
        return []

    mention_candidates: list[tuple[int, int, str, KnowledgeBaseNote, float]] = []
    for note, score in candidate_notes:
        if _note_identity(note) in used_note_ids:
            continue
        for alias in _build_note_title_aliases(note):
            alias_text = _clean_optional_string(alias)
            alias_normalized = _normalize_title_for_citation_match(alias_text)
            if not alias_text or len(alias_normalized) < 4:
                continue
            position = text.find(alias_text)
            if position < 0:
                continue
            mention_candidates.append((position, -len(alias_text), alias_text, note, score))

    mention_candidates.sort(key=lambda entry: (entry[0], entry[1]))
    mentions: list[tuple[int, str, KnowledgeBaseNote, float]] = []
    seen_note_ids: set[str] = set()
    occupied_ranges: list[tuple[int, int]] = []
    for position, _, alias_text, note, score in mention_candidates:
        identity = _note_identity(note)
        if identity in seen_note_ids:
            continue
        span = (position, position + len(alias_text))
        if any(not (span[1] <= start or span[0] >= end) for start, end in occupied_ranges):
            continue
        mentions.append((position, alias_text, note, score))
        seen_note_ids.add(identity)
        occupied_ranges.append(span)

    mentions.sort(key=lambda entry: entry[0])
    return mentions


def _resolve_answer_label_matches(
    answer_text: str,
    candidate_notes: list[tuple[KnowledgeBaseNote, float]],
) -> list[tuple[int, str, KnowledgeBaseNote, float]]:
    used_note_ids: set[str] = set()
    resolved_matches: list[tuple[int, str, KnowledgeBaseNote, float]] = []
    for position, label in _extract_answer_candidate_labels(answer_text):
        match_result = _best_label_note_match(label, candidate_notes, used_note_ids)
        if match_result is None:
            continue
        note, score = match_result
        resolved_matches.append((position, label, note, score))
        used_note_ids.add(_note_identity(note))
    return resolved_matches


def _best_label_note_match(
    label: str,
    candidate_notes: list[tuple[KnowledgeBaseNote, float]],
    used_note_ids: set[str],
) -> tuple[KnowledgeBaseNote, float] | None:
    label_normalized = _normalize_title_for_citation_match(label)
    if len(label_normalized) < 4:
        return None

    best_note: KnowledgeBaseNote | None = None
    best_score = 0.0
    best_weight = 0.0

    for note, weight in candidate_notes:
        if _note_identity(note) in used_note_ids:
            continue
        alias_scores: list[float] = []
        for alias in _build_note_title_aliases(note):
            alias_normalized = _normalize_title_for_citation_match(alias)
            if len(alias_normalized) < 4:
                continue
            if label_normalized == alias_normalized:
                alias_scores.append(1.0)
                continue
            if label_normalized in alias_normalized or alias_normalized in label_normalized:
                overlap = min(len(label_normalized), len(alias_normalized)) / max(len(label_normalized), len(alias_normalized))
                alias_scores.append(0.88 + overlap * 0.12)
                continue
            alias_scores.append(difflib.SequenceMatcher(None, label_normalized, alias_normalized).ratio())

        if not alias_scores:
            continue
        score = max(alias_scores)
        if score > best_score or (math.isclose(score, best_score) and weight > best_weight):
            best_note = note
            best_score = score
            best_weight = weight

    if best_note is None:
        return None

    threshold = 0.6 if len(label_normalized) >= 8 else 0.72
    if best_score < threshold:
        return None
    return best_note, best_weight


def _candidate_notes_for_answer_matching(
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
    directory_notes: list[KnowledgeBaseNote] | None = None,
) -> list[tuple[KnowledgeBaseNote, float]]:
    candidates: list[tuple[KnowledgeBaseNote, float]] = list(ranked_notes)
    seen_note_ids = {_note_identity(note) for note, _ in ranked_notes}
    for note in directory_notes or []:
        identity = _note_identity(note)
        if identity in seen_note_ids:
            continue
        candidates.append((note, 0.0))
        seen_note_ids.add(identity)
    return candidates


def _strip_citation_placeholders(answer_text: str | None) -> str:
    text = str(answer_text or "")
    if not text:
        return ""

    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        cleaned_line = _CITATION_PLACEHOLDER_PATTERN.sub(" ", raw_line)
        cleaned_line = re.sub(r"[ \t]{2,}", " ", cleaned_line)
        cleaned_line = re.sub(r"\s+([,，.。!！?？:：;；、])", r"\1", cleaned_line)
        cleaned_line = re.sub(r"([(\[【（])\s+", r"\1", cleaned_line)
        cleaned_line = re.sub(r"\s+([)\]】）])", r"\1", cleaned_line)
        cleaned_lines.append(cleaned_line.strip())

    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


def _strip_answer_citation_markers(answer_text: str | None) -> str:
    text = _strip_citation_placeholders(answer_text)
    if not text:
        return ""

    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        cleaned_line = re.sub(r"\s*\[\d{1,3}\]\s*", " ", raw_line)
        cleaned_line = re.sub(r"[ \t]{2,}", " ", cleaned_line)
        cleaned_line = re.sub(r"\s+([,，.。!！?？:：;；、])", r"\1", cleaned_line)
        cleaned_line = re.sub(r"([(\[【（])\s+", r"\1", cleaned_line)
        cleaned_line = re.sub(r"\s+([)\]】）])", r"\1", cleaned_line)
        cleaned_lines.append(cleaned_line.strip())

    return re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()


def _split_reasoning_and_answer(text: str | None) -> tuple[str | None, str, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return None, "", None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        thinking = parsed.get("think")
        answer = parsed.get("answer")
        if isinstance(thinking, str) and isinstance(answer, str):
            return thinking, answer, "json"

    matches = list(re.finditer(r"<think\b[^>]*>[\s\S]*?</think>", raw, flags=re.IGNORECASE))
    if not matches:
        return None, raw, None

    reasoning_blocks = [match.group(0).strip() for match in matches if match.group(0).strip()]
    answer_parts: list[str] = []
    last_end = 0
    for match in matches:
        if match.start() > last_end:
            answer_parts.append(raw[last_end:match.start()])
        last_end = match.end()
    if last_end < len(raw):
        answer_parts.append(raw[last_end:])

    answer = "".join(answer_parts).strip()
    reasoning = "\n\n".join(reasoning_blocks).strip() or None
    return reasoning, answer, "tags"


def _merge_reasoning_and_answer(reasoning: str | None, answer: str, reasoning_format: str | None) -> str:
    answer_text = str(answer or "").strip()
    reasoning_text = str(reasoning or "").strip()
    if not reasoning_text:
        return answer_text
    if reasoning_format == "json":
        return json.dumps({"think": reasoning_text, "answer": answer_text}, ensure_ascii=False)
    if not answer_text:
        return reasoning_text
    return f"{reasoning_text}\n\n{answer_text}".strip()


def _inject_citations_for_matches(
    answer_text: str,
    matches: list[tuple[int, str, KnowledgeBaseNote, float]],
) -> tuple[str, list[tuple[int, KnowledgeBaseNote, float]]]:
    if not answer_text or not matches:
        return "", []

    augmented_answer = answer_text
    offset = 0
    citation_matches: list[tuple[int, KnowledgeBaseNote, float]] = []
    next_index = 1

    for position, label, note, score in matches:
        actual_start = position + offset
        actual_end = actual_start + len(label)
        if augmented_answer[actual_start:actual_end] != label:
            relocated = augmented_answer.find(label, max(0, actual_start - 24))
            if relocated < 0:
                continue
            actual_start = relocated
            actual_end = relocated + len(label)

        augmented_answer = (
            augmented_answer[:actual_end]
            + f" [{next_index}]"
            + augmented_answer[actual_end:]
        )
        offset += len(f" [{next_index}]")
        citation_matches.append((next_index, note, score))
        next_index += 1

    return augmented_answer, citation_matches


def _repair_answer_citations(
    answer_text: str,
    candidate_notes: list[tuple[KnowledgeBaseNote, float]],
) -> tuple[str, list[tuple[int, KnowledgeBaseNote, float]]]:
    cleaned_answer = _strip_answer_citation_markers(answer_text)
    label_matches = _resolve_answer_label_matches(cleaned_answer, candidate_notes)
    if label_matches:
        return _inject_citations_for_matches(cleaned_answer, label_matches)

    alias_matches = _extract_answer_alias_mentions(cleaned_answer, candidate_notes, set())
    return _inject_citations_for_matches(cleaned_answer, alias_matches)


def _annotate_answer_with_citations(
    answer_text: str | None,
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
    directory_notes: list[KnowledgeBaseNote] | None = None,
) -> tuple[str, list[tuple[int, KnowledgeBaseNote, float]]]:
    reasoning, answer_body, reasoning_format = _split_reasoning_and_answer(answer_text)
    visible_answer = _strip_citation_placeholders(answer_body)
    if not visible_answer:
        return _merge_reasoning_and_answer(reasoning, "", reasoning_format), []

    explicit_matches = _collect_citation_matches(visible_answer, ranked_notes)
    candidate_notes = _candidate_notes_for_answer_matching(ranked_notes, directory_notes)
    cleaned_answer = _strip_answer_citation_markers(visible_answer)
    resolved_labels = _resolve_answer_label_matches(cleaned_answer, candidate_notes)
    needs_repair = (
        _has_invalid_citation_markers(visible_answer, len(ranked_notes))
        or (resolved_labels and len(resolved_labels) > len(explicit_matches))
        or (not explicit_matches and bool(_extract_answer_alias_mentions(cleaned_answer, candidate_notes, set())))
    )
    if needs_repair:
        repaired_answer, repaired_matches = _repair_answer_citations(visible_answer, candidate_notes)
        if repaired_matches:
            return _merge_reasoning_and_answer(reasoning, repaired_answer, reasoning_format), repaired_matches

    return _merge_reasoning_and_answer(reasoning, visible_answer, reasoning_format), explicit_matches


def _filter_ranked_notes_by_citation_markers(
    answer_text: str | None,
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
) -> list[tuple[KnowledgeBaseNote, float]]:
    if not ranked_notes:
        return []

    referenced_positions = _extract_citation_positions(answer_text, len(ranked_notes))
    if not referenced_positions:
        return []

    return [ranked_notes[index - 1] for index in referenced_positions]


def _build_note_context_lines(note: KnowledgeBaseNote, index: int) -> str:
    return "\n".join(
        [
            f"[{index}] 标题: {note.title}",
            f"[{index}] 摘要: {note.summary or '无已整理摘要'}",
            f"[{index}] 标签: {', '.join(note.tags) if note.tags else '无'}",
            f"[{index}] 文件夹: {note.folder or '根目录'}",
            f"[{index}] 路径: {note.relative_path}",
            f"[{index}] 时间: {note.created_at.isoformat(sep=' ', timespec='minutes') if note.created_at else '未知'}",
            f"[{index}] 来源: {note.source or '无'}",
            f"[{index}] 正文摘录: {_truncate_text(note.excerpt or note.body, 800) or '无'}",
        ]
    )


def _build_current_item_context(item: Item, note: KnowledgeBaseNote | None = None, page_notes: list[ItemPageNote] | None = None) -> str:
    folder_names = _extract_item_folder_names(item)
    analysis_text = _normalize_multiline_text(item.extracted_text)
    canonical_text = _normalize_multiline_text(item.canonical_text)
    has_video = any(m.type == "video" for m in (item.media or []))
    ocr_text = "" if has_video else _normalize_multiline_text(item.ocr_text)
    frame_text = _normalize_multiline_text("\n".join(_load_frame_texts(item)))
    note_summary = _clean_optional_string(note.summary if note else None)

    lines = [
        f"当前文章 item_id：{item.id}",
        f"当前文章标题：{_clean_optional_string(item.title) or f'Item {item.id}'}",
        f"当前文章来源：{_clean_optional_string(item.source_url) or '无'}",
        f"当前文章文件夹：{' / '.join(folder_names) if folder_names else '未归档'}",
        f"当前文章解析状态：{item.parse_status or 'idle'}",
    ]

    if note_summary:
        lines.extend([
            "",
            "这篇内容的已有摘要：",
            _truncate_text(note_summary, 1200),
        ])

    if analysis_text:
        lines.extend([
            "",
            "当前文章的内容分析 / 解析结果：",
            _truncate_text(analysis_text, 5000),
        ])

    if canonical_text:
        lines.extend([
            "",
            "当前文章抓取到的正文文本：",
            _truncate_text(canonical_text, 7000),
        ])

    supplemental_parts = [part for part in [ocr_text, frame_text] if part]
    if supplemental_parts:
        lines.extend([
            "",
            "当前文章额外抓取到的 OCR / 帧文字：",
            _truncate_text("\n\n".join(supplemental_parts), 4000),
        ])

    if page_notes:
        user_notes_parts = []
        for pn in page_notes:
            title = _clean_optional_string(pn.title) or "无标题"
            content = _clean_optional_string(pn.content) or ""
            if content:
                user_notes_parts.append(f"【{title}】\n{content}")
            else:
                user_notes_parts.append(f"【{title}】")
        if user_notes_parts:
            lines.extend([
                "",
                "用户在这篇文章上的笔记：",
                _truncate_text("\n\n".join(user_notes_parts), 4000),
            ])

    return "\n".join(lines).strip()


def _build_analysis_organizer_context(item: Item) -> str:
    analysis_text = _normalize_multiline_text(item.extracted_text)
    if not analysis_text:
        return ""

    lines = [
        f"当前文章 item_id：{item.id}",
        f"当前文章标题：{_clean_optional_string(item.title) or f'Item {item.id}'}",
        "",
        "当前文章已有的内容分析文本：",
        _truncate_text(analysis_text, 20000),
    ]
    return "\n".join(lines).strip()


def _extract_item_folder_names(item: Item) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for link in item.folder_links or []:
        folder = getattr(link, "folder", None)
        name = _clean_optional_string(folder.name if folder else None)
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
    fallback_name = _clean_optional_string(item.folder.name if getattr(item, "folder", None) else None)
    if fallback_name and fallback_name not in seen:
        names.append(fallback_name)
    return names


def _build_seed_note_from_item(item: Item, existing_note: KnowledgeBaseNote | None = None) -> KnowledgeBaseNote:
    if existing_note is not None:
        return existing_note

    folder_names = _extract_item_folder_names(item)
    combined_body = "\n\n".join(
        [
            value.strip()
            for value in (
                item.canonical_text or "",
                item.extracted_text or "",
            )
            if value and value.strip()
        ]
    )
    summary = _truncate_text(combined_body, 280)
    note = KnowledgeBaseNote(
        note_id=f"item::{item.id}",
        title=_clean_optional_string(item.title) or f"Item {item.id}",
        summary=summary,
        body=combined_body,
        excerpt=_truncate_text(combined_body, 320),
        extracted_text=(item.extracted_text or "").strip(),
        tags=[],
        folder=", ".join(folder_names),
        source=_clean_optional_string(item.source_url),
        created_at=item.created_at,
        relative_path=f"library/{item.id}",
        item_id=item.id,
    )
    return prepare_note_for_similarity(note)


def _ask_ai_system_prompt() -> str:
    return (
        "你是一个读过用户收藏库所有内容的研究助理。"
        "只能基于提供的内容回答，不要引入外部常识来补空。"
        "优先使用每条内容已有的摘要，不要重复整理同一份内容。"
        "如果证据不足，必须明确说信息不足。"
        "提到任何内容时，必须使用 [1] [2] 这样的引用编号，不要用「笔记1」「（笔记51）」等其他格式。"
        "如果你在做归类、列表、表格或逐条总结，每一条内容名称后都必须紧跟自己的 [编号]，不要只在小节末尾统一放引用。"
        "如果答案没有直接引用具体内容，就不要输出引用编号。"
        "\n\n"
        "【重要】仔细审查所有提供的内容，不要只看标题是否字面匹配用户问题。"
        "要深入理解每条内容的实际用途，判断它是否能间接回答用户的问题。"
        "例如：用户问'找实习要用什么工具'，一篇关于'简历自动填写'的内容就是高度相关的。"
    )


def _analysis_system_prompt() -> str:
    return (
        "你是一个读过用户收藏库内容的研究助理。"
        "当前任务是分析一条收藏内容，不要机械复述现有摘要。"
        "分析时要结合正文内容和用户在文章上的笔记内容一起综合判断。"
        "要以现有摘要为锚点，补充更高层次的理解、归类、关联和思考方向。"
        "只基于提供的内容做判断，不要编造。"
        "返回严格 JSON。"
    )


def _assistant_chat_system_prompt() -> str:
    return (
        "你是用户网站里的 AI chatbot。"
        "你的职责是和用户收藏库中的内容以及当前打开的文章对话，而不是泛泛聊天。"
        "如果提供了当前文章上下文，优先依据当前文章的内容分析、抓取文本、OCR / 帧文字以及用户在文章上的笔记综合回答。"
        "回答时要结合正文内容和用户笔记内容一起分析，而不是只看其中一个。"
        "如果同时提供了收藏库内容索引，优先使用已有摘要作为辅助，不要机械重复整理。"
        "只能基于提供的上下文回答；若上下文不足，必须明确说明。"
        "回答请使用中文。"
        "提到任何收藏内容时，必须使用 [编号] 引用标记（如 [1] [2]），不要用「笔记1」「（笔记51）」等其他格式。"
        "如果你在做归类、列表、表格或逐条总结，每一条内容名称后都必须紧跟自己的 [编号]，不要只在小节末尾统一放引用。"
        "如果没有直接引用具体内容，就不要输出引用编号。"
        "\n\n"
        "【重要：深度语义检索】\n"
        "仔细审查所有提供的内容，不要只看标题是否字面匹配用户问题。"
        "要深入理解每条内容的实际用途，判断它是否能间接回答用户的问题。"
        "运用发散性思维：用户问'找实习要用什么工具'→ 简历工具、求职平台、面试准备、AI 辅助写作等都是相关的。"
        "尽可能全面地找出相关内容，宁可多找也不要遗漏。"
        "\n\n"
        "【重要：回答风格】\n"
        "简洁、直接、信息密度高，不要废话和客套。\n"
        "格式要求：\n"
        "- 开头一句话直接回答要点，不要重复用户问题。\n"
        "- 列举型回答用「名称 [编号] — 一句话说明核心价值和用法」的格式，编号紧跟在名称后。\n"
        "- 对比型回答（如比较多个工具/方案的异同）用 Markdown 表格呈现，列为对比维度，行为对比对象。\n"
        "- 提到任何内容时，必须使用 [编号] 格式引用（如 [1] [2]），绝对不要用「笔记1」「（笔记51）」等其他格式；如果一行里列了某条内容，编号要贴在那条内容名字后面。\n"
        "- 如果有实用建议（如工具组合使用方式），在末尾用一段话给出。\n"
        "- 不要输出'希望对你有帮助'之类的尾巴。\n"
        "- 不要问'需要我展开吗'，直接把有价值的信息说完。"
    )


def _load_ai_memories(db: Session, user_id: str) -> list[AiMemory]:
    return (
        db.query(AiMemory)
        .filter(AiMemory.user_id == user_id)
        .order_by(AiMemory.updated_at.desc())
        .limit(50)
        .all()
    )


def _format_memories_for_prompt(memories: list[AiMemory]) -> str:
    if not memories:
        return (
            "【你的记忆】你还没有关于这位用户的任何记忆。\n"
            "在交互过程中，主动用 save_memory 记住你观察到的用户偏好、分类习惯、兴趣领域等。\n"
            "这些记忆会在未来的对话中帮助你更好地服务用户。"
        )
    type_labels = {"learned": "学到的", "preference": "用户偏好", "correction": "纠正"}
    lines = [
        "【你的记忆】以下是你从过去的交互中积累的对用户的了解。"
        "这是你最重要的参考依据——务必据此调整行为，不要忽略这些记忆：",
    ]
    for m in memories:
        label = type_labels.get(m.type, m.type)
        lines.append(f"- [{label}] {m.content}")
    lines.append(
        "\n持续维护你的记忆：用 save_memory 记住新发现的模式和偏好，"
        "用 delete_memory 删除过时或不准确的记忆。"
        "当用户纠正你时，必须立刻保存纠正记忆。"
    )
    return "\n".join(lines)


def _assistant_agent_system_prompt(agent_permissions: list[str], memories: list[AiMemory] | None = None) -> str:
    permission_lines = {
        "search_library": "搜索收藏库内容",
        "manage_folders": "管理文件夹与标签（创建、归档、打标签）",
        "parse_content": "触发内容解析",
        "sync_obsidian": "触发同步到 Obsidian",
        "sync_notion": "触发同步到 Notion",
        "execute_commands": "执行沙箱命令（仅限 exports 临时区）",
        "run_computer_commands": "在用户电脑上执行系统命令（需逐条批准）",
        "web_search": "联网搜索外部信息",
    }
    readable_permissions = "、".join(permission_lines[key] for key in agent_permissions if key in permission_lines)
    if not readable_permissions:
        readable_permissions = "搜索收藏库内容"

    memory_block = _format_memories_for_prompt(memories or [])

    base = (
        "你是用户网站里的 AI agent。"
        "你既可以回答问题，也可以在工具确认成功时代表用户执行站内操作。"
        "你必须优先基于用户收藏库中的内容和工具返回的信息工作，不要编造。"
        "当用户要求执行动作时，必须调用工具，不要只描述你会怎么做。"
        "如果某个权限没有开放，或某个工具执行失败，必须直接说明。"
        "只有在工具结果明确成功时，才能说操作已经完成。"
        "回答请使用中文，保持清楚直接。"
        "提到任何收藏内容时，必须使用工具返回结果中 ref 字段的编号作为引用标记（如 [3] [7]），不要自己按顺序编号。"
        "如果工具结果没有 ref 字段，就不要输出引用编号。"
        "如果没有直接引用具体内容，就不要输出引用编号。"
        "\n\n"
        "【重要：智能检索策略】\n"
        "当用户提问时，你必须主动进行多轮、多角度的收藏库检索，而不是只搜索一次：\n"
        "1. 先用用户原始问题的关键词搜索一次。\n"
        "2. 然后思考用户真正想要找的内容可能以什么形式保存——"
        "考虑同义词、相关概念、不同的表述方式。"
        "例如用户问'申请实习用什么工具'，你应该额外搜索'简历''求职''resume''job application'等。\n"
        "3. 如果第一次搜索结果不够理想（分数低或明显不相关），务必用不同的关键词再搜索1-2次。\n"
        "4. 综合所有搜索结果后再给出最终回答。\n"
        "\n"
        "【重要：用记忆解析个人指代】\n"
        "当用户使用'我的XX''自己的XX'等个人指代时，必须先查看你的记忆来理解用户指的是什么。\n"
        "例如：记忆里有'Everything Capture 是用户自己的开源项目'，用户说'我的项目'时你应该知道是 Everything Capture，"
        "搜索时用具体名称而非'我的项目'。\n"
        "同理，'我的公司''我的团队''我喜欢的XX'等都应结合记忆展开成具体名称再搜索。\n"
        "\n"
        "【重要：执行操作的通用原则】\n"
        "你拥有多个原子工具，可以自由组合来完成用户的各种请求：\n"
        "- 查看内容：search_library_items / list_recent_notes（支持 scope='unfiled' 筛选未归档）/ get_item_details\n"
        "- 管理标签：list_tags / create_tag / assign_item_tags / batch_assign_item_tags\n"
        "- 管理文件夹：list_folders / create_folder / assign_item_folders / batch_assign_item_folders\n"
        "- 联网搜索：web_search — 当需要查询收藏库以外的外部信息（事实校验、最新资讯、百科知识等）时使用\n"
        "- 遇到复杂任务时，先用查询工具了解现状，再决定执行什么操作。\n"
        "- 标签是主题关键词，可多选、可重叠、偏轻量；文件夹是归档位置，偏结构化、偏长期整理。\n"
        "- 用户提到“标签 / tag / 关键词 / 主题词 / 打标签 / 补标签”时，优先使用标签工具，不要擅自调整文件夹。\n"
        "- 用户提到“文件夹 / folder / 归档 / 放到哪个目录”时，优先使用文件夹工具。\n"
        "- 用户只说“分类”但没有说清是标签还是文件夹，而执行会改动数据时，先澄清再操作。\n"
        "- 批量操作优先用 batch_assign_item_folders，不要逐条调用 assign_item_folders。\n"
        "- 需要新文件夹时先用 create_folder 创建，再用 batch_assign_item_folders 归档。\n"
        "- 批量打标签优先用 batch_assign_item_tags；优先复用已有标签，确实缺少时再创建新标签。\n"
        "\n"
        "【重要：文件夹分配策略】\n"
        "当用户要求整理、分类、归档内容时，你必须先学习用户现有的分类习惯，再动手操作：\n"
        "1. 先用 list_folders 查看所有文件夹。\n"
        "2. 用 search_library_items 按每个文件夹搜索几条已分类的内容，分析用户的分类逻辑和命名风格。\n"
        "3. 检查你的记忆中是否已有用户的分类偏好。如果没有，先总结用户的分类规律，"
        "用 save_memory 存储（type='learned'），例如：\n"
        "   - '用户的文件夹按主题领域划分：技术/设计/商业/生活'\n"
        "   - '用户倾向于把 AI 相关内容放在「AI与机器学习」而非「技术」'\n"
        "   - '用户的文件夹命名风格是中文简短名词'\n"
        "4. 根据学到的分类逻辑来分配未归档内容，不要按你自己的理解自创分类标准。\n"
        "5. 如果现有文件夹都不合适，先询问用户是否要创建新文件夹，说明理由。\n"
        "6. 用户纠正你的分配时，立刻用 save_memory(type='correction') 记住纠正内容。\n"
        "\n"
        "【重要：主动学习用户偏好】\n"
        "你应该像一个了解用户的私人助理一样工作。在每次交互中主动观察并记忆：\n"
        "- 用户的兴趣领域和关注方向\n"
        "- 用户的分类习惯和组织逻辑\n"
        "- 用户对你回答风格的偏好（简洁/详细、中文/英文等）\n"
        "- 用户纠正过你的任何行为\n"
        "发现新的模式时主动用 save_memory 保存，不需要用户明确要求。\n"
        "当记忆中已有相关内容但发现过时或不准确时，先 delete_memory 删除旧的再保存新的。\n"
        "\n"
        "【重要：了解外部项目/网页】\n"
        "当用户要求你'去看看''去读一下''了解一下'某个外部项目、GitHub 仓库或网页时：\n"
        "1. 必须使用 web_search 搜索相关信息，而不是把项目下载到本地。\n"
        "2. 克隆仓库会占用用户磁盘空间，用户只是想了解项目内容，不是要下载代码。\n"
        "3. 只有当用户明确要求'下载''克隆''clone'到本地时，才允许执行本机命令，且必须先征得用户同意。\n"
        "\n"
        "【重要：安装到电脑 / 全局安装 / 本地项目配置】\n"
        "当用户要你'装到电脑里''全局安装''brew 安装''npm -g''pipx install''clone 到本地''放到 ~/Projects''配置 GitHub 项目'时：\n"
        "1. 必须使用 run_computer_command，不要使用 execute_sandbox_command。\n"
        "2. execute_sandbox_command 只适合 exports/ 目录下的临时文件，不适合软件安装、全局依赖、仓库克隆、项目初始化、PATH 配置。\n"
        "3. 如果用户没指定目录，run_computer_command 的 working_directory 默认用用户主目录，不要擅自改成 exports/ 或数据目录。\n"
        "4. 如果当前没有开放系统命令权限，不要退回沙箱硬做，直接告诉用户去设置里开启“允许系统命令（需逐条批准）”。\n"
        "\n"
        "【重要：任何下载到电脑的动作都要先批准】\n"
        "使用 run_computer_command 下载文件、克隆仓库或安装软件时，必须先向用户确认：\n"
        "- 告诉用户你要下载或安装什么、大概会影响哪里\n"
        "- 等用户批准后再执行\n"
        "- 绝对不要未经用户批准就下载文件、克隆仓库或安装软件\n"
        "\n"
        "【重要：导出/打包/下载请求】\n"
        "当用户要求'打包''导出''下载''整理成文档'内容时：\n"
        "1. 必须使用 export_items_to_zip 工具，不要自己搜索后在回复里摘要。\n"
        "2. 用户要求的是完整内容，不是摘要或开头。该工具会导出全部正文。\n"
        "3. 用户要一个文件时，用 format='merged_md' 合并成单个 markdown。\n"
        "4. 用户要分开的文件时，用 format='zip_individual' 打包成 zip。\n"
        "5. 导出完成后，告诉用户下载链接，不要在回复中重复粘贴内容。\n"
        "\n"
        f"当前可用权限：{readable_permissions}。"
    )

    if memory_block:
        base += "\n\n" + memory_block

    return base


def _compose_system_message(*parts: str | None) -> str:
    sections = [str(part).strip() for part in parts if str(part or "").strip()]
    return "\n\n".join(sections).strip()


def _analysis_organizer_system_prompt() -> str:
    return (
        "你是一个内容整理助手。"
        "你的任务是把当前文章已有的内容分析文字整理成适合阅读侧栏直接展示的结构化文本。"
        "目标不是生成摘要，而是在不引入外部信息的前提下，最大限度保留原有内容、事实和原文表达。"
        "你更像在做编辑排版，而不是写摘要或读后感。"
        "不要把长文压缩成几点结论，不要默认输出「摘要 / 核心要点」这种固定模板。"
        "不要整理正文，不要改写抓取正文、OCR 或帧文字，也不要把正文重新誊写进结果里。"
        "只允许基于提供的内容整理，不要补外部知识，不要编造。"
        "输出必须是纯文本，不要解释，不要加代码块。"
        "如果原文里已经有像 [detected_title]、[body]、[urls]、[qr_links]、[ocr_text]、[subtitle_text]、[transcript_text] 这样的结构标记，优先保留这些结构标记，只整理各自内部的格式。"
        "如果原文没有结构标记，至少输出 [detected_title] 和 [body]。"
        "整理时只做这些事：修正乱换行、合并重复片段、补齐必要标点、拆分过长段落、在确有必要时添加少量贴近原文逻辑的 Markdown 标题。"
        "[body] 内请使用 Markdown 段落渲染友好的格式：段落之间留空行；仅在原文本来就是条目时使用列表；需要分段时使用 `##` / `###` 标题，但不要把正文改写成提纲式总结。"
    )


def _extract_json_object(text: str) -> dict:
    stripped = _JSON_FENCE_PATTERN.sub("", (text or "").strip())
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON object not found")
    return json.loads(stripped[start : end + 1])


def _coerce_text_list(value: object, *, limit: int = 6) -> list[str]:
    if isinstance(value, list):
        cleaned = [_clean_optional_string(entry) for entry in value]
        return [entry for entry in cleaned if entry][:limit]
    cleaned = _clean_optional_string(value)
    return [cleaned] if cleaned else []


def _clean_tag_name(value: str) -> str:
    return (value or "").strip()


def _strip_code_fence(text: str) -> str:
    stripped = (text or "").strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].lstrip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _strip_reasoning_blocks(text: str | None) -> str:
    return re.sub(r"<think\b[^>]*>[\s\S]*?</think>", "", str(text or ""), flags=re.IGNORECASE).strip()


def _strip_leading_analysis_heading(text: str | None) -> str:
    lines = str(text or "").splitlines()
    while lines:
        normalized = re.sub(r"[*_#`~>\-\s:：]+", "", lines[0]).strip().lower()
        if normalized in {"解析内容", "内容分析"}:
            lines.pop(0)
            continue
        break
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Stage 1: AI query expansion — bridge the semantic gap at the *query* level
# ---------------------------------------------------------------------------

_QUERY_EXPANSION_PROMPT = (
    "你是搜索查询扩展助手。用户会问一个问题，你需要生成多组不同的搜索关键词，"
    "帮助在用户收藏库中通过关键词匹配找到相关内容。\n"
    "要求：\n"
    "1. 输出用户原始问题的核心关键词\n"
    "2. 输出同义词、相关概念、可能的内容标题用词\n"
    "   例如：用户问'申请实习'→ 也搜索'简历 求职 resume job application 面试'\n"
    "   例如：用户问'学编程'→ 也搜索'Python 教程 tutorial 开发工具 coding'\n"
    "3. 每行一组搜索词（可包含多个词），共4-6行\n"
    "4. 不要编号、不要解释，只输出搜索词"
)


async def _expand_search_queries(ai_config: dict[str, str], question: str) -> list[str]:
    """Use AI to generate expanded search queries that cover synonyms and related concepts."""
    try:
        response = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=[
                {"role": "system", "content": _QUERY_EXPANSION_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0.3,
        )
        expanded = [
            line.strip()
            for line in _strip_reasoning_blocks(response).strip().splitlines()
            if line.strip() and len(line.strip()) >= 2
        ]
        if expanded:
            return [question, *expanded[:6]]
    except (AiClientError, Exception):
        pass
    return [question]


# ---------------------------------------------------------------------------
# Stage 2: TF-IDF candidate retrieval over database items
# ---------------------------------------------------------------------------

_CANDIDATE_POOL_SIZE = 30


def _item_to_virtual_note(item: Item) -> KnowledgeBaseNote:
    """Convert a database Item into a KnowledgeBaseNote for unified search."""
    folder_names = _extract_item_folder_names(item)
    summary = _truncate_text(item.extracted_text or item.canonical_text, 280)
    return KnowledgeBaseNote(
        note_id=f"item::{item.id}",
        title=_clean_optional_string(item.title) or f"Item {item.id}",
        summary=summary,
        body=(item.canonical_text or "").strip(),
        excerpt=_truncate_text(item.canonical_text or item.extracted_text, 320),
        extracted_text=(item.extracted_text or "").strip(),
        tags=[],
        folder=", ".join(folder_names),
        source=_clean_optional_string(item.source_url),
        created_at=item.created_at,
        relative_path=f"library/{item.id}",
        item_id=item.id,
    )


# ---------------------------------------------------------------------------
# Cached DB-item snapshot
# ---------------------------------------------------------------------------

_ITEMS_SNAPSHOT_CACHE: dict[str, tuple[str, KnowledgeBaseSnapshot]] = {}


def _items_cache_signature(items: list[Item]) -> str:
    """Build a lightweight signature from item count + latest timestamp."""
    if not items:
        return "0"
    latest = max(
        (item.parsed_at or item.created_at or datetime.min)
        for item in items
    )
    return f"{len(items)}:{latest.isoformat()}"


def _build_items_only_snapshot(db: Session, user_id: str) -> KnowledgeBaseSnapshot:
    """Build a searchable snapshot from database items, with caching."""
    items = _load_all_user_items(db, user_id)
    sig = _items_cache_signature(items)

    cached = _ITEMS_SNAPSHOT_CACHE.get(user_id)
    if cached and cached[0] == sig:
        return cached[1]

    notes: list[KnowledgeBaseNote] = []
    for item in items:
        virtual_note = _item_to_virtual_note(item)
        virtual_note = prepare_note_for_similarity(virtual_note)
        notes.append(virtual_note)

    snapshot = KnowledgeBaseSnapshot(
        root_path=None,
        notes=notes,
        loaded_at=datetime.utcnow(),
    )
    _ITEMS_SNAPSHOT_CACHE[user_id] = (sig, snapshot)
    return snapshot


def _retrieve_candidates(
    unified_snapshot: KnowledgeBaseSnapshot,
    queries: list[str],
    pool_size: int = _CANDIDATE_POOL_SIZE,
) -> list[tuple[KnowledgeBaseNote, float]]:
    """Run TF-IDF search with multiple expanded queries and merge into a candidate pool."""
    return rank_notes_for_expanded_queries(unified_snapshot, queries, limit=pool_size)


# ---------------------------------------------------------------------------
# Stage 3: AI reranker — semantically select from the candidate pool
# ---------------------------------------------------------------------------

_RERANKER_SYSTEM_PROMPT = (
    "你是收藏库语义精排助手。下面列出了一组候选内容的编号、标题和摘要。"
    "请根据用户的问题，选出所有真正相关的条目编号。\n"
    "重要规则：\n"
    "1. 深入理解语义关系，不要只看字面关键词。\n"
    "2. 例如用户问'申请实习'，'简历工具''求职产品''面试准备'都是相关的。\n"
    "3. 宁可多选也不要漏掉，最多选10个。\n"
    "4. 按相关度从高到低排列。\n"
    "5. 输出格式：只输出编号，用英文逗号分隔，例如：3,7,12\n"
    "6. 如果没有任何相关内容，输出：无"
)

# Combined expansion + reranker: one AI call instead of two.
# AI first expands the query semantically, then picks from candidates.
_EXPAND_AND_RERANK_SYSTEM_PROMPT = (
    "你是收藏库语义检索助手。你需要完成两步任务：\n"
    "第一步：理解用户问题的深层含义，联想相关概念和同义词。\n"
    "第二步：从候选列表中选出所有真正相关的条目。\n\n"
    "重要规则：\n"
    "1. 深入理解语义关系，不要只看字面关键词。\n"
    "2. 例如用户问'申请实习'，'简历工具''求职产品''面试准备'都是相关的。\n"
    "3. 宁可多选也不要漏掉，最多选10个。\n"
    "4. 按相关度从高到低排列。\n"
    "5. 输出格式：只输出编号，用英文逗号分隔，例如：3,7,12\n"
    "6. 如果没有任何相关内容，输出：无"
)


def _build_candidate_index(
    candidates: list[tuple[KnowledgeBaseNote, float]],
) -> tuple[str, list[KnowledgeBaseNote]]:
    """Build a compact index from candidates for the AI reranker."""
    lines: list[str] = []
    indexed: list[KnowledgeBaseNote] = []
    for note, _score in candidates:
        idx = len(indexed) + 1
        title = (note.title or "").strip()[:80]
        summary = (note.summary or "").strip()[:150]
        tags = ", ".join(note.tags[:5]) if note.tags else ""
        source = (note.source or "").strip()[:80]
        parts = [f"{idx}. [{title}]"]
        if summary:
            parts.append(summary)
        if tags:
            parts.append(f"标签:{tags}")
        if source:
            parts.append(f"来源:{source}")
        lines.append(" | ".join(parts))
        indexed.append(note)
    return "\n".join(lines), indexed


def _parse_rerank_response(
    response: str,
    indexed_notes: list[KnowledgeBaseNote],
    limit: int,
) -> list[tuple[KnowledgeBaseNote, float]]:
    """Parse comma-separated indices from AI reranker response."""
    cleaned = _strip_reasoning_blocks(response).strip()
    if not cleaned or cleaned == "无":
        return []

    selected: list[tuple[KnowledgeBaseNote, float]] = []
    seen_ids: set[str] = set()
    for raw_number in re.findall(r"\d+", cleaned):
        try:
            idx = int(raw_number) - 1
        except ValueError:
            continue
        if idx < 0 or idx >= len(indexed_notes):
            continue
        note = indexed_notes[idx]
        if note.note_id in seen_ids:
            continue
        seen_ids.add(note.note_id)
        relevance = max(0.1, 1.0 - len(selected) * 0.08)
        selected.append((note, round(relevance, 4)))
        if len(selected) >= limit:
            break

    return selected


async def _ai_rerank_candidates(
    ai_config: dict[str, str],
    candidates: list[tuple[KnowledgeBaseNote, float]],
    question: str,
    limit: int = 8,
) -> list[tuple[KnowledgeBaseNote, float]]:
    """Ask AI to pick the most relevant notes from the candidate pool."""
    if not candidates:
        return []

    index_text, indexed_notes = _build_candidate_index(candidates)

    try:
        response = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=[
                {"role": "system", "content": _RERANKER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"候选内容：\n{index_text}\n\n用户问题：{question}",
                },
            ],
            temperature=0.1,
        )
    except AiClientError:
        return candidates[:limit]

    return _parse_rerank_response(response, indexed_notes, limit)


async def _ai_expand_and_rerank(
    ai_config: dict[str, str],
    candidates: list[tuple[KnowledgeBaseNote, float]],
    question: str,
    limit: int = 8,
) -> list[tuple[KnowledgeBaseNote, float]]:
    """Combined expansion + rerank in a single AI call (saves one round-trip)."""
    if not candidates:
        return []

    index_text, indexed_notes = _build_candidate_index(candidates)

    try:
        response = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=[
                {"role": "system", "content": _EXPAND_AND_RERANK_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"候选内容：\n{index_text}\n\n用户问题：{question}",
                },
            ],
            temperature=0.1,
        )
    except AiClientError:
        return candidates[:limit]

    return _parse_rerank_response(response, indexed_notes, limit)


# ---------------------------------------------------------------------------
# Full pipeline: expand → retrieve → rerank
# ---------------------------------------------------------------------------

def _load_all_user_items(db: Session, user_id: str) -> list[Item]:
    """Load all items from the database for a user."""
    return (
        db.query(Item)
        .filter(Item.user_id == user_id)
        .order_by(Item.created_at.desc())
        .all()
    )


async def _semantic_rank_notes(
    ai_config: dict[str, str],
    snapshot: KnowledgeBaseSnapshot,
    question: str,
    limit: int = 8,
    db: Session | None = None,
    user_id: str | None = None,
) -> list[tuple[KnowledgeBaseNote, float]]:
    """Local TF-IDF search with pseudo-relevance feedback expansion.

    Used by agent tools for focused retrieval. For main chat/ask endpoints,
    prefer _build_full_items_index() which gives all items to the AI directly.
    """
    if db and user_id:
        items_snapshot = _build_items_only_snapshot(db, user_id)
    else:
        items_snapshot = snapshot

    expanded_queries = expand_query_from_top_results(items_snapshot, question)
    candidates = _retrieve_candidates(items_snapshot, expanded_queries, pool_size=_CANDIDATE_POOL_SIZE)

    if not candidates:
        return []

    return candidates[:limit]


def _clean_index_summary(text: str) -> str:
    """Clean summary text for the compact items index — remove structural markers."""
    cleaned = re.sub(r"\[(?:detected_title|body|ocr_text|urls|qr_links|frame_texts)\]\s*", "", text)
    cleaned = re.sub(r"\n+", " ", cleaned)
    return cleaned.strip()


def _build_full_items_index(db: Session, user_id: str) -> tuple[str, list[KnowledgeBaseNote]]:
    """Build a compact index of ALL user items (title + clean summary) for the AI to scan.

    With ~136 items at ~40 tokens each ≈ 5-6K tokens — easily fits in model context.
    The AI does semantic matching directly, which is far more accurate than TF-IDF
    for cross-language/cross-concept queries (e.g. "申请实习" → "ai-resume-autofill").
    """
    items_snapshot = _build_items_only_snapshot(db, user_id)
    lines: list[str] = []
    indexed: list[KnowledgeBaseNote] = []

    for note in items_snapshot.notes:
        idx = len(indexed) + 1
        title = (note.title or "").strip()[:80]
        summary = _clean_index_summary((note.summary or ""))[:150]
        # Skip the summary if it's just repeating the title
        if summary and summary.strip().lower() == title.strip().lower():
            summary = ""
        date_str = note.created_at.strftime("%Y-%m-%d") if note.created_at else ""
        parts = [f"[{idx}]"]
        if date_str:
            parts.append(f"({date_str})")
        parts.append(title)
        if summary:
            parts.append(f"— {summary}")
        lines.append(" ".join(parts))
        indexed.append(note)

    return "\n".join(lines), indexed


_CHAT_ITEMS_DIRECTORY_LIMIT = 200


def _build_chat_items_directory(db: Session, user_id: str) -> tuple[str, list[KnowledgeBaseNote]]:
    """Build a compact chronological directory of all user items for chat mode awareness.

    Uses bullet format with no numeric prefixes, so the model is less likely to copy
    directory positions like `[11]` and confuse them with citation markers.
    """
    items_snapshot = _build_items_only_snapshot(db, user_id)
    if not items_snapshot.notes:
        return "", []

    lines: list[str] = []
    directory_notes = items_snapshot.notes[:_CHAT_ITEMS_DIRECTORY_LIMIT]
    for note in directory_notes:
        title = (note.title or "").strip()[:80]
        if not title:
            continue
        date_str = note.created_at.strftime("%Y-%m-%d") if note.created_at else ""
        folder = (note.folder or "").strip()
        parts = ["-"]
        if date_str:
            parts.append(date_str)
        parts.append(title)
        if folder:
            parts.append(f"文件夹: {folder}")
        lines.append(" ".join(parts))

    total = items_snapshot.note_count
    header = f"收藏库完整目录（共 {total} 条，按保存时间倒序）："
    if total > _CHAT_ITEMS_DIRECTORY_LIMIT:
        header += f"（仅显示最近 {_CHAT_ITEMS_DIRECTORY_LIMIT} 条）"
    return header + "\n" + "\n".join(lines), directory_notes


def _semantic_chunk_signature(snapshot: KnowledgeBaseSnapshot) -> str:
    digest = hashlib.sha1()
    for note in snapshot.notes:
        digest.update((note.note_id or "").encode("utf-8", errors="ignore"))
        digest.update(b"|")
        digest.update((note.title or "").encode("utf-8", errors="ignore"))
        digest.update(b"|")
        digest.update((note.summary or "").encode("utf-8", errors="ignore"))
        digest.update(b"|")
        digest.update(str(len(note.body or "")).encode("ascii"))
        digest.update(b"|")
        digest.update(str(len(note.extracted_text or "")).encode("ascii"))
        digest.update(b"|")
        digest.update(str(note.created_at.isoformat() if note.created_at else "").encode("utf-8", errors="ignore"))
        digest.update(b"\n")
    return digest.hexdigest()


def _split_oversized_text(text: str, limit: int) -> list[str]:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return []
    if len(normalized) <= limit:
        return [normalized]

    parts = re.split(r"(?<=[。！？!?\.])\s+|\n", normalized)
    segments: list[str] = []
    for raw_part in parts:
        part = raw_part.strip()
        if not part:
            continue
        if len(part) <= limit:
            segments.append(part)
            continue
        start = 0
        while start < len(part):
            chunk = part[start : start + limit].strip()
            if chunk:
                segments.append(chunk)
            start += limit
    return segments


def _split_text_into_semantic_chunks(
    text: str,
    *,
    limit: int = _RAG_CHUNK_CHAR_LIMIT,
    overlap: int = _RAG_CHUNK_OVERLAP_CHAR_LIMIT,
) -> list[str]:
    normalized = _normalize_multiline_text(text)
    if not normalized:
        return []
    if len(normalized) <= limit:
        return [normalized]

    raw_paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", normalized) if paragraph.strip()]
    paragraphs: list[str] = []
    for paragraph in raw_paragraphs:
        if len(paragraph) <= limit:
            paragraphs.append(paragraph)
            continue
        paragraphs.extend(_split_oversized_text(paragraph, limit))

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        paragraph_len = len(paragraph) + (2 if current_parts else 0)
        if current_parts and current_len + paragraph_len > limit:
            chunk_text = "\n\n".join(current_parts).strip()
            if chunk_text:
                chunks.append(chunk_text)
            overlap_text = chunk_text[-overlap:].strip() if overlap > 0 else ""
            current_parts = [overlap_text] if overlap_text else []
            current_len = len(overlap_text)

        if current_parts and current_parts[-1] != paragraph and current_len + len(paragraph) + 2 <= limit:
            current_parts.append(paragraph)
            current_len += len(paragraph) + 2
        elif not current_parts:
            current_parts = [paragraph]
            current_len = len(paragraph)
        else:
            chunk_text = "\n\n".join(current_parts).strip()
            if chunk_text and (not chunks or chunks[-1] != chunk_text):
                chunks.append(chunk_text)
            current_parts = [paragraph]
            current_len = len(paragraph)

    if current_parts:
        chunk_text = "\n\n".join(current_parts).strip()
        if chunk_text and (not chunks or chunks[-1] != chunk_text):
            chunks.append(chunk_text)

    deduped: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        key = chunk.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _build_note_source_text(note: KnowledgeBaseNote) -> str:
    sections: list[str] = []
    seen: set[str] = set()
    for raw_value in (note.summary, note.excerpt, note.body, note.extracted_text):
        value = _normalize_multiline_text(raw_value)
        if not value:
            continue
        fingerprint = value.lower()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        sections.append(value)
    if not sections and note.title:
        sections.append(note.title.strip())
    return "\n\n".join(sections).strip()


def _add_weighted_chunk_terms(bucket: dict[str, float], text: str, weight: float) -> None:
    for term in extract_terms(text):
        bucket[term] = bucket.get(term, 0.0) + weight


def _vector_norm(values: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in values.values()))


def _lexical_cosine(left: dict[str, float], left_norm: float, right: dict[str, float], right_norm: float) -> float:
    if not left or not right or left_norm <= 0 or right_norm <= 0:
        return 0.0
    dot = 0.0
    if len(left) > len(right):
        left, right = right, left
    for key, value in left.items():
        dot += value * right.get(key, 0.0)
    if dot <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _build_chunk_term_weights(chunk: SemanticChunk) -> dict[str, float]:
    weights: dict[str, float] = {}
    _add_weighted_chunk_terms(weights, chunk.title, 3.2)
    _add_weighted_chunk_terms(weights, chunk.summary, 2.4)
    _add_weighted_chunk_terms(weights, " ".join(chunk.note.tags or []), 1.8)
    _add_weighted_chunk_terms(weights, chunk.note.folder or "", 0.9)
    _add_weighted_chunk_terms(weights, chunk.text, 1.0)
    return weights


def _build_semantic_chunks(snapshot: KnowledgeBaseSnapshot) -> list[SemanticChunk]:
    chunks: list[SemanticChunk] = []
    for note in snapshot.notes:
        source_text = _build_note_source_text(note)
        chunk_texts = _split_text_into_semantic_chunks(source_text)[:_RAG_MAX_CHUNKS_PER_NOTE]
        total_chunks = max(1, len(chunk_texts))
        if not chunk_texts:
            chunk_texts = [note.summary or note.excerpt or note.title]
        for index, chunk_text in enumerate(chunk_texts, start=1):
            chunk = SemanticChunk(
                chunk_id=f"{note.note_id}::chunk::{index}",
                note=note,
                text=chunk_text,
                title=note.title,
                summary=note.summary,
                chunk_index=index,
                total_chunks=total_chunks,
            )
            chunk.term_weights = _build_chunk_term_weights(chunk)
            chunk.term_norm = _vector_norm(chunk.term_weights)
            chunks.append(chunk)
    return chunks


def _chunk_embedding_text(chunk: SemanticChunk) -> str:
    parts = [chunk.title.strip()]
    summary = _clean_optional_string(chunk.summary)
    if summary:
        parts.append(summary)
    parts.append(chunk.text.strip())
    return "\n\n".join(part for part in parts if part).strip()


async def _embed_texts(ai_config: dict[str, str], texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _RAG_EMBED_BATCH_SIZE):
        batch = texts[start : start + _RAG_EMBED_BATCH_SIZE]
        batch_vectors = await create_embeddings(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["embedding_model"],
            inputs=batch,
            timeout_seconds=90.0,
        )
        if len(batch_vectors) != len(batch):
            raise AiClientError("AI embeddings response count did not match the request")
        vectors.extend(batch_vectors)
    return vectors


async def _embed_query(ai_config: dict[str, str], text: str) -> list[float]:
    vectors = await _embed_texts(ai_config, [text])
    if not vectors:
        raise AiClientError("AI query embedding is empty")
    return vectors[0]


async def _build_semantic_chunk_index(
    *,
    snapshot: KnowledgeBaseSnapshot,
    user_id: str,
    ai_config: dict[str, str],
) -> SemanticChunkIndex:
    signature = _semantic_chunk_signature(snapshot)
    cache_key = "|".join(
        [
            user_id,
            ai_config.get("base_url") or "",
            ai_config.get("embedding_model") or "",
        ]
    )
    cached = _SEMANTIC_INDEX_CACHE.get(cache_key)
    if cached and cached[0] == signature:
        return cached[1]

    chunks = _build_semantic_chunks(snapshot)
    index = SemanticChunkIndex(
        chunks=chunks,
        embeddings=[],
        mode="lexical",
        embedding_model=ai_config.get("embedding_model"),
        loaded_at=datetime.utcnow(),
    )

    if chunks:
        try:
            embeddings = await _embed_texts(ai_config, [_chunk_embedding_text(chunk) for chunk in chunks])
        except AiClientError:
            embeddings = []
        if len(embeddings) == len(chunks):
            index.embeddings = embeddings
            index.mode = "semantic"

    _SEMANTIC_INDEX_CACHE[cache_key] = (signature, index)
    return index


def _embedding_cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for left_value, right_value in zip(left, right):
        dot += left_value * right_value
        left_norm += left_value * left_value
        right_norm += right_value * right_value
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


def _rank_chunks_lexically(
    question: str,
    chunks: list[SemanticChunk],
    *,
    limit: int,
) -> list[tuple[SemanticChunk, float]]:
    query_weights: dict[str, float] = {}
    _add_weighted_chunk_terms(query_weights, question, 1.0)
    query_norm = _vector_norm(query_weights)
    if query_norm <= 0:
        return []

    lowered_query = question.lower()
    query_terms = [term for term in extract_terms(question) if len(term) >= 2]
    scored: list[tuple[SemanticChunk, float]] = []
    for chunk in chunks:
        score = _lexical_cosine(query_weights, query_norm, chunk.term_weights, chunk.term_norm)
        if lowered_query and lowered_query in chunk.title.lower():
            score += 0.45
        if query_terms:
            snippet_lower = chunk.text.lower()
            hits = sum(1 for term in query_terms if term in snippet_lower)
            if hits > 0:
                score += min(0.35, hits * 0.08)
        if score > 0:
            scored.append((chunk, round(score, 4)))

    scored.sort(
        key=lambda entry: (
            entry[1],
            entry[0].note.created_at or datetime.min,
            entry[0].note.relative_path,
            -entry[0].chunk_index,
        ),
        reverse=True,
    )
    return scored[: max(1, limit)]


def _rank_chunks_by_vector(
    query_vector: list[float],
    index: SemanticChunkIndex,
    *,
    limit: int,
) -> list[tuple[SemanticChunk, float]]:
    if not index.embeddings or len(index.embeddings) != len(index.chunks):
        return []

    scored: list[tuple[SemanticChunk, float]] = []
    for chunk, embedding in zip(index.chunks, index.embeddings):
        score = _embedding_cosine(query_vector, embedding)
        if score > 0:
            scored.append((chunk, round(score, 4)))

    scored.sort(
        key=lambda entry: (
            entry[1],
            entry[0].note.created_at or datetime.min,
            entry[0].note.relative_path,
            -entry[0].chunk_index,
        ),
        reverse=True,
    )
    return scored[: max(1, limit)]


def _build_chunk_candidate_index(
    candidates: list[tuple[SemanticChunk, float]],
) -> tuple[str, list[SemanticChunk]]:
    lines: list[str] = []
    indexed: list[SemanticChunk] = []
    for chunk, _score in candidates:
        idx = len(indexed) + 1
        title = (chunk.title or "").strip()[:80]
        summary = (chunk.summary or "").strip()[:120]
        snippet = _truncate_text(chunk.text, 180)
        parts = [f"{idx}. [{title}]"]
        if summary:
            parts.append(summary)
        if snippet:
            parts.append(f"片段:{snippet}")
        lines.append(" | ".join(parts))
        indexed.append(chunk)
    return "\n".join(lines), indexed


def _parse_ranked_indices(response: str, result_count: int, limit: int) -> list[int]:
    cleaned = _strip_reasoning_blocks(response).strip()
    if not cleaned or cleaned == "无":
        return []

    selected: list[int] = []
    seen: set[int] = set()
    for raw_number in re.findall(r"\d+", cleaned):
        try:
            index = int(raw_number)
        except ValueError:
            continue
        if index < 1 or index > result_count or index in seen:
            continue
        selected.append(index)
        seen.add(index)
        if len(selected) >= limit:
            break
    return selected


_RAG_RERANK_SYSTEM_PROMPT = (
    "你是收藏库 RAG 语义精排助手。下面给你一组候选内容片段。"
    "请根据用户问题，选出真正相关的片段编号，按相关度从高到低排序。\n"
    "规则：\n"
    "1. 不要只看字面关键词，要理解语义。\n"
    "2. 优先保留能直接支持回答的问题片段。\n"
    "3. 最多输出 12 个编号。\n"
    "4. 只输出编号，用英文逗号分隔；如果没有相关内容，输出：无"
)


async def _ai_rerank_chunks(
    ai_config: dict[str, str],
    *,
    question: str,
    candidates: list[tuple[SemanticChunk, float]],
    limit: int,
) -> list[tuple[SemanticChunk, float]]:
    if not candidates:
        return []

    index_text, indexed_chunks = _build_chunk_candidate_index(candidates)
    try:
        response = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=[
                {"role": "system", "content": _RAG_RERANK_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"候选片段：\n{index_text}\n\n用户问题：{question}",
                },
            ],
            temperature=0.1,
        )
    except AiClientError:
        return candidates[:limit]

    selected = _parse_ranked_indices(response, len(indexed_chunks), limit)
    if not selected:
        return candidates[:limit]

    reranked: list[tuple[SemanticChunk, float]] = []
    for position, selected_index in enumerate(selected):
        chunk = indexed_chunks[selected_index - 1]
        reranked.append((chunk, round(max(0.1, 1.0 - position * 0.07), 4)))
    return reranked


def _build_rag_note_context_lines(note: KnowledgeBaseNote, index: int, snippets: list[str]) -> str:
    lines = [
        f"[{index}] 标题: {note.title}",
        f"[{index}] 摘要: {note.summary or '无已整理摘要'}",
        f"[{index}] 文件夹: {note.folder or '未归档'}",
        f"[{index}] 来源: {note.source or '无'}",
    ]
    for snippet_index, snippet in enumerate(snippets, start=1):
        lines.append(f"[{index}] 相关片段{snippet_index}: {snippet}")
    return "\n".join(lines)


def _merge_rag_chunks_into_context(
    ranked_chunks: list[tuple[SemanticChunk, float]],
    *,
    note_limit: int,
    note_count: int,
    retrieval_mode: str,
) -> RagGroundedContext:
    if not ranked_chunks:
        return RagGroundedContext(
            context_text="",
            ranked_notes=[],
            note_count=note_count,
            insufficient_context=True,
            retrieval_mode=retrieval_mode,
        )

    ordered_note_ids: list[str] = []
    note_entries: dict[str, dict[str, Any]] = {}

    for chunk, score in ranked_chunks:
        note_id = chunk.note.note_id
        entry = note_entries.get(note_id)
        if entry is None:
            if len(ordered_note_ids) >= note_limit:
                continue
            entry = {
                "note": chunk.note,
                "score": score,
                "snippets": [],
            }
            note_entries[note_id] = entry
            ordered_note_ids.append(note_id)
        else:
            entry["score"] = max(entry["score"], score)

        snippet = _truncate_text(_normalize_multiline_text(chunk.text), _RAG_CONTEXT_SNIPPET_LIMIT)
        if snippet and snippet not in entry["snippets"] and len(entry["snippets"]) < _RAG_MAX_SNIPPETS_PER_NOTE:
            entry["snippets"].append(snippet)

    ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
    context_blocks: list[str] = []
    for display_index, note_id in enumerate(ordered_note_ids, start=1):
        entry = note_entries[note_id]
        note = entry["note"]
        score = float(entry["score"])
        ranked_notes.append((note, round(score, 4)))
        context_blocks.append(_build_rag_note_context_lines(note, display_index, entry["snippets"]))

    return RagGroundedContext(
        context_text="\n\n".join(context_blocks).strip(),
        ranked_notes=ranked_notes,
        note_count=note_count,
        insufficient_context=not ranked_notes,
        retrieval_mode=retrieval_mode,
    )


async def _retrieve_rag_context(
    *,
    db: Session,
    user_id: str,
    ai_config: dict[str, str],
    question: str,
    top_k: int,
) -> RagGroundedContext:
    snapshot = _build_items_only_snapshot(db, user_id)
    if snapshot.note_count <= 0:
        return RagGroundedContext(
            context_text="",
            ranked_notes=[],
            note_count=0,
            insufficient_context=True,
            retrieval_mode="empty",
        )

    # Expand personal references using AI memories for better retrieval
    from routers.items import _expand_query_with_memories
    expanded_question = _expand_query_with_memories(db, user_id, question)

    index = await _build_semantic_chunk_index(snapshot=snapshot, user_id=user_id, ai_config=ai_config)
    candidate_limit = max(_RAG_VECTOR_MIN_CANDIDATES, max(1, top_k) * _RAG_VECTOR_CANDIDATE_MULTIPLIER)
    retrieval_mode = index.mode
    vector_candidates: list[tuple[SemanticChunk, float]] = []

    if index.mode == "semantic":
        try:
            query_vector = await _embed_query(ai_config, expanded_question)
        except AiClientError:
            query_vector = []
        if query_vector:
            vector_candidates = _rank_chunks_by_vector(query_vector, index, limit=candidate_limit)
        if not vector_candidates:
            retrieval_mode = "lexical"

    candidates = vector_candidates or _rank_chunks_lexically(expanded_question, index.chunks, limit=candidate_limit)
    rerank_limit = max(top_k, min(candidate_limit, max(4, top_k * 2)))
    reranked = await _ai_rerank_chunks(
        ai_config,
        question=question,
        candidates=candidates,
        limit=rerank_limit,
    )

    return _merge_rag_chunks_into_context(
        reranked,
        note_limit=max(1, top_k),
        note_count=snapshot.note_count,
        retrieval_mode=retrieval_mode,
    )


def _build_retrieval_query_from_conversation(conversation: list[dict[str, str]]) -> str:
    user_turns = [
        _clean_optional_string(message.get("content"))
        for message in conversation
        if message.get("role") == "user"
    ]
    filtered_turns = [turn for turn in user_turns if turn]
    if not filtered_turns:
        return ""
    if len(filtered_turns) == 1:
        return filtered_turns[0]
    return "\n".join(filtered_turns[-3:])


def _match_organized_analysis_heading(line: str | None) -> str | None:
    source = str(line or "")
    heading_match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", source)
    if heading_match:
        candidate = heading_match.group(1)
    else:
        if re.match(r"^\s*[-*+]\s+", source) or re.match(r"^\s*\d+\.\s+", source):
            return None
        candidate = source.strip()
        if not candidate:
            return None

    normalized = re.sub(r"[*_`~]+", "", candidate).strip().rstrip("：:").strip()
    if not normalized:
        return None

    aliases = {
        "摘要": "摘要",
        "核心要点": "核心要点",
        "关键要点": "核心要点",
        "要点": "核心要点",
        "链接与待确认": "链接与待确认",
        "链接和待确认": "链接与待确认",
        "相关链接与待确认": "链接与待确认",
        "链接待确认": "链接与待确认",
        "相关链接": "链接与待确认",
        "待确认": "链接与待确认",
        "链接": "链接与待确认",
    }
    return aliases.get(normalized)


def _normalize_organized_analysis_body(text: str | None) -> str:
    normalized = _normalize_multiline_text(_strip_leading_analysis_heading(text))
    if not normalized:
        return ""

    normalized_lines: list[str] = []
    for raw_line in normalized.splitlines():
        heading = _match_organized_analysis_heading(raw_line)
        if heading:
            while normalized_lines and not normalized_lines[-1].strip():
                normalized_lines.pop()
            if normalized_lines:
                normalized_lines.append("")
            normalized_lines.append(f"## {heading}")
            continue
        normalized_lines.append(raw_line.rstrip())

    return _normalize_multiline_text("\n".join(normalized_lines))


def _normalize_organized_analysis_text(text: str, fallback_title: str | None = None) -> str:
    normalized = _normalize_multiline_text(_strip_leading_analysis_heading(_strip_reasoning_blocks(_strip_code_fence(text))))
    if not normalized:
        return ""
    if re.search(r"(?im)^\[[a-z_]+\]\s*$", normalized):
        sections: list[tuple[str, list[str]]] = []
        current_key = ""
        current_lines: list[str] = []
        for line in normalized.splitlines():
            match = re.match(r"^\[([a-z_]+)\]\s*$", line.strip(), flags=re.IGNORECASE)
            if match:
                if current_key:
                    sections.append((current_key, current_lines))
                current_key = match.group(1).lower()
                current_lines = []
                continue
            current_lines.append(line)
        if current_key:
            sections.append((current_key, current_lines))

        if sections:
            normalized_sections: list[str] = []
            for key, lines in sections:
                value = _normalize_multiline_text("\n".join(lines))
                if key == "body":
                    value = _normalize_organized_analysis_body(value)
                if not value and key != "detected_title":
                    continue
                normalized_sections.append(f"[{key}]\n{value}".rstrip())
            normalized = "\n\n".join(section for section in normalized_sections if section.strip()).strip()
        return normalized

    sections: list[str] = []
    if fallback_title:
        sections.append(f"[detected_title]\n{fallback_title}")
    sections.append(f"[body]\n{_normalize_organized_analysis_body(normalized)}")
    return "\n\n".join(section for section in sections if section.strip()).strip()


def _sanitize_conversation_messages(messages: list[Any]) -> list[dict[str, str]]:
    sanitized: list[dict[str, str]] = []
    for raw_message in messages[-_CHAT_HISTORY_LIMIT:]:
        if isinstance(raw_message, dict):
            role = _clean_optional_string(raw_message.get("role"))
            content = _clean_optional_string(raw_message.get("content"))
        else:
            role = _clean_optional_string(getattr(raw_message, "role", None))
            content = _clean_optional_string(getattr(raw_message, "content", None))
        if role not in {"user", "assistant"} or not content:
            continue
        sanitized.append({"role": role, "content": content})
    return sanitized


def _sanitize_saved_conversation_messages(messages: list[Any]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for raw_message in messages[-_SAVED_CHAT_HISTORY_LIMIT:]:
        payload = raw_message if isinstance(raw_message, dict) else raw_message.model_dump(mode="json")
        role = _clean_optional_string(payload.get("role"))
        content = _clean_optional_string(payload.get("content"))
        if role not in {"user", "assistant"} or not content:
            continue

        mode = "agent" if _clean_optional_string(payload.get("mode")) == "agent" else "chat"
        citations = payload.get("citations")
        tool_events = payload.get("tool_events")
        created_at = _clean_optional_string(payload.get("created_at"))

        sanitized.append(
            {
                "role": role,
                "content": content,
                "mode": mode,
                "citations": citations if isinstance(citations, list) else [],
                "tool_events": tool_events if isinstance(tool_events, list) else [],
                "note_count": max(0, int(payload.get("note_count") or 0)),
                "insufficient_context": bool(payload.get("insufficient_context")),
                "is_error": bool(payload.get("is_error")),
                "created_at": created_at or datetime.utcnow().isoformat(),
            }
        )
    return sanitized


def _load_saved_conversation_messages(raw_messages: str | None) -> list[dict[str, Any]]:
    if not raw_messages:
        return []
    try:
        payload = json.loads(raw_messages)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return _sanitize_saved_conversation_messages(payload)


def _derive_conversation_title(
    messages: list[dict[str, Any]],
    *,
    explicit_title: str | None = None,
    current_item: Item | None = None,
) -> str:
    title = _clean_optional_string(explicit_title)
    if title:
        return _truncate_text(_normalize_multiline_text(title).split("\n", 1)[0], 80)

    for message in messages:
        if message.get("role") != "user":
            continue
        content = _clean_optional_string(message.get("content"))
        if content:
            return _truncate_text(_normalize_multiline_text(content).split("\n", 1)[0], 80)

    if current_item is not None:
        fallback_title = _clean_optional_string(current_item.title) or f"Item {current_item.id}"
        return _truncate_text(f"{fallback_title} 对话", 80)
    return "未命名对话"


def _build_conversation_search_text(
    title: str,
    *,
    current_item: Item | None,
    messages: list[dict[str, Any]],
) -> str:
    parts = [title]
    if current_item is not None:
        parts.extend(
            [
                _clean_optional_string(current_item.title) or "",
                _clean_optional_string(current_item.source_url) or "",
                _normalize_multiline_text(current_item.canonical_text),
            ]
        )
    parts.extend(_normalize_multiline_text(message.get("content")) for message in messages)
    combined = "\n".join(part for part in parts if part)
    return _truncate_text(combined, 20000)


def _conversation_last_message_preview(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        content = _clean_optional_string(message.get("content"))
        if content:
            return _truncate_text(_normalize_multiline_text(content).replace("\n", " "), 160)
    return None


def _serialize_ai_conversation_summary(conversation: AiConversation) -> AiConversationSummaryResponse:
    messages = _load_saved_conversation_messages(conversation.messages_json)
    current_item = getattr(conversation, "current_item", None)
    current_item_title = _clean_optional_string(current_item.title if current_item else None)
    return AiConversationSummaryResponse(
        id=conversation.id,
        title=_clean_optional_string(conversation.title) or "未命名对话",
        mode="agent" if _clean_optional_string(conversation.mode) == "agent" else "chat",
        current_item_id=_clean_optional_string(conversation.current_item_id),
        current_item_title=current_item_title,
        message_count=len(messages),
        last_message_preview=_conversation_last_message_preview(messages),
        created_at=conversation.created_at or datetime.utcnow(),
        updated_at=conversation.updated_at or conversation.created_at or datetime.utcnow(),
        last_message_at=conversation.last_message_at,
    )


def _serialize_ai_conversation(conversation: AiConversation) -> AiConversationResponse:
    summary = _serialize_ai_conversation_summary(conversation)
    messages = [
        AiConversationStoredMessage.model_validate(message)
        for message in _load_saved_conversation_messages(conversation.messages_json)
    ]
    return AiConversationResponse(**summary.model_dump(mode="python"), messages=messages)


def _tool_note_result(note: KnowledgeBaseNote, score: float = 0.0) -> dict[str, Any]:
    return {
        "note_id": note.note_id,
        "item_id": note.item_id,
        "title": note.title,
        "summary": note.summary or None,
        "folder": note.folder or None,
        "relative_path": note.relative_path,
        "source": note.source,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "score": round(float(score or 0.0), 4),
        "excerpt": note.excerpt or None,
    }


def _tool_item_result(item: Item, note: KnowledgeBaseNote | None = None) -> dict[str, Any]:
    page_notes_text = ""
    if hasattr(item, "page_notes") and item.page_notes:
        parts = []
        for pn in item.page_notes:
            title = _clean_optional_string(pn.title) or "无标题"
            content = _clean_optional_string(pn.content) or ""
            parts.append(f"【{title}】{content}" if content else f"【{title}】")
        page_notes_text = _truncate_text(" | ".join(parts), 500)
    result: dict[str, Any] = {
        "item_id": item.id,
        "title": _clean_optional_string(item.title) or f"Item {item.id}",
        "folder_names": _extract_item_folder_names(item),
        "source_url": _clean_optional_string(item.source_url),
        "parse_status": item.parse_status or "idle",
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "summary": note.summary if note else None,
        "excerpt": note.excerpt if note else _truncate_text(item.canonical_text or item.extracted_text, 220),
        "obsidian_path": _clean_optional_string(item.obsidian_path),
        "notion_page_id": _clean_optional_string(item.notion_page_id),
    }
    if page_notes_text:
        result["user_notes"] = page_notes_text
    return result


def _append_unique_ranked_notes(
    bucket: list[tuple[KnowledgeBaseNote, float]],
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
) -> None:
    seen = {note.note_id for note, _ in bucket}
    for note, score in ranked_notes:
        if note.note_id in seen:
            continue
        bucket.append((note, score))
        seen.add(note.note_id)


def _annotate_result_with_citation_refs(
    result: dict[str, Any],
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
    collected_notes: list[tuple[KnowledgeBaseNote, float]],
) -> dict[str, Any]:
    """Add citation ref numbers to tool result items based on their position in collected_notes.

    This ensures the LLM uses the same [N] numbers that _filter_ranked_notes_by_citation_markers
    will resolve, preventing mismatched citations.
    """
    if not ranked_notes or "results" not in result:
        return result
    # Build note_id → 1-based position in collected_notes
    note_id_to_pos: dict[str, int] = {
        note.note_id: idx + 1 for idx, (note, _) in enumerate(collected_notes)
    }
    # Build item_id → note_id from ranked_notes for lookup
    item_id_to_note_id: dict[str, str] = {}
    for note, _ in ranked_notes:
        if note.item_id:
            item_id_to_note_id[note.item_id] = note.note_id
    items = result.get("results")
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("item_id") or ""
        note_id = item_id_to_note_id.get(item_id) or f"item::{item_id}"
        pos = note_id_to_pos.get(note_id)
        if pos is not None:
            item["ref"] = pos
    return result


def _append_unique_updated_items(
    bucket: list[dict[str, Any]],
    updated_items: list[dict[str, Any]],
) -> None:
    seen_ids = {str(item.get("id") or "") for item in bucket}
    for item in updated_items:
        item_id = str(item.get("id") or "")
        if not item_id or item_id in seen_ids:
            continue
        bucket.append(item)
        seen_ids.add(item_id)


def _agent_permission_flags(settings: Settings | None) -> dict[str, bool]:
    return {
        "manage_folders": coerce_bool(
            getattr(settings, "ai_agent_can_manage_folders", None),
            AI_AGENT_DEFAULT_CAN_MANAGE_FOLDERS,
        ),
        "parse_content": coerce_bool(
            getattr(settings, "ai_agent_can_parse_content", None),
            AI_AGENT_DEFAULT_CAN_PARSE_CONTENT,
        ),
        "sync_obsidian": coerce_bool(
            getattr(settings, "ai_agent_can_sync_obsidian", None),
            AI_AGENT_DEFAULT_CAN_SYNC_OBSIDIAN,
        ),
        "sync_notion": coerce_bool(
            getattr(settings, "ai_agent_can_sync_notion", None),
            AI_AGENT_DEFAULT_CAN_SYNC_NOTION,
        ),
        "execute_commands": coerce_bool(
            getattr(settings, "ai_agent_can_execute_commands", None),
            AI_AGENT_DEFAULT_CAN_EXECUTE_COMMANDS,
        ),
        "web_search": coerce_bool(
            getattr(settings, "ai_agent_can_web_search", None),
            AI_AGENT_DEFAULT_CAN_WEB_SEARCH,
        ),
        "run_computer_commands": coerce_bool(
            getattr(settings, "ai_agent_can_run_computer_commands", None),
            AI_AGENT_DEFAULT_CAN_RUN_COMPUTER_COMMANDS,
        ),
    }


def _agent_permissions(settings: Settings | None) -> list[str]:
    permissions = ["search_library"]
    flags = _agent_permission_flags(settings)
    obsidian_ready = bool(
        _clean_optional_string(settings.obsidian_rest_api_url if settings else None)
        and _get_setting_secret(settings, "obsidian_api_key")
    )
    notion_ready = bool(
        _get_setting_secret(settings, "notion_api_token")
        and _clean_optional_string(settings.notion_database_id if settings else None)
        and _NOTION_ID_RE.search(_clean_optional_string(settings.notion_database_id if settings else None) or "")
    )

    if flags["manage_folders"]:
        permissions.append("manage_folders")
    if flags["parse_content"]:
        permissions.append("parse_content")
    if flags["sync_obsidian"] and obsidian_ready:
        permissions.append("sync_obsidian")
    if flags["sync_notion"] and notion_ready:
        permissions.append("sync_notion")
    if flags["execute_commands"]:
        permissions.append("execute_commands")
    if flags["web_search"]:
        permissions.append("web_search")
    if flags["run_computer_commands"]:
        permissions.append("run_computer_commands")
    return permissions


def _build_agent_tools(agent_permissions: list[str]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "search_library_items",
                "description": (
                    "Search saved items in the user's library. "
                    "The search uses keyword matching, so choose your query terms carefully. "
                    "Tips: use specific keywords rather than full sentences; "
                    "try synonyms and related concepts if the first search doesn't yield good results; "
                    "call this tool multiple times with different queries to improve recall."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 8},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_item_details",
                "description": "Read one saved website item by item_id, including its note summary if available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                    },
                    "required": ["item_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_recent_notes",
                "description": (
                    "List saved items from the library. "
                    "Supports filtering by scope (all/unfiled) and platform. "
                    "Returns item_id, title, folder info, excerpt for each item."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                        "scope": {
                            "type": "string",
                            "enum": ["all", "unfiled"],
                            "description": "'unfiled' = only items not in any folder. Default 'all'.",
                        },
                        "platform": {
                            "type": "string",
                            "description": "Filter by platform (e.g. 'xiaohongshu', 'douyin', 'wechat', 'github', 'generic').",
                        },
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_related_notes",
                "description": "Find related items for one saved item by item_id.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 6},
                    },
                    "required": ["item_id"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_folders",
                "description": "List the current folders available in the website library.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "save_memory",
                "description": (
                    "Save a piece of learned knowledge to your long-term memory. "
                    "Use this proactively when you discover user preferences, patterns, or corrections. "
                    "Examples: how the user organizes folders, preferred response style, domain interests, "
                    "classification rules the user established or corrected."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "What to remember. Be concise and specific.",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["learned", "preference", "correction"],
                            "description": (
                                "'learned' = observed pattern or fact about user's library/habits, "
                                "'preference' = explicit user preference, "
                                "'correction' = user corrected your behavior."
                            ),
                        },
                    },
                    "required": ["content", "type"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "delete_memory",
                "description": "Delete an outdated or wrong memory entry by its ID.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                    },
                    "required": ["memory_id"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    if "manage_folders" in agent_permissions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "list_tags",
                    "description": "List all existing tags in the user's library, including item counts when available.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "assign_item_tags",
                    "description": "Assign one saved item to one or more tags using tag IDs or tag names. Replaces the item's current tags.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "tag_ids": {"type": "array", "items": {"type": "string"}},
                            "tag_names": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["item_id"],
                        "additionalProperties": False,
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "create_tag",
                    "description": "Create a new tag in the user's library, or return the existing tag if the name already exists.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The tag name to create."},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "batch_assign_item_tags",
                    "description": (
                        "Assign tags to multiple items in one call. "
                        "Each assignment maps one item_id to one or more tag names. "
                        "Use this for bulk tagging instead of calling assign_item_tags repeatedly."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "assignments": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "item_id": {"type": "string"},
                                        "tag_names": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["item_id", "tag_names"],
                                },
                                "description": "List of {item_id, tag_names} assignments.",
                            },
                        },
                        "required": ["assignments"],
                        "additionalProperties": False,
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "assign_item_folders",
                    "description": "Assign one saved item to one or more folders using folder IDs or folder names.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                            "folder_ids": {"type": "array", "items": {"type": "string"}},
                            "folder_names": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["item_id"],
                        "additionalProperties": False,
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "create_folder",
                    "description": "Create a new folder in the user's library. Returns the created folder's ID and name. Supports nesting up to 2 levels by specifying parent_id.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "The folder name to create."},
                            "parent_id": {"type": "string", "description": "Optional parent folder ID for nesting (max 2 levels)."},
                        },
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "batch_assign_item_folders",
                    "description": (
                        "Assign multiple items to folders in one call. "
                        "Each assignment maps one item_id to one or more folder names. "
                        "Use this for bulk organization instead of calling assign_item_folders repeatedly."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "assignments": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "item_id": {"type": "string"},
                                        "folder_names": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["item_id", "folder_names"],
                                },
                                "description": "List of {item_id, folder_names} assignments.",
                            },
                        },
                        "required": ["assignments"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    if "parse_content" in agent_permissions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "parse_item_content",
                    "description": "Trigger content parsing for a saved item by item_id.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                        },
                        "required": ["item_id"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    if "sync_obsidian" in agent_permissions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "sync_item_to_obsidian",
                    "description": "Sync a saved item to Obsidian.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                        },
                        "required": ["item_id"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    if "sync_notion" in agent_permissions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "sync_item_to_notion",
                    "description": "Sync a saved item to Notion.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "item_id": {"type": "string"},
                        },
                        "required": ["item_id"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    if "execute_commands" in agent_permissions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "export_items_to_zip",
                    "description": (
                        "Export saved items' COMPLETE text content to downloadable files in one step. "
                        "Filters by query AND/OR platform AND/OR content_type simultaneously. "
                        "IMPORTANT: Always includes the COMPLETE text, never truncated or summarized. "
                        "Use format='merged_md' to create a single consolidated markdown file. "
                        "IMPORTANT: output_filename must describe the content (e.g. '量化视频汇总.md'), never use generic names like 'export.md'. "
                        "When user asks for '打包/导出/下载/整理成文档', ALWAYS use this tool."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query to find items (e.g. 'github', 'AI', '量化', '股票')"},
                            "platform": {
                                "type": "string",
                                "description": "Filter by platform. Can combine with comma: 'douyin,xiaohongshu'. Values: github, xiaohongshu, douyin, wechat, generic, web",
                            },
                            "content_type": {
                                "type": "string",
                                "enum": ["video", "article", "all"],
                                "description": "video: only douyin/xiaohongshu video content. article: only wechat/web articles. all: everything (default).",
                            },
                            "item_ids": {"type": "array", "items": {"type": "string"}, "description": "Specific item IDs to export"},
                            "output_filename": {"type": "string", "description": "Output filename — MUST describe content, e.g. '量化视频汇总.md', 'GitHub项目合集.zip'. Never use generic 'export.md'."},
                            "format": {
                                "type": "string",
                                "enum": ["merged_md", "merged_txt", "zip_individual"],
                                "description": "merged_md: single markdown (default). merged_txt: single text. zip_individual: ZIP with separate files.",
                            },
                            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "description": "Max items to export (default 50)"},
                        },
                        "additionalProperties": False,
                    },
                },
            }
        )
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "execute_sandbox_command",
                    "description": (
                        "Execute commands in a sandboxed environment (exports/ dir and /tmp only). "
                        "Actions: git_clone, download_file, zip_files, list_files, read_file, write_file, "
                        "move_file, delete_file, run_command (whitelisted: git,curl,zip,python3,ls,find,etc), "
                        "batch (run multiple operations in one call). "
                        "IMPORTANT: Use 'batch' action with 'operations' array to run multiple commands at once "
                        "instead of calling this tool multiple times — this is MUCH faster. "
                        "NOTE: This sandbox is restricted to the exports/ directory. "
                        "NEVER use this tool for software installation, global package installs, git clone to the user's computer, "
                        "or project setup that should live outside exports/. "
                        "If the run_computer_command tool is available, use that instead for git clone, software installation, "
                        "project setup, and any task where the user wants files in a specific location on their computer "
                        "(e.g. home directory, ~/Projects, etc). Only use this sandbox for temporary/disposable operations."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [
                                    "batch",
                                    "git_clone", "download_file", "zip_files",
                                    "list_files", "read_file", "write_file",
                                    "move_file", "delete_file", "run_command",
                                ],
                            },
                            "operations": {
                                "type": "array",
                                "description": "For batch action: array of operations, each with its own action and params. Max 20.",
                                "items": {"type": "object"},
                            },
                            "url": {"type": "string", "description": "URL for git_clone or download_file"},
                            "path": {"type": "string", "description": "Relative file path within sandbox"},
                            "paths": {"type": "array", "items": {"type": "string"}, "description": "Multiple paths for zip_files"},
                            "content": {"type": "string", "description": "File content for write_file"},
                            "command": {"type": "string", "description": "Shell command for run_command"},
                            "output_filename": {"type": "string", "description": "Output filename for zip/download/move"},
                        },
                        "required": ["action"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    if "run_computer_commands" in agent_permissions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "run_computer_command",
                    "description": (
                        "Run a command on the user's computer. This requires explicit user approval before execution. "
                        "ALWAYS use this for git clone to local machine, software installation (brew/pip/pipx/npm/pnpm/yarn), "
                        "global package installs, GitHub project setup, running scripts, and any task where files should be in a real location "
                        "on the user's computer (not the sandbox exports/ directory). "
                        "The user will see the exact command and must click 'Allow' before it runs. "
                        "Always provide a clear description of what the command does and why. "
                        "Default working directory is the user's home directory (~)."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "The shell command to execute.",
                            },
                            "description": {
                                "type": "string",
                                "description": "Clear explanation of what this command does, shown to user for approval.",
                            },
                            "working_directory": {
                                "type": "string",
                                "description": "Optional working directory. Defaults to user's home directory.",
                            },
                        },
                        "required": ["command", "description"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    if "web_search" in agent_permissions:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": (
                        "Search the internet for real-time information using DuckDuckGo. "
                        "Use this when the user asks about external facts, current events, "
                        "or anything that requires information beyond the saved library. "
                        "Returns a list of search results with titles, URLs, and snippets."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query in any language.",
                            },
                            "max_results": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 10,
                                "description": "Number of results to return (default 5).",
                            },
                        },
                        "required": ["query"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    return tools


def _resolve_tool_target_folders(
    db: Session,
    user_id: str,
    folder_ids: list[str],
    folder_names: list[str],
) -> tuple[list[Folder], list[str]]:
    ordered: list[Folder] = []
    seen_ids: set[str] = set()
    missing_names: list[str] = []

    if folder_ids:
        folders = db.query(Folder).filter(Folder.user_id == user_id, Folder.id.in_(folder_ids)).all()
        folders_by_id = {folder.id: folder for folder in folders}
        for folder_id in folder_ids:
            folder = folders_by_id.get(folder_id)
            if folder and folder.id not in seen_ids:
                ordered.append(folder)
                seen_ids.add(folder.id)

    if folder_names:
        available_folders = db.query(Folder).filter(Folder.user_id == user_id).all()
        folders_by_name = {
            (folder.name or "").strip().lower(): folder
            for folder in available_folders
            if _clean_optional_string(folder.name)
        }
        for raw_name in folder_names:
            name = (raw_name or "").strip().lower()
            if not name:
                continue
            folder = folders_by_name.get(name)
            if not folder:
                missing_names.append(raw_name)
                continue
            if folder.id in seen_ids:
                continue
            ordered.append(folder)
            seen_ids.add(folder.id)

    return ordered, missing_names


def _resolve_tool_target_tags(
    db: Session,
    user_id: str,
    tag_ids: list[str],
    tag_names: list[str],
    *,
    create_missing: bool = False,
) -> tuple[list[Tag], list[str]]:
    ordered: list[Tag] = []
    seen_ids: set[str] = set()
    missing_names: list[str] = []

    if tag_ids:
        tags = db.query(Tag).filter(Tag.user_id == user_id, Tag.id.in_(tag_ids)).all()
        tags_by_id = {tag.id: tag for tag in tags}
        for tag_id in tag_ids:
            tag = tags_by_id.get(tag_id)
            if tag and tag.id not in seen_ids:
                ordered.append(tag)
                seen_ids.add(tag.id)

    tags_by_name = {
        _clean_tag_name(tag.name).lower(): tag
        for tag in db.query(Tag).filter(Tag.user_id == user_id).all()
        if _clean_tag_name(tag.name)
    }
    created = False

    for raw_name in tag_names:
        clean_name = _clean_tag_name(raw_name)
        lookup = clean_name.lower()
        if not lookup:
            continue
        tag = tags_by_name.get(lookup)
        if not tag and create_missing:
            tag = Tag(id=str(uuid.uuid4()), user_id=user_id, name=clean_name)
            db.add(tag)
            db.flush()
            tags_by_name[lookup] = tag
            created = True
        if not tag:
            missing_names.append(raw_name)
            continue
        if tag.id in seen_ids:
            continue
        ordered.append(tag)
        seen_ids.add(tag.id)

    if created:
        db.flush()

    return ordered, missing_names


_web_search_logger = logging.getLogger("web_search")


_WEB_SEARCH_FETCH_LIMIT = 3  # 最多抓取前 N 个结果的正文
_WEB_SEARCH_CONTENT_CHARS = 2000  # 每个页面抓取的最大字符数


async def _fetch_page_text(url: str, timeout: float = 10) -> str:
    """Fetch a URL and extract readable text content (best-effort)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
            )
            resp.raise_for_status()
            html_text = resp.text
    except Exception:
        return ""

    # Try trafilatura first (best quality)
    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(html_text, include_comments=False, include_tables=True)
        if extracted:
            return extracted[:_WEB_SEARCH_CONTENT_CHARS]
    except Exception:
        pass

    # Fallback: strip HTML tags
    import re as _re

    text = _re.sub(r"<script[^>]*>.*?</script>", "", html_text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r"<style[^>]*>.*?</style>", "", text, flags=_re.DOTALL | _re.IGNORECASE)
    text = _re.sub(r"<[^>]+>", " ", text)
    text = _re.sub(r"\s+", " ", text).strip()
    from html import unescape

    text = unescape(text)
    return text[:_WEB_SEARCH_CONTENT_CHARS]


async def _web_search_duckduckgo(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search DuckDuckGo and return results with title, url, snippet, and page content."""
    import httpx
    from html import unescape
    import asyncio

    results: list[dict[str, str]] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                },
            )
            resp.raise_for_status()
            html_text = resp.text

        # Parse results from DuckDuckGo HTML lite page
        import re as _re

        link_pattern = _re.compile(
            r'<a\s+[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            _re.DOTALL,
        )
        snippet_pattern = _re.compile(
            r'<a\s+[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            _re.DOTALL,
        )

        links = link_pattern.findall(html_text)
        snippets = snippet_pattern.findall(html_text)

        tag_re = _re.compile(r"<[^>]+>")
        for i, (raw_url, raw_title) in enumerate(links[:max_results]):
            title = unescape(tag_re.sub("", raw_title)).strip()
            snippet = ""
            if i < len(snippets):
                snippet = unescape(tag_re.sub("", snippets[i])).strip()

            # DuckDuckGo redirects through //duckduckgo.com/l/?uddg=...
            url = raw_url
            if "uddg=" in url:
                from urllib.parse import unquote, urlparse, parse_qs

                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                if "uddg" in qs:
                    url = unquote(qs["uddg"][0])

            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})

        # Fetch page content for top results to give AI more context
        fetch_count = min(len(results), _WEB_SEARCH_FETCH_LIMIT)
        if fetch_count > 0:
            tasks = [_fetch_page_text(results[i]["url"]) for i in range(fetch_count)]
            page_texts = await asyncio.gather(*tasks, return_exceptions=True)
            for i, text in enumerate(page_texts):
                if isinstance(text, str) and text.strip():
                    results[i]["content"] = text

    except Exception as exc:
        _web_search_logger.warning("DuckDuckGo 搜索失败: %s", exc)

    return results


async def _execute_agent_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    db: Session,
    user_id: str,
    snapshot: KnowledgeBaseSnapshot,
    agent_permissions: list[str],
    ai_config: dict[str, str] | None = None,
) -> tuple[dict[str, Any], AiToolEventResponse, list[tuple[KnowledgeBaseNote, float]], list[dict[str, Any]]]:
    limit = max(1, min(int(arguments.get("limit") or 5), 10))

    if tool_name == "search_library_items":
        query = _clean_optional_string(arguments.get("query"))
        if not query:
            result = {"status": "error", "message": "query is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="搜索失败：缺少 query"), [], []
        from routers.items import rank_search_rows, _expand_query_with_memories

        # Expand personal references using AI memories
        expanded_query = _expand_query_with_memories(db, user_id, query)

        candidate_rows = (
            db.query(
                Item.id,
                Item.user_id,
                Item.title,
                Item.canonical_text,
                Item.source_url,
                Item.platform,
                Item.created_at,
            )
            .filter(Item.user_id == user_id)
            .all()
        )
        ranked_item_ids = rank_search_rows(candidate_rows, expanded_query)[:limit]
        items = db.query(Item).filter(Item.user_id == user_id, Item.id.in_(ranked_item_ids)).all() if ranked_item_ids else []
        items_by_id = {item.id: item for item in items}
        ordered_items = [items_by_id[item_id] for item_id in ranked_item_ids if item_id in items_by_id]
        ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
        for item in ordered_items:
            virtual = _item_to_virtual_note(item)
            virtual = prepare_note_for_similarity(virtual)
            ranked_notes.append((virtual, 1.0))
        result = {
            "status": "ok",
            "query": query,
            "results": [_tool_item_result(item) for item in ordered_items],
        }
        summary = f"搜索完成，找到 {len(ordered_items)} 条结果"
        return result, AiToolEventResponse(name=tool_name, summary=summary), ranked_notes, []

    if tool_name == "get_item_details":
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="读取详情失败：Item not found"), [], []
        result = {"status": "ok", "item": _tool_item_result(item)}
        return result, AiToolEventResponse(name=tool_name, summary=f"已读取《{item.title or item.id}》的详情"), [], []

    if tool_name == "list_recent_notes":
        list_limit = max(1, min(int(arguments.get("limit") or 10), 50))
        scope = _clean_optional_string(arguments.get("scope")) or "all"
        platform_filter = _clean_optional_string(arguments.get("platform"))

        q = db.query(Item).filter(Item.user_id == user_id)

        if scope == "unfiled":
            q = q.outerjoin(ItemFolderLink, ItemFolderLink.item_id == Item.id).filter(ItemFolderLink.item_id.is_(None))
        if platform_filter:
            q = q.filter(Item.platform == platform_filter)

        items = q.order_by(Item.created_at.desc()).limit(list_limit).all()

        ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
        for item in items:
            virtual = _item_to_virtual_note(item)
            virtual = prepare_note_for_similarity(virtual)
            ranked_notes.append((virtual, 1.0))
        scope_label = "未归档" if scope == "unfiled" else "最近"
        result = {"status": "ok", "results": [_tool_item_result(item) for item in items]}
        summary = f"已列出{scope_label} {len(items)} 条收藏内容"
        return result, AiToolEventResponse(name=tool_name, summary=summary), ranked_notes, []

    if tool_name == "get_related_notes":
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="查找相关内容失败：Item not found"), [], []
        seed_note = _build_seed_note_from_item(item)
        ranked = rank_related_notes(snapshot, seed_note, limit=limit) if snapshot.note_count else []
        result = {
            "status": "ok",
            "item_id": item.id,
            "results": [_tool_note_result(note, score) for note, score in ranked],
        }
        summary = f"已找到 {len(ranked)} 条相关内容"
        return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, []

    if tool_name == "list_folders":
        folders = (
            db.query(Folder)
            .filter(Folder.user_id == user_id)
            .order_by(Folder.sort_order.asc(), Folder.created_at.asc(), func.lower(Folder.name).asc(), Folder.id.asc())
            .all()
        )
        result = {
            "status": "ok",
            "folders": [
                {
                    "folder_id": folder.id,
                    "name": folder.name,
                    "sort_order": folder.sort_order or 0,
                    "parent_id": folder.parent_id,
                }
                for folder in folders
            ],
        }
        summary = f"已列出 {len(folders)} 个文件夹"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], []

    if tool_name == "save_memory":
        content = _clean_optional_string(arguments.get("content"))
        memory_type = _clean_optional_string(arguments.get("type")) or "learned"
        if not content:
            result = {"status": "error", "message": "content is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="记忆保存失败：缺少内容"), [], []
        if memory_type not in ("learned", "preference", "correction"):
            memory_type = "learned"
        import datetime as _dt
        now = _dt.datetime.utcnow()
        memory = AiMemory(
            user_id=user_id,
            type=memory_type,
            content=content.strip(),
            created_at=now,
            updated_at=now,
        )
        db.add(memory)
        db.commit()
        db.refresh(memory)
        result = {"status": "ok", "memory_id": memory.id, "type": memory_type}
        type_label = {"learned": "学到的", "preference": "用户偏好", "correction": "纠正"}.get(memory_type, memory_type)
        return result, AiToolEventResponse(
            name=tool_name,
            summary=f"已记住（{type_label}）：{_truncate_text(content, 40)}",
            detail=content.strip(),
        ), [], []

    if tool_name == "delete_memory":
        memory_id = _clean_optional_string(arguments.get("memory_id"))
        if not memory_id:
            result = {"status": "error", "message": "memory_id is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="删除记忆失败：缺少 ID"), [], []
        memory = db.query(AiMemory).filter(AiMemory.id == memory_id, AiMemory.user_id == user_id).first()
        if not memory:
            result = {"status": "error", "message": "Memory not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="删除记忆失败：未找到"), [], []
        db.delete(memory)
        db.commit()
        result = {"status": "ok"}
        return result, AiToolEventResponse(name=tool_name, summary="已删除一条记忆"), [], []

    if tool_name == "assign_item_folders":
        if "manage_folders" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放文件夹管理权限"), [], []
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="移动文件夹失败：Item not found"), [], []
        folder_ids = [value for value in _coerce_text_list(arguments.get("folder_ids"), limit=12)]
        folder_names = [value for value in _coerce_text_list(arguments.get("folder_names"), limit=12)]
        folders, missing_names = _resolve_tool_target_folders(db, user_id, folder_ids, folder_names)
        if missing_names:
            result = {"status": "error", "message": f"Unknown folders: {', '.join(missing_names)}"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"找不到文件夹：{', '.join(missing_names)}"), [], []

        from routers.items import serialize_items, sync_item_folder_assignments

        sync_item_folder_assignments(item, folders)
        db.commit()
        db.refresh(item)
        updated_item = serialize_items([item])[0].model_dump(mode="json")
        result = {
            "status": "ok",
            "item": _tool_item_result(item),
        }
        folder_text = "、".join(_extract_item_folder_names(item)) or "未归档"
        summary = f"已更新《{item.title or item.id}》的文件夹为：{folder_text}"
        ranked: list[tuple[KnowledgeBaseNote, float]] = []
        return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, [updated_item]

    if tool_name == "list_tags":
        if "manage_folders" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放标签管理权限"), [], []
        rows = (
            db.query(Tag, func.count(ItemTagLink.item_id))
            .outerjoin(ItemTagLink, ItemTagLink.tag_id == Tag.id)
            .filter(Tag.user_id == user_id)
            .group_by(Tag.id)
            .order_by(Tag.name.asc())
            .all()
        )
        result = {
            "status": "ok",
            "tags": [
                {
                    "tag_id": tag.id,
                    "name": tag.name,
                    "item_count": int(count or 0),
                }
                for tag, count in rows
            ],
        }
        summary = f"已列出 {len(rows)} 个标签"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], []

    if tool_name == "assign_item_tags":
        if "manage_folders" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放标签管理权限"), [], []
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="打标签失败：Item not found"), [], []
        tag_ids = [value for value in _coerce_text_list(arguments.get("tag_ids"), limit=20)]
        tag_names = [value for value in _coerce_text_list(arguments.get("tag_names"), limit=20)]
        tags, missing_names = _resolve_tool_target_tags(db, user_id, tag_ids, tag_names, create_missing=True)
        if missing_names:
            result = {"status": "error", "message": f"Unknown tags: {', '.join(missing_names)}"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"找不到标签：{', '.join(missing_names)}"), [], []

        from routers.items import serialize_items

        db.query(ItemTagLink).filter(ItemTagLink.item_id == item.id).delete(synchronize_session=False)
        for tag in tags:
            db.add(ItemTagLink(item_id=item.id, tag_id=tag.id, source="ai"))
        db.commit()
        db.refresh(item)
        updated_item = serialize_items([item])[0].model_dump(mode="json")
        result = {
            "status": "ok",
            "item": _tool_item_result(item),
            "tags": updated_item.get("tag_names") or [],
        }
        tag_text = "、".join(updated_item.get("tag_names") or []) or "无标签"
        summary = f"已更新《{item.title or item.id}》的标签为：{tag_text}"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], [updated_item]

    if tool_name == "parse_item_content":
        if "parse_content" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放内容解析权限"), [], []
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="内容解析失败：Item not found"), [], []

        from routers.items import _mark_item_parse_processing, _store_item_parse_failure, parse_item_content_for_item, serialize_items

        try:
            _mark_item_parse_processing(item)
            db.commit()
            db.refresh(item)
            parse_item_content_for_item(item)
            db.commit()
            db.refresh(item)
            updated_item = serialize_items([item])[0].model_dump(mode="json")
            result = {
                "status": "ok",
                "item": _tool_item_result(item),
            }
            summary = f"已完成《{item.title or item.id}》的内容解析"
            ranked: list[tuple[KnowledgeBaseNote, float]] = []
            return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, [updated_item]
        except Exception as exc:
            db.rollback()
            item = _get_user_item(db, user_id, item_id or "")
            if item:
                _store_item_parse_failure(item, str(exc))
                db.commit()
            result = {"status": "error", "message": str(exc)}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"内容解析失败：{exc}"), [], []

    if tool_name == "sync_item_to_obsidian":
        if "sync_obsidian" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放 Obsidian 同步权限"), [], []
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="Obsidian 同步失败：Item not found"), [], []

        from routers.connect import _sync_item_to_obsidian
        from routers.items import serialize_items

        try:
            result = await _sync_item_to_obsidian(item, db)
            db.refresh(item)
            summary = f"已触发《{item.title or item.id}》同步到 Obsidian"
            updated_item = serialize_items([item])[0].model_dump(mode="json")
            return result, AiToolEventResponse(name=tool_name, summary=summary), [], [updated_item]
        except HTTPException as exc:
            result = {"status": "error", "message": str(exc.detail)}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"Obsidian 同步失败：{exc.detail}"), [], []

    if tool_name == "sync_item_to_notion":
        if "sync_notion" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放 Notion 同步权限"), [], []
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="Notion 同步失败：Item not found"), [], []

        from routers.connect import _sync_item_to_notion
        from routers.items import serialize_items

        try:
            result = await _sync_item_to_notion(item, db)
            db.refresh(item)
            summary = f"已触发《{item.title or item.id}》同步到 Notion"
            updated_item = serialize_items([item])[0].model_dump(mode="json")
            return result, AiToolEventResponse(name=tool_name, summary=summary), [], [updated_item]
        except HTTPException as exc:
            result = {"status": "error", "message": str(exc.detail)}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"Notion 同步失败：{exc.detail}"), [], []

    if tool_name == "export_items_to_zip":
        if "execute_commands" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放命令执行权限"), [], []

        import zipfile
        from pathlib import Path
        from paths import EXPORTS_DIR

        query = _clean_optional_string(arguments.get("query"))
        platform = _clean_optional_string(arguments.get("platform"))
        content_type = _clean_optional_string(arguments.get("content_type")) or "all"
        item_ids_raw = arguments.get("item_ids") or []
        export_format = _clean_optional_string(arguments.get("format")) or "merged_md"
        export_limit = max(1, min(int(arguments.get("limit") or 50), 100))

        # Determine default output filename based on format
        default_filenames = {"merged_md": "export.md", "merged_txt": "export.txt", "zip_individual": "export.zip"}
        output_filename = _clean_optional_string(arguments.get("output_filename")) or default_filenames.get(export_format, "export.md")

        try:
            # Build base query
            q = db.query(Item).filter(Item.user_id == user_id, Item.status == "ready")

            if item_ids_raw:
                q = q.filter(Item.id.in_(item_ids_raw))
            else:
                # --- Platform filter ---
                if platform:
                    platforms = [p.strip().lower() for p in platform.split(",") if p.strip()]
                    platform_conditions = []
                    for p in platforms:
                        if p == "github":
                            platform_conditions.append(Item.platform == "github")
                            platform_conditions.append(Item.source_url.like("%github.com/%"))
                        else:
                            platform_conditions.append(Item.platform == p)
                    if platform_conditions:
                        q = q.filter(or_(*platform_conditions))

                # --- Content type filter ---
                if content_type == "video":
                    q = q.filter(Item.platform.in_(["douyin", "xiaohongshu"]))
                elif content_type == "article":
                    q = q.filter(Item.platform.in_(["wechat", "generic", "web"]))

                # --- Query/keyword filter (applied ON TOP of platform filter, not replacing it) ---
                if query:
                    from routers.items import rank_search_rows

                    # Get candidate IDs from the already-filtered query
                    filtered_ids_q = q.with_entities(Item.id).all()
                    filtered_id_set = {row[0] for row in filtered_ids_q}

                    if filtered_id_set:
                        candidate_rows = (
                            db.query(Item.id, Item.user_id, Item.title, Item.canonical_text, Item.source_url, Item.platform, Item.created_at)
                            .filter(Item.user_id == user_id, Item.id.in_(filtered_id_set))
                            .all()
                        )
                        ranked_ids = rank_search_rows(candidate_rows, query)[:export_limit]

                        # Fallback: if compound query matches nothing, try splitting into sub-terms
                        if not ranked_ids and len(query) > 2:
                            # Split by whitespace/punctuation first
                            sub_terms = [w.strip() for w in re.split(r'[\s,，、/\-_]+', query) if len(w.strip()) > 1]
                            # If still one big term, use 2-char sliding window (works for Chinese)
                            if len(sub_terms) <= 1:
                                sub_terms = [query[i:i+2] for i in range(0, len(query) - 1)]
                            for sub in sub_terms:
                                sub_ids = rank_search_rows(candidate_rows, sub)[:export_limit]
                                if sub_ids:
                                    ranked_ids = sub_ids
                                    break

                        if ranked_ids:
                            q = q.filter(Item.id.in_(ranked_ids))

            items = q.order_by(Item.created_at.desc()).limit(export_limit).all()

            if not items:
                result = {"status": "ok", "message": "没有找到匹配的内容", "exported_count": 0}
                return result, AiToolEventResponse(name=tool_name, summary="没有找到匹配的内容"), [], []

            EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
            exported_titles: list[str] = []

            def _build_item_full_text(item: Item, index: int, is_markdown: bool) -> str:
                """Build COMPLETE text for one item — never truncated."""
                parts: list[str] = []
                title = item.title or "无标题"
                if is_markdown:
                    parts.append(f"# {index}. {title}\n")
                    parts.append(f"- **来源**: {item.source_url or '未知'}")
                    parts.append(f"- **平台**: {item.platform or '未知'}")
                    parts.append(f"- **保存时间**: {item.created_at}")
                    if _extract_item_folder_names(item):
                        parts.append(f"- **文件夹**: {', '.join(_extract_item_folder_names(item))}")
                    parts.append("")
                    parts.append("---\n")
                else:
                    parts.append(f"{'='*80}")
                    parts.append(f"[{index}] {title}")
                    parts.append(f"来源: {item.source_url or '未知'}")
                    parts.append(f"平台: {item.platform or '未知'}")
                    parts.append(f"保存时间: {item.created_at}")
                    parts.append(f"{'='*80}\n")

                # FULL canonical_text — no truncation
                if item.canonical_text:
                    parts.append(item.canonical_text)

                # FULL extracted_text (OCR, subtitles, etc.)
                if item.extracted_text:
                    separator = "\n\n## 提取文本\n" if is_markdown else "\n\n--- 提取文本 ---\n"
                    parts.append(separator)
                    parts.append(item.extracted_text)

                # FULL OCR text
                if item.ocr_text:
                    separator = "\n\n## OCR 文本\n" if is_markdown else "\n\n--- OCR 文本 ---\n"
                    parts.append(separator)
                    parts.append(item.ocr_text)

                # Frame texts (video subtitles/transcripts)
                frame_texts = []
                try:
                    frame_texts = json.loads(item.frame_texts_json) if item.frame_texts_json else []
                except (json.JSONDecodeError, TypeError):
                    pass
                if frame_texts:
                    separator = "\n\n## 视频字幕/帧文本\n" if is_markdown else "\n\n--- 视频字幕/帧文本 ---\n"
                    parts.append(separator)
                    for ft in frame_texts:
                        if isinstance(ft, dict):
                            ts = ft.get("timestamp", "")
                            txt = ft.get("text", "")
                            parts.append(f"[{ts}] {txt}" if ts else txt)
                        elif isinstance(ft, str):
                            parts.append(ft)

                # Page notes (user's content analysis / AI analysis)
                if hasattr(item, "page_notes") and item.page_notes:
                    for pn in item.page_notes:
                        if pn.content and pn.content.strip():
                            separator = f"\n\n## 内容分析: {pn.title}\n" if is_markdown else f"\n\n--- 内容分析: {pn.title} ---\n"
                            parts.append(separator)
                            parts.append(pn.content)

                parts.append("\n")
                return "\n".join(parts)

            if export_format in ("merged_md", "merged_txt"):
                is_md = export_format == "merged_md"
                merged_parts: list[str] = []

                for i, item in enumerate(items):
                    merged_parts.append(_build_item_full_text(item, i + 1, is_md))
                    exported_titles.append(item.title or item.id)

                merged_content = "\n".join(merged_parts)
                out_path = EXPORTS_DIR / output_filename
                out_path.write_text(merged_content, encoding="utf-8")

            else:  # zip_individual
                if not output_filename.endswith(".zip"):
                    output_filename += ".zip"
                out_path = EXPORTS_DIR / output_filename
                with zipfile.ZipFile(str(out_path), "w", zipfile.ZIP_DEFLATED) as zf:
                    for i, item in enumerate(items):
                        content = _build_item_full_text(item, i + 1, is_markdown=True)
                        safe_title = re.sub(r'[\\/:*?"<>|]', '_', (item.title or f"item_{i}")[:80])
                        filename = f"{i+1:02d}_{safe_title}.md"
                        zf.writestr(filename, content)
                        exported_titles.append(item.title or item.id)

            download_url = f"/api/ai/exports/{output_filename}"
            summary = f"已导出 {len(items)} 条完整内容到 {output_filename}"
            result = {
                "status": "ok",
                "exported_count": len(items),
                "exported_titles": exported_titles[:30],
                "download_url": download_url,
                "output": summary,
            }
            return result, AiToolEventResponse(name=tool_name, summary=summary, download_url=download_url), [], []
        except Exception as exc:
            logger.exception("Export items error")
            result = {"status": "error", "message": str(exc)}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"导出失败：{exc}"), [], []

    if tool_name == "create_folder":
        if "manage_folders" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放文件夹管理权限"), [], []
        folder_name = _clean_optional_string(arguments.get("name"))
        parent_id = _clean_optional_string(arguments.get("parent_id"))
        if not folder_name:
            result = {"status": "error", "message": "name is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="创建文件夹失败：缺少名称"), [], []
        # Check duplicate within same parent
        dup_query = db.query(Folder).filter(
            Folder.user_id == user_id,
            func.lower(Folder.name) == folder_name.strip().lower(),
        )
        if parent_id:
            dup_query = dup_query.filter(Folder.parent_id == parent_id)
        else:
            dup_query = dup_query.filter(Folder.parent_id.is_(None))
        existing = dup_query.first()
        if existing:
            result = {
                "status": "ok",
                "message": "文件夹已存在",
                "folder_id": existing.id,
                "folder_name": existing.name,
            }
            return result, AiToolEventResponse(name=tool_name, summary=f"文件夹「{existing.name}」已存在"), [], []
        if parent_id:
            parent = db.query(Folder).filter(Folder.id == parent_id, Folder.user_id == user_id).first()
            if not parent:
                result = {"status": "error", "message": "Parent folder not found"}
                return result, AiToolEventResponse(name=tool_name, status="failed", summary="父文件夹不存在"), [], []
            if parent.parent_id:
                result = {"status": "error", "message": "Maximum nesting depth exceeded"}
                return result, AiToolEventResponse(name=tool_name, status="failed", summary="超过最大嵌套层级"), [], []
        import datetime as _dt
        now = _dt.datetime.utcnow()
        sort_q = db.query(func.max(Folder.sort_order)).filter(Folder.user_id == user_id)
        if parent_id:
            sort_q = sort_q.filter(Folder.parent_id == parent_id)
        else:
            sort_q = sort_q.filter(Folder.parent_id.is_(None))
        max_sort = sort_q.scalar()
        folder = Folder(
            user_id=user_id,
            name=folder_name.strip(),
            parent_id=parent_id,
            sort_order=int(max_sort if max_sort is not None else -1) + 1,
            created_at=now,
            updated_at=now,
        )
        db.add(folder)
        db.commit()
        db.refresh(folder)
        result = {
            "status": "ok",
            "folder_id": folder.id,
            "folder_name": folder.name,
        }
        return result, AiToolEventResponse(name=tool_name, summary=f"已创建文件夹「{folder.name}」"), [], []

    if tool_name == "create_tag":
        if "manage_folders" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放标签管理权限"), [], []
        tag_name = _clean_tag_name(_clean_optional_string(arguments.get("name")))
        if not tag_name:
            result = {"status": "error", "message": "name is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="创建标签失败：缺少名称"), [], []

        existing = db.query(Tag).filter(Tag.user_id == user_id, func.lower(Tag.name) == tag_name.lower()).first()
        if existing:
            result = {
                "status": "ok",
                "message": "标签已存在",
                "tag_id": existing.id,
                "tag_name": existing.name,
            }
            return result, AiToolEventResponse(name=tool_name, summary=f"标签「{existing.name}」已存在"), [], []

        tag = Tag(id=str(uuid.uuid4()), user_id=user_id, name=tag_name)
        db.add(tag)
        db.commit()
        db.refresh(tag)
        result = {
            "status": "ok",
            "tag_id": tag.id,
            "tag_name": tag.name,
        }
        return result, AiToolEventResponse(name=tool_name, summary=f"已创建标签「{tag.name}」"), [], []

    if tool_name == "batch_assign_item_folders":
        if "manage_folders" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放文件夹管理权限"), [], []
        assignments = arguments.get("assignments") or []
        if not assignments:
            result = {"status": "error", "message": "assignments is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="批量归档失败：缺少 assignments"), [], []

        from routers.items import serialize_items, sync_item_folder_assignments

        success_count = 0
        errors: list[str] = []
        updated_items_list: list[dict[str, Any]] = []

        for assignment in assignments[:50]:
            item_id = _clean_optional_string(assignment.get("item_id"))
            folder_names = _coerce_text_list(assignment.get("folder_names"), limit=12)
            if not item_id or not folder_names:
                continue
            item = _get_user_item(db, user_id, item_id)
            if not item:
                errors.append(f"Item {item_id} not found")
                continue
            folders, missing = _resolve_tool_target_folders(db, user_id, [], folder_names)
            if missing:
                errors.append(f"Unknown folders for {item_id}: {', '.join(missing)}")
                continue
            sync_item_folder_assignments(item, folders)
            success_count += 1

        db.commit()

        # Refresh updated items
        for assignment in assignments[:50]:
            item_id = _clean_optional_string(assignment.get("item_id"))
            if item_id:
                item = _get_user_item(db, user_id, item_id)
                if item:
                    db.refresh(item)
                    updated_items_list.append(serialize_items([item])[0].model_dump(mode="json"))

        result = {
            "status": "ok",
            "success_count": success_count,
            "errors": errors[:20] if errors else [],
        }
        summary = f"已批量归档 {success_count} 条内容"
        if errors:
            summary += f"，{len(errors)} 条失败"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], updated_items_list

    if tool_name == "batch_assign_item_tags":
        if "manage_folders" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放标签管理权限"), [], []
        assignments = arguments.get("assignments") or []
        if not assignments:
            result = {"status": "error", "message": "assignments is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="批量打标签失败：缺少 assignments"), [], []

        from routers.items import serialize_items

        success_count = 0
        errors: list[str] = []
        updated_items_list: list[dict[str, Any]] = []

        for assignment in assignments[:50]:
            item_id = _clean_optional_string(assignment.get("item_id"))
            tag_names = _coerce_text_list(assignment.get("tag_names"), limit=20)
            if not item_id or not tag_names:
                continue
            item = _get_user_item(db, user_id, item_id)
            if not item:
                errors.append(f"Item {item_id} not found")
                continue
            tags, missing = _resolve_tool_target_tags(db, user_id, [], tag_names, create_missing=True)
            if missing:
                errors.append(f"Unknown tags for {item_id}: {', '.join(missing)}")
                continue
            db.query(ItemTagLink).filter(ItemTagLink.item_id == item.id).delete(synchronize_session=False)
            for tag in tags:
                db.add(ItemTagLink(item_id=item.id, tag_id=tag.id, source="ai"))
            success_count += 1

        db.commit()

        for assignment in assignments[:50]:
            item_id = _clean_optional_string(assignment.get("item_id"))
            if item_id:
                item = _get_user_item(db, user_id, item_id)
                if item:
                    db.refresh(item)
                    updated_items_list.append(serialize_items([item])[0].model_dump(mode="json"))

        result = {
            "status": "ok",
            "success_count": success_count,
            "errors": errors[:20] if errors else [],
        }
        summary = f"已批量更新 {success_count} 条内容的标签"
        if errors:
            summary += f"，{len(errors)} 条失败"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], updated_items_list

    if tool_name == "execute_sandbox_command":
        if "execute_commands" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放命令执行权限"), [], []

        from services.sandbox_executor import execute_sandbox_action, SandboxError

        action = _clean_optional_string(arguments.get("action")) or ""
        redirect_reason = _sandbox_command_requires_real_computer(action, arguments)
        if redirect_reason:
            if "run_computer_commands" in agent_permissions:
                message = (
                    f"{redirect_reason} 请改用 run_computer_command，"
                    "并把 working_directory 设为用户真正想要的目录；如果用户没指定目录，默认用主目录。"
                )
                result = {"status": "error", "message": message}
                return result, AiToolEventResponse(name=tool_name, status="failed", summary="本机安装/克隆任务不能走沙箱，请改用系统命令"), [], []
            message = (
                f"{redirect_reason} 当前没有开放系统命令权限。"
                "不要继续往 exports 沙箱下载或安装，请直接提示用户到设置里开启“允许系统命令（需逐条批准）”。"
            )
            result = {"status": "error", "message": message}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="缺少系统命令权限，不能在沙箱里替代执行"), [], []

        # Route git_clone and download_file through approval system
        _SANDBOX_APPROVAL_ACTIONS = {"git_clone", "download_file"}
        if action in _SANDBOX_APPROVAL_ACTIONS:
            url = _clean_optional_string(arguments.get("url")) or ""
            desc = f"沙盒{action}: {url}" if url else f"沙盒{action}"
            approval_command = f"[sandbox] {action}: {url}" if url else f"[sandbox] {action}"
            result = _create_pending_approval(
                command=approval_command,
                description=desc,
                working_directory="exports/",
                extra_fields={
                    "_sandbox_action": action,
                    "_sandbox_arguments": arguments,
                },
            )
            return result, AiToolEventResponse(
                name=tool_name,
                status="pending",
                summary=f"等待用户批准：{desc}",
                approval_id=result["approval_id"],
                approval_command=approval_command,
                approval_description=desc,
            ), [], []

        # Also check batch operations for git_clone/download_file
        if action == "batch":
            operations = arguments.get("operations") or []
            has_download_op = any(
                isinstance(op, dict) and op.get("action") in _SANDBOX_APPROVAL_ACTIONS
                for op in operations
            )
            if has_download_op:
                urls = [op.get("url", "") for op in operations if isinstance(op, dict) and op.get("action") in _SANDBOX_APPROVAL_ACTIONS]
                desc = f"沙盒批量下载: {', '.join(u for u in urls if u)}" if any(urls) else "沙盒批量下载操作"
                approval_command = "[sandbox] batch with download ops"
                result = _create_pending_approval(
                    command=approval_command,
                    description=desc,
                    working_directory="exports/",
                    extra_fields={
                        "_sandbox_action": action,
                        "_sandbox_arguments": arguments,
                    },
                )
                return result, AiToolEventResponse(
                    name=tool_name,
                    status="pending",
                    summary=f"等待用户批准：{desc}",
                    approval_id=result["approval_id"],
                    approval_command=f"[sandbox] batch download",
                    approval_description=desc,
                ), [], []

        try:
            result = await execute_sandbox_action(action, arguments)
            summary = f"已执行 {action}"
            if result.get("files_created"):
                summary += f"，创建了 {len(result['files_created'])} 个文件"
            download_url = result.get("download_url")
            return result, AiToolEventResponse(name=tool_name, summary=summary, download_url=download_url), [], []
        except SandboxError as exc:
            result = {"status": "error", "message": str(exc)}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"命令执行失败：{exc}"), [], []
        except Exception as exc:
            logger.exception("Sandbox execution error")
            result = {"status": "error", "message": str(exc)}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"命令执行异常：{exc}"), [], []

    if tool_name == "run_computer_command":
        if "run_computer_commands" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放系统命令权限"), [], []

        command = _clean_optional_string(arguments.get("command")) or ""
        description = _clean_optional_string(arguments.get("description")) or command
        working_directory = _clean_optional_string(arguments.get("working_directory")) or os.path.expanduser("~")

        if not command:
            result = {"status": "error", "message": "command is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="缺少命令"), [], []

        # Check for extremely dangerous patterns
        cmd_lower = command.lower()
        for banned in _COMPUTER_CMD_BANNED_PATTERNS:
            if banned.lower() in cmd_lower:
                result = {"status": "error", "message": f"Command contains banned pattern: {banned}"}
                return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"命令被禁止：{banned}"), [], []

        # Create pending approval — do NOT execute yet
        result = _create_pending_approval(
            command=command,
            description=description,
            working_directory=working_directory,
        )
        event = AiToolEventResponse(name=tool_name, status="pending", summary=f"等待用户批准：{_truncate_text(command, 60)}")
        return result, event, [], []

    if tool_name == "web_search":
        if "web_search" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放联网搜索权限"), [], []
        query = _clean_optional_string(arguments.get("query"))
        if not query:
            result = {"status": "error", "message": "query is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="搜索失败：缺少 query"), [], []
        max_results = max(1, min(int(arguments.get("max_results") or 5), 10))
        search_results = await _web_search_duckduckgo(query, max_results)
        if not search_results:
            result = {"status": "ok", "query": query, "results": [], "message": "未找到搜索结果"}
            return result, AiToolEventResponse(name=tool_name, summary=f"联网搜索「{_truncate_text(query, 30)}」：无结果"), [], []
        result = {
            "status": "ok",
            "query": query,
            "results": search_results,
        }
        summary = f"联网搜索「{_truncate_text(query, 30)}」：找到 {len(search_results)} 条结果"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], []

    result = {"status": "error", "message": f"Unknown tool: {tool_name}"}
    return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"未知工具：{tool_name}"), [], []


_PLAN_AND_EXECUTE_SYSTEM_PROMPT = (
    "你是一个工具调用规划器。分析用户请求，输出一个 JSON 数组，包含需要顺序执行的工具调用。\n"
    "每个元素格式：{\"name\": \"工具名\", \"arguments\": {...}}\n"
    "规则：\n"
    "1. 尽可能用最少的工具调用完成任务。优先使用高级工具（如 export_items_to_zip）而不是多次低级调用。\n"
    "2. 用户要求导出/打包/下载/整理内容时，直接用 export_items_to_zip，不要先搜索再导出。\n"
    "3. 用户要求执行多个命令时，用 execute_sandbox_command 的 batch action。\n"
    "4. 如果用户只是提问（不需要执行操作），返回空数组 []。\n"
    "5. 只输出 JSON 数组，不要解释。\n"
    "\n"
    "【关键：正确拆分 query / content_type / platform 参数】\n"
    "用户说的'视频'→ content_type='video'，不要放到 query 里。\n"
    "用户说的'文章'→ content_type='article'。\n"
    "用户说的'GitHub'→ platform='github'。\n"
    "用户说的'抖音'→ platform='douyin'。\n"
    "用户说的'小红书'→ platform='xiaohongshu'。\n"
    "用户说的'微信'→ platform='wechat'。\n"
    "query 只放主题关键词，不要混入内容类型或平台。\n"
    "\n"
    "【关键：output_filename 必须根据任务内容命名】\n"
    "不要用 export.md / export.zip 这种通用名，要根据用户请求的主题命名文件。\n"
    "命名规则：用简短中文或英文描述内容，用下划线连接，加上正确后缀。\n"
    "\n"
    "示例：\n"
    "用户：'整理所有量化视频的内容写成md'\n"
    "→ [{\"name\":\"export_items_to_zip\",\"arguments\":{\"query\":\"量化\",\"content_type\":\"video\",\"format\":\"merged_md\",\"output_filename\":\"量化视频内容汇总.md\"}}]\n"
    "\n"
    "用户：'下载所有GitHub的内容打包成zip'\n"
    "→ [{\"name\":\"export_items_to_zip\",\"arguments\":{\"platform\":\"github\",\"format\":\"zip_individual\",\"output_filename\":\"GitHub项目内容.zip\"}}]\n"
    "\n"
    "用户：'把所有股票相关的抖音视频导出'\n"
    "→ [{\"name\":\"export_items_to_zip\",\"arguments\":{\"query\":\"股票\",\"platform\":\"douyin\",\"format\":\"merged_md\",\"output_filename\":\"抖音股票视频合集.md\"}}]\n"
)


def _is_organize_request(user_message: str) -> bool:
    """Heuristic: does the user's message look like a library organization request?"""
    organize_keywords = [
        "整理", "归类", "分类", "自动分类", "按主题", "按领域",
        "分到文件夹", "建议文件夹", "检查标签", "重新分类",
        "打标签", "补标签", "标签整理", "标签分类",
        "organize", "categorize", "classify",
    ]
    lower = user_message.lower()
    return any(kw in lower for kw in organize_keywords)


def _is_action_request(user_message: str) -> bool:
    """Heuristic: does the user's last message look like an action/execution request?"""
    # Organization requests should go through agent loop (not plan-and-execute)
    if _is_organize_request(user_message):
        return False
    action_keywords = [
        "打包", "导出", "下载", "创建", "生成", "写成", "合并",
        "克隆", "clone", "zip", "export",
        "同步", "移到",
        "执行", "运行",
    ]
    lower = user_message.lower()
    return any(kw in lower for kw in action_keywords)


async def _run_agent_assistant(
    *,
    db: Session,
    user_id: str,
    ai_config: dict[str, str],
    settings: Settings | None,
    conversation: list[dict[str, str]],
    current_item: Item | None = None,
    current_item_note: KnowledgeBaseNote | None = None,
) -> AiAssistantResponse:
    agent_permissions = _agent_permissions(settings)
    tools = _build_agent_tools(agent_permissions)
    snapshot = _build_items_only_snapshot(db, user_id)
    memories = _load_ai_memories(db, user_id)
    current_page_notes = _get_item_page_notes(db, user_id, current_item.id) if current_item else []
    current_item_context = _build_current_item_context(current_item, current_item_note, current_page_notes) if current_item is not None else ""

    # Detect if user is requesting an action vs asking a question
    last_user_msg = ""
    for msg in reversed(conversation):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    use_plan_mode = (
        _is_action_request(last_user_msg)
        and "execute_commands" in agent_permissions
        and "run_computer_commands" not in agent_permissions
    )

    if use_plan_mode:
        return await _run_plan_and_execute(
            db=db,
            user_id=user_id,
            ai_config=ai_config,
            settings=settings,
            conversation=conversation,
            tools=tools,
            agent_permissions=agent_permissions,
            snapshot=snapshot,
            memories=memories,
            current_item=current_item,
            current_item_note=current_item_note,
            current_item_context=current_item_context,
        )

    return await _run_agent_loop(
        db=db,
        user_id=user_id,
        ai_config=ai_config,
        settings=settings,
        conversation=conversation,
        tools=tools,
        agent_permissions=agent_permissions,
        snapshot=snapshot,
        memories=memories,
        current_item=current_item,
        current_item_note=current_item_note,
        current_item_context=current_item_context,
    )


async def _run_plan_and_execute(
    *,
    db: Session,
    user_id: str,
    ai_config: dict[str, str],
    settings: Settings | None,
    conversation: list[dict[str, str]],
    tools: list[dict[str, Any]],
    agent_permissions: list[str],
    snapshot: KnowledgeBaseSnapshot,
    memories: list[AiMemory] | None = None,
    current_item: Item | None = None,
    current_item_note: KnowledgeBaseNote | None = None,
    current_item_context: str = "",
) -> AiAssistantResponse:
    """Plan-then-execute: 2 LLM calls instead of N.

    Phase 1: LLM analyzes request → outputs a JSON plan of tool calls
    Phase 2: Execute all planned tool calls
    Phase 3: LLM summarizes results with download links
    """
    tool_events: list[AiToolEventResponse] = []
    collected_notes: list[tuple[KnowledgeBaseNote, float]] = []
    if current_item_note is not None:
        collected_notes.append((current_item_note, 1.0))
    updated_items: list[dict[str, Any]] = []
    download_urls: list[str] = []

    # --- Phase 1: Planning ---
    tool_descriptions = "\n".join(
        f"- {t['function']['name']}: {t['function']['description']}"
        for t in tools
    )
    plan_system = _PLAN_AND_EXECUTE_SYSTEM_PROMPT + f"\n可用工具：\n{tool_descriptions}"
    if current_item_context:
        plan_system += (
            f"\n\n当前文章上下文（item_id 可直接使用）：\n{current_item_context}"
        )

    plan_messages: list[dict[str, Any]] = [
        {"role": "system", "content": plan_system},
        *conversation,
    ]

    try:
        plan_text = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=plan_messages,
            temperature=0.1,
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    # Parse plan
    planned_calls: list[dict[str, Any]] = []
    try:
        stripped = _JSON_FENCE_PATTERN.sub("", (plan_text or "").strip())
        start = stripped.find("[")
        end = stripped.rfind("]")
        if start != -1 and end > start:
            planned_calls = json.loads(stripped[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        pass

    # If no planned actions (question, not action), fall back to normal loop
    if not planned_calls:
        return await _run_agent_loop(
            db=db,
            user_id=user_id,
            ai_config=ai_config,
            settings=settings,
            conversation=conversation,
            tools=tools,
            agent_permissions=agent_permissions,
            snapshot=snapshot,
            memories=memories,
            current_item=current_item,
            current_item_note=current_item_note,
            current_item_context=current_item_context,
        )

    # --- Phase 2: Execute all planned tools ---
    execution_results: list[dict[str, Any]] = []
    for call in planned_calls:
        tool_name = _clean_optional_string(call.get("name")) or ""
        arguments = call.get("arguments") or {}

        result, event, ranked_notes, changed_items = await _execute_agent_tool(
            tool_name=tool_name,
            arguments=arguments,
            db=db,
            user_id=user_id,
            snapshot=snapshot,
            agent_permissions=agent_permissions,
            ai_config=ai_config,
        )
        tool_events.append(event)
        _append_unique_ranked_notes(collected_notes, ranked_notes)
        _append_unique_updated_items(updated_items, changed_items)
        if isinstance(result, dict) and ranked_notes:
            _annotate_result_with_citation_refs(result, ranked_notes, collected_notes)
        execution_results.append({"tool": tool_name, "result": result})

        if event.download_url:
            download_urls.append(event.download_url)

        # If a tool needs user approval, pause and return immediately
        if isinstance(result, dict) and result.get("status") == "pending_approval":
            return AiAssistantResponse(
                mode="agent",
                message=result.get("description", "需要你的批准才能执行此命令。"),
                citations=[],
                tool_events=tool_events,
                note_count=snapshot.note_count,
                insufficient_context=False,
                agent_permissions=agent_permissions,
                updated_items=updated_items,
                pending_approval=AiPendingApprovalResponse(
                    approval_id=result["approval_id"],
                    command=result["command"],
                    description=result["description"],
                    working_directory=result.get("working_directory"),
                ),
            )

    # --- Phase 3: Summarize with download links ---
    results_text = json.dumps(execution_results, ensure_ascii=False, default=str)
    download_hint = ""
    if download_urls:
        links = "\n".join(f"- [{url.split('/')[-1]}]({url})" for url in download_urls)
        download_hint = (
            f"\n\n以下文件已生成，请在回答末尾用 Markdown 链接格式提供下载链接，"
            f"格式必须为 📥 下载链接：[文件名](URL)，不要省略括号和URL：\n{links}"
        )

    agent_system = _compose_system_message(
        _assistant_agent_system_prompt(agent_permissions, memories=memories),
        (
            "下面是当前文章上下文。\n\n" + current_item_context
        ) if current_item_context else "",
    )
    summary_messages: list[dict[str, Any]] = [
        {"role": "system", "content": agent_system},
        *conversation,
        {
            "role": "system",
            "content": (
                f"以下是工具执行结果，请基于结果给用户简洁的回答。"
                f"不要重复粘贴完整内容，只需说明执行情况和提供下载链接。"
                f"引用内容时，必须使用结果中每条 item 的 ref 字段编号（如 [3] [7]），不要自己按顺序重新编号。"
                f"{download_hint}\n\n"
                f"执行结果：{results_text[:3000]}"
            ),
        },
    ]

    try:
        final_text = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=summary_messages,
            temperature=0.2,
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    return AiAssistantResponse(
        mode="agent",
        message=final_text.strip() or "已完成执行。",
        citations=_serialize_citations(
            db,
            user_id,
            _filter_ranked_notes_by_citation_markers(final_text, collected_notes),
        ),
        tool_events=tool_events,
        note_count=snapshot.note_count,
        insufficient_context=False,
        agent_permissions=agent_permissions,
        updated_items=updated_items,
    )


async def _run_agent_loop(
    *,
    db: Session,
    user_id: str,
    ai_config: dict[str, str],
    settings: Settings | None,
    conversation: list[dict[str, str]],
    tools: list[dict[str, Any]],
    agent_permissions: list[str],
    snapshot: KnowledgeBaseSnapshot,
    memories: list[AiMemory] | None = None,
    current_item: Item | None = None,
    current_item_note: KnowledgeBaseNote | None = None,
    current_item_context: str = "",
) -> AiAssistantResponse:
    """Original agent loop — used for questions and complex multi-step tasks."""
    system_message = _compose_system_message(
        _assistant_agent_system_prompt(agent_permissions, memories=memories),
        (
            "下面是当前文章上下文。若用户提到当前文章、这篇内容、这条笔记等指代，优先以这里为准；"
            "如果需要调用工具操作当前文章，请直接使用这里给出的 item_id。\n\n"
            f"{current_item_context}"
        ) if current_item_context else "",
    )
    model_messages: list[dict[str, Any]] = [{"role": "system", "content": system_message}, *conversation]
    tool_events: list[AiToolEventResponse] = []
    collected_notes: list[tuple[KnowledgeBaseNote, float]] = []
    if current_item_note is not None:
        collected_notes.append((current_item_note, 1.0))
    updated_items: list[dict[str, Any]] = []
    _tool_call_counts: dict[str, int] = {}  # 每个工具的调用计数
    _WEB_SEARCH_MAX_CALLS = 3  # web_search 最多调用次数

    last_tool_signature: str | None = None
    repeated_tool_call_count = 0
    force_finalize_reason: str | None = None

    while True:
        try:
            payload = await create_chat_completion(
                api_key=ai_config["api_key"],
                base_url=ai_config["base_url"],
                model=ai_config["model"],
                messages=model_messages,
                temperature=0.2,
                tools=tools,
                tool_choice="auto",
            )
        except AiClientError as exc:
            raise _ai_request_failed(exc) from exc

        assistant_message = extract_assistant_message(payload)
        tool_calls = extract_tool_calls(assistant_message)
        assistant_text = extract_message_text(assistant_message, allow_empty=True)

        if not tool_calls:
            final_message = assistant_text.strip() or "我已完成当前可执行步骤，但没有生成额外说明。"
            return AiAssistantResponse(
                mode="agent",
                message=final_message,
                citations=_serialize_citations(
                    db,
                    user_id,
                    _filter_ranked_notes_by_citation_markers(final_message, collected_notes),
                ),
                tool_events=tool_events,
                note_count=snapshot.note_count,
                insufficient_context=False,
                agent_permissions=agent_permissions,
                updated_items=updated_items,
            )

        model_messages.append(
            {
                "role": "assistant",
                "content": assistant_message.get("content"),
                "tool_calls": tool_calls,
            }
        )

        for tool_call in tool_calls:
            tool_id = _clean_optional_string(tool_call.get("id")) or "tool-call"
            function_payload = tool_call.get("function") or {}
            tool_name = _clean_optional_string(function_payload.get("name")) or "unknown_tool"
            raw_arguments = function_payload.get("arguments") or "{}"

            # 限制 web_search 调用次数，防止死循环
            _tool_call_counts[tool_name] = _tool_call_counts.get(tool_name, 0) + 1
            if tool_name == "web_search" and _tool_call_counts[tool_name] > _WEB_SEARCH_MAX_CALLS:
                result = {
                    "status": "error",
                    "message": "已达到联网搜索次数上限，请基于已有搜索结果回答。",
                }
                event = AiToolEventResponse(name=tool_name, status="failed", summary="联网搜索次数已达上限")
                ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
                changed_items: list[dict[str, Any]] = []
                tool_events.append(event)
                model_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "name": tool_name,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                continue

            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else {}
            except json.JSONDecodeError:
                arguments = {}
                result = {"status": "error", "message": "Invalid JSON arguments"}
                event = AiToolEventResponse(name=tool_name, status="failed", summary=f"{tool_name} 参数解析失败")
                ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
                changed_items: list[dict[str, Any]] = []
            else:
                tool_signature = _tool_call_signature(tool_name, arguments)
                if tool_signature == last_tool_signature:
                    repeated_tool_call_count += 1
                else:
                    last_tool_signature = tool_signature
                    repeated_tool_call_count = 1

                if repeated_tool_call_count > _AGENT_TOOL_REPEAT_LIMIT:
                    result = {
                        "status": "error",
                        "message": (
                            "检测到 agent 连续重复调用同一个工具且参数完全相同。"
                            "为避免死循环，停止继续执行重复操作，请基于已有结果给出下一步结论。"
                        ),
                    }
                    event = AiToolEventResponse(
                        name=tool_name,
                        status="failed",
                        summary="检测到重复工具调用，已停止继续重复执行",
                    )
                    ranked_notes = []
                    changed_items = []
                    force_finalize_reason = "检测到重复工具调用死循环"
                else:
                    result, event, ranked_notes, changed_items = await _execute_agent_tool(
                        tool_name=tool_name,
                        arguments=arguments,
                        db=db,
                        user_id=user_id,
                        snapshot=snapshot,
                        agent_permissions=agent_permissions,
                        ai_config=ai_config,
                    )
            tool_events.append(event)
            _append_unique_ranked_notes(collected_notes, ranked_notes)
            _append_unique_updated_items(updated_items, changed_items)
            if isinstance(result, dict) and ranked_notes:
                _annotate_result_with_citation_refs(result, ranked_notes, collected_notes)
            model_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": tool_name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

            # If a tool needs user approval, pause the loop and return
            if isinstance(result, dict) and result.get("status") == "pending_approval":
                return AiAssistantResponse(
                    mode="agent",
                    message=result.get("description", "需要你的批准才能执行此命令。"),
                    citations=[],
                    tool_events=tool_events,
                    note_count=snapshot.note_count,
                    insufficient_context=False,
                    agent_permissions=agent_permissions,
                    updated_items=updated_items,
                    pending_approval=AiPendingApprovalResponse(
                        approval_id=result["approval_id"],
                        command=result["command"],
                        description=result["description"],
                        working_directory=result.get("working_directory"),
                    ),
                )

            if force_finalize_reason:
                break

        if force_finalize_reason:
            break

    model_messages.append(
        {
            "role": "system",
            "content": (
                f"{force_finalize_reason}。"
                "停止继续调用工具。现在基于已有工具结果，给出最终简洁回答。"
            ) if force_finalize_reason else "停止继续调用工具。现在基于已有工具结果，给出最终简洁回答。",
        }
    )
    try:
        final_text = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=model_messages,
            temperature=0.2,
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    return AiAssistantResponse(
        mode="agent",
        message=final_text.strip() or "我已完成当前可执行步骤。",
        citations=_serialize_citations(
            db,
            user_id,
            _filter_ranked_notes_by_citation_markers(final_text, collected_notes),
        ),
        tool_events=tool_events,
        note_count=snapshot.note_count,
        insufficient_context=False,
        agent_permissions=agent_permissions,
        updated_items=updated_items,
    )


@router.get("/memories")
def list_ai_memories_for_frontend(db: Session = Depends(get_db)):
    """Return AI memories for frontend query expansion (search bar, graph search)."""
    user_id = get_current_user_id()
    memories = _load_ai_memories(db, user_id)
    return [{"id": m.id, "type": m.type, "content": m.content} for m in memories]


@router.get("/conversations", response_model=AiConversationListResponse)
def list_ai_conversations(
    q: str | None = None,
    current_item_id: str | None = None,
    limit: int = 40,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    query = db.query(AiConversation).filter(AiConversation.user_id == user_id)

    normalized_item_id = _clean_optional_string(current_item_id)
    if normalized_item_id:
        query = query.filter(AiConversation.current_item_id == normalized_item_id)

    normalized_query = _clean_optional_string(q)
    if normalized_query:
        like_query = f"%{normalized_query.lower()}%"
        query = query.filter(
            or_(
                func.lower(func.coalesce(AiConversation.title, "")).like(like_query),
                func.lower(func.coalesce(AiConversation.search_text, "")).like(like_query),
            )
        )

    safe_limit = max(1, min(int(limit or 40), 100))
    conversations = (
        query.order_by(
            func.coalesce(AiConversation.last_message_at, AiConversation.updated_at, AiConversation.created_at).desc(),
            AiConversation.updated_at.desc(),
        )
        .limit(safe_limit)
        .all()
    )
    return AiConversationListResponse(
        conversations=[_serialize_ai_conversation_summary(conversation) for conversation in conversations]
    )


@router.get("/conversations/{conversation_id}", response_model=AiConversationResponse)
def get_ai_conversation(conversation_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    conversation = (
        db.query(AiConversation)
        .filter(AiConversation.id == conversation_id, AiConversation.user_id == user_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _serialize_ai_conversation(conversation)


@router.post("/conversations", response_model=AiConversationResponse)
def save_ai_conversation(request: AiConversationSaveRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    current_item_id = _clean_optional_string(request.current_item_id)
    current_item = _get_user_item(db, user_id, current_item_id) if current_item_id else None
    if current_item_id and current_item is None:
        raise HTTPException(status_code=404, detail="Current item not found")

    messages = _sanitize_saved_conversation_messages(request.messages)
    if not messages:
        raise HTTPException(status_code=400, detail="messages are required")

    conversation_id = _clean_optional_string(request.conversation_id)
    if conversation_id:
        conversation = (
            db.query(AiConversation)
            .filter(AiConversation.id == conversation_id, AiConversation.user_id == user_id)
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = AiConversation(user_id=user_id)
        db.add(conversation)

    now = datetime.utcnow()
    conversation.current_item_id = current_item.id if current_item is not None else None
    if current_item is not None:
        conversation.workspace_id = current_item.workspace_id
    conversation.mode = "agent" if _clean_optional_string(request.mode) == "agent" else "chat"
    conversation.title = _derive_conversation_title(
        messages,
        explicit_title=request.title,
        current_item=current_item,
    )
    conversation.messages_json = json.dumps(messages, ensure_ascii=False)
    conversation.search_text = _build_conversation_search_text(
        conversation.title,
        current_item=current_item,
        messages=messages,
    )
    if conversation.created_at is None:
        conversation.created_at = now
    conversation.updated_at = now
    conversation.last_message_at = now

    db.commit()
    db.refresh(conversation)
    return _serialize_ai_conversation(conversation)


@router.delete("/conversations/{conversation_id}")
def delete_ai_conversation(conversation_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    conversation = (
        db.query(AiConversation)
        .filter(AiConversation.id == conversation_id, AiConversation.user_id == user_id)
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.delete(conversation)
    db.commit()
    return {"ok": True}


@router.post("/ask", response_model=AiAskResponse)
async def ask_ai(request: AiAskRequest, db: Session = Depends(get_db)):
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    ai_config = _resolve_ai_config(settings)
    rag_context = await _retrieve_rag_context(
        db=db,
        user_id=user_id,
        ai_config=ai_config,
        question=question,
        top_k=max(1, min(request.top_k, 8)),
    )

    if rag_context.note_count <= 0:
        return AiAskResponse(
            question=question,
            answer="收藏库里没有找到任何内容。",
            citations=[],
            note_count=0,
            insufficient_context=True,
        )
    if rag_context.insufficient_context or not rag_context.context_text:
        return AiAskResponse(
            question=question,
            answer="收藏库里没有找到足够相关的内容来可靠回答这个问题。",
            citations=[],
            note_count=rag_context.note_count,
            insufficient_context=True,
        )

    items_directory, directory_notes = _build_chat_items_directory(db, user_id)
    user_content_parts = [f"用户问题：{question}\n"]
    if items_directory:
        user_content_parts.append(
            "下面是用户收藏库的完整目录，供你了解全貌。"
            "当用户问概览性问题时以此为准。这里不是引用编号列表，不要把目录顺序写成 [11] 这类引用。\n\n"
            f"{items_directory}\n"
        )
    user_content_parts.append(
        "下面是从用户收藏库中检索出的相关内容（含详细正文）。"
        "回答具体问题时请基于这些详细内容，引用时使用 [编号] 格式。若信息不够，请直接说明缺口。\n\n"
        f"{rag_context.context_text}"
    )
    try:
        answer = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=[
                {"role": "system", "content": _ask_ai_system_prompt()},
                {
                    "role": "user",
                    "content": "\n".join(user_content_parts),
                },
            ],
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    answer, citation_matches = _annotate_answer_with_citations(answer, rag_context.ranked_notes, directory_notes)
    return AiAskResponse(
        question=question,
        answer=answer.strip(),
        citations=_serialize_citation_matches(
            db,
            user_id,
            citation_matches,
        ),
        note_count=rag_context.note_count,
        insufficient_context=False,
    )


@router.post("/assistant", response_model=AiAssistantResponse)
async def assistant(request: AiAssistantRequest, db: Session = Depends(get_db)):
    conversation = _sanitize_conversation_messages(request.messages)
    if not conversation:
        raise HTTPException(status_code=400, detail="messages are required")

    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    ai_config = _resolve_ai_config(settings)
    mode = "agent" if (request.mode or "").strip().lower() == "agent" else "chat"
    current_item_id = _clean_optional_string(request.current_item_id)
    current_item = _get_user_item(db, user_id, current_item_id) if current_item_id else None
    current_item_note = None
    current_page_notes: list[ItemPageNote] = []
    if current_item:
        current_item_note = _build_seed_note_from_item(current_item)
        current_page_notes = _get_item_page_notes(db, user_id, current_item.id)

    if mode == "agent":
        return await _run_agent_assistant(
            db=db,
            user_id=user_id,
            ai_config=ai_config,
            settings=settings,
            conversation=conversation,
            current_item=current_item,
            current_item_note=current_item_note,
        )

    retrieval_query = _build_retrieval_query_from_conversation(conversation) or conversation[-1]["content"]
    rag_context = await _retrieve_rag_context(
        db=db,
        user_id=user_id,
        ai_config=ai_config,
        question=retrieval_query,
        top_k=max(1, min(request.top_k, 8)),
    )

    current_item_context = _build_current_item_context(current_item, current_item_note, current_page_notes) if current_item is not None else ""
    items_directory, directory_notes = _build_chat_items_directory(db, user_id)
    system_message = _compose_system_message(
        _assistant_chat_system_prompt(),
        (
            "下面是当前文章上下文（包括正文内容和用户笔记）。回答时请结合正文内容和用户笔记综合分析。\n\n"
            f"{current_item_context}"
        ) if current_item_context else "",
        (
            "下面是用户收藏库的完整目录，供你了解全貌。"
            "当用户问'最近保存了什么''列出我的内容'等概览性问题时，以此为准。这里不是引用编号列表，不要把目录顺序写成 [11] 这类引用。\n\n"
            f"{items_directory}"
        ) if items_directory else "",
        (
            "下面是从用户收藏库中检索出的相关内容（含详细正文）。"
            "回答具体问题时请基于这些详细内容，引用时使用 [编号] 格式。\n\n"
            f"{rag_context.context_text}"
        ) if rag_context.context_text else "",
    )
    model_messages: list[dict[str, Any]] = [{"role": "system", "content": system_message}, *conversation]
    try:
        answer = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=model_messages,
            temperature=0.2,
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    answer, citation_matches = _annotate_answer_with_citations(answer, rag_context.ranked_notes, directory_notes)
    return AiAssistantResponse(
        mode="chat",
        message=answer.strip(),
        citations=_serialize_citation_matches(
            db,
            user_id,
            citation_matches,
        ),
        tool_events=[],
        note_count=rag_context.note_count,
        insufficient_context=rag_context.insufficient_context,
        agent_permissions=_agent_permissions(settings),
        updated_items=[],
    )


@router.post("/assistant/approve", response_model=AiApprovalResponse)
async def approve_computer_command(request: AiApprovalRequest):
    """Execute or deny a pending computer command that required user approval."""
    approval = _pending_approvals.pop(request.approval_id, None)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found or expired")

    if not request.approved:
        return AiApprovalResponse(status="denied", output="用户拒绝了此命令。", exit_code=-1)

    # Handle sandbox command approvals (git_clone, download_file)
    if "_sandbox_action" in approval:
        from services.sandbox_executor import execute_sandbox_action, SandboxError
        sandbox_action = approval["_sandbox_action"]
        sandbox_arguments = approval["_sandbox_arguments"]
        try:
            result = await execute_sandbox_action(sandbox_action, sandbox_arguments)
            output_parts = [f"操作完成: {sandbox_action}"]
            if result.get("files_created"):
                output_parts.append(f"创建了 {len(result['files_created'])} 个文件")
            if result.get("output"):
                output_parts.append(str(result["output"])[:_COMPUTER_CMD_MAX_OUTPUT])
            return AiApprovalResponse(
                status="completed",
                output="\n".join(output_parts),
                exit_code=0,
            )
        except (SandboxError, Exception) as exc:
            return AiApprovalResponse(
                status="error",
                output=f"沙盒执行失败: {exc}",
                exit_code=-1,
            )

    command = approval["command"]
    working_directory = approval.get("working_directory") or os.path.expanduser("~")

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=working_directory,
            env={**os.environ},
        )
        stdout_bytes, _ = await asyncio.wait_for(
            proc.communicate(),
            timeout=_COMPUTER_CMD_TIMEOUT,
        )
        output = (stdout_bytes or b"").decode("utf-8", errors="replace")
        if len(output) > _COMPUTER_CMD_MAX_OUTPUT:
            output = output[:_COMPUTER_CMD_MAX_OUTPUT] + "\n... (output truncated)"
        return AiApprovalResponse(
            status="completed",
            output=output,
            exit_code=proc.returncode or 0,
        )
    except asyncio.TimeoutError:
        return AiApprovalResponse(
            status="error",
            output=f"命令执行超时（{_COMPUTER_CMD_TIMEOUT}s）",
            exit_code=-1,
        )
    except Exception as exc:
        return AiApprovalResponse(
            status="error",
            output=str(exc),
            exit_code=-1,
        )


@router.post("/assistant/stream")
async def assistant_stream(request: AiAssistantRequest, db: Session = Depends(get_db)):
    """Streaming version of /assistant for chat mode. Sends SSE events."""
    conversation = _sanitize_conversation_messages(request.messages)
    if not conversation:
        raise HTTPException(status_code=400, detail="messages are required")

    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    ai_config = _resolve_ai_config(settings)
    current_item_id = _clean_optional_string(request.current_item_id)
    current_item = _get_user_item(db, user_id, current_item_id) if current_item_id else None
    current_item_note = None
    current_page_notes: list[ItemPageNote] = []
    if current_item:
        current_item_note = _build_seed_note_from_item(current_item)
        current_page_notes = _get_item_page_notes(db, user_id, current_item.id)

    async def event_stream():
        def _sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"

        retrieval_query = _build_retrieval_query_from_conversation(conversation) or conversation[-1]["content"]
        rag_context = await _retrieve_rag_context(
            db=db,
            user_id=user_id,
            ai_config=ai_config,
            question=retrieval_query,
            top_k=max(1, min(request.top_k, 8)),
        )

        yield _sse({
            "type": "status",
            "status": "found",
            "message": f"已完成检索，已命中 {len(rag_context.ranked_notes)} 条相关收藏内容，正在生成回答",
        })

        if rag_context.note_count <= 0:
            yield _sse({
                "type": "done",
                "message": "收藏库里没有任何内容。",
                "citations": [],
                "insufficient_context": True,
            })
            return

        # Build context and stream the answer
        current_item_context = _build_current_item_context(current_item, current_item_note, current_page_notes) if current_item is not None else ""
        items_directory, directory_notes = _build_chat_items_directory(db, user_id)
        system_message = _compose_system_message(
            _assistant_chat_system_prompt(),
            (
                "下面是当前文章上下文（包括正文内容和用户笔记）。回答时请结合正文内容和用户笔记综合分析。\n\n"
                f"{current_item_context}"
            ) if current_item_context else "",
            (
                "下面是用户收藏库的完整目录，供你了解全貌。"
                "当用户问'最近保存了什么''列出我的内容'等概览性问题时，以此为准。这里不是引用编号列表，不要把目录顺序写成 [11] 这类引用。\n\n"
                f"{items_directory}"
            ) if items_directory else "",
            (
                "下面是从用户收藏库中检索出的相关内容（含详细正文）。"
                "回答具体问题时请基于这些详细内容，引用时使用 [编号] 格式。\n\n"
                f"{rag_context.context_text}"
            ) if rag_context.context_text else "",
        )
        model_messages: list[dict[str, Any]] = [{"role": "system", "content": system_message}, *conversation]

        full_answer = ""
        try:
            async for delta in stream_chat_completion(
                api_key=ai_config["api_key"],
                base_url=ai_config["base_url"],
                model=ai_config["model"],
                messages=model_messages,
                temperature=0.2,
            ):
                full_answer += delta
                yield _sse({"type": "delta", "content": delta})
        except AiClientError as exc:
            yield _sse({"type": "error", "message": str(exc)})
            return

        # Final event with citations — build directly from indexed_notes
        # without DB query (all notes come from items, so item_id is valid)
        answer, citation_matches = _annotate_answer_with_citations(full_answer.strip(), rag_context.ranked_notes, directory_notes)
        citations = _serialize_citation_matches(db, user_id, citation_matches)
        yield _sse({
            "type": "done",
            "message": answer,
            "citations": [c.model_dump() if hasattr(c, 'model_dump') else c.dict() for c in citations],
            "insufficient_context": rag_context.insufficient_context,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/items/{item_id}/related", response_model=AiRelatedNotesResponse)
def related_notes(item_id: str, limit: int = 5, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = _get_user_item(db, user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    snapshot = _build_items_only_snapshot(db, user_id)
    seed_note = _build_seed_note_from_item(item)
    ranked_related = rank_related_notes(snapshot, seed_note, limit=max(1, min(limit, 8))) if snapshot.note_count else []

    return AiRelatedNotesResponse(
        item_id=item.id,
        related=_serialize_citations(db, user_id, ranked_related),
        note_count=snapshot.note_count,
    )


_ORGANIZER_CHUNK_CHAR_LIMIT = 12000
_ORGANIZER_MERGE_PROMPT = (
    "下面是同一篇文章分段整理后的结果，请合并成一份连贯的内容分析文本。"
    "保留所有信息和结构标记（[detected_title]、[body] 等），去除重复部分。"
    "输出纯文本，不要解释。"
)


def _split_analysis_chunks(text: str, limit: int = _ORGANIZER_CHUNK_CHAR_LIMIT) -> list[str]:
    """Split long analysis text into chunks at paragraph boundaries."""
    if len(text) <= limit:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for \n\n
        if current and current_len + para_len > limit:
            chunks.append("\n\n".join(current))
            current = [para]
            current_len = para_len
        else:
            current.append(para)
            current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


async def _organize_single_chunk(
    ai_config: dict[str, str],
    system_prompt: str,
    chunk_context: str,
    timeout: float,
) -> str:
    return await chat_completion(
        api_key=ai_config["api_key"],
        base_url=ai_config["base_url"],
        model=ai_config["model"],
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "请直接整理下面这条「内容分析」文本。目标是尽量保留原有信息和表述，"
                    "只做结构化、分段、去重和 Markdown 排版；不要总结、不要压缩成提要。"
                    "请输出最终可保存的内容分析文本。\n\n"
                    f"{chunk_context}"
                ),
            },
        ],
        temperature=0.2,
        timeout_seconds=timeout,
    )


@router.post("/items/{item_id}/organize-analysis", response_model=ItemResponse)
async def organize_item_analysis(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = _get_user_item(db, user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    if (item.parse_status or "").strip().lower() == "processing":
        raise HTTPException(status_code=409, detail="Item content is still processing")

    settings = _get_user_settings(db, user_id)
    ai_config = _resolve_ai_config(settings)

    if not _clean_optional_string(item.extracted_text):
        raise HTTPException(status_code=400, detail="No current item analysis available for organization")

    analysis_text = _normalize_multiline_text(item.extracted_text)
    # For video items, strip cover-image OCR — it's just the thumbnail, not real content
    has_video = any(m.type == "video" for m in (item.media or []))
    if has_video:
        analysis_text = re.sub(r"\[ocr_text\]\n.*?(?=\n\[|\Z)", "", analysis_text, flags=re.DOTALL).strip()
    item_header = (
        f"当前文章 item_id：{item.id}\n"
        f"当前文章标题：{_clean_optional_string(item.title) or f'Item {item.id}'}\n\n"
        "当前文章已有的内容分析文本：\n"
    )
    system_prompt = _analysis_organizer_system_prompt()

    chunks = _split_analysis_chunks(analysis_text)

    try:
        if len(chunks) == 1:
            # Short text: single pass
            context = item_header + _truncate_text(analysis_text, 20000)
            timeout = min(300.0, 90.0 + (len(context) / 5000) * 30.0)
            response_text = await _organize_single_chunk(ai_config, system_prompt, context, timeout)
        else:
            # Long text: organize each chunk, then merge
            chunk_results: list[str] = []
            for i, chunk in enumerate(chunks):
                chunk_label = f"（第{i + 1}/{len(chunks)}段）\n" if len(chunks) > 1 else ""
                context = item_header + chunk_label + chunk
                timeout = min(300.0, 90.0 + (len(context) / 5000) * 30.0)
                result = await _organize_single_chunk(ai_config, system_prompt, context, timeout)
                chunk_results.append(_strip_reasoning_blocks(result).strip())

            if len(chunk_results) == 1:
                response_text = chunk_results[0]
            else:
                # Merge all chunk results
                merged_input = "\n\n---\n\n".join(chunk_results)
                merge_timeout = min(300.0, 90.0 + (len(merged_input) / 5000) * 30.0)
                response_text = await chat_completion(
                    api_key=ai_config["api_key"],
                    base_url=ai_config["base_url"],
                    model=ai_config["model"],
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": f"{_ORGANIZER_MERGE_PROMPT}\n\n{merged_input}",
                        },
                    ],
                    temperature=0.2,
                    timeout_seconds=merge_timeout,
                )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    organized_text = _normalize_organized_analysis_text(
        response_text,
        fallback_title=_clean_optional_string(item.title) or f"Item {item.id}",
    )
    if not organized_text:
        raise HTTPException(status_code=502, detail="AI returned empty organized analysis")

    # For video items, ensure the organized result doesn't contain cover-image OCR
    if has_video:
        organized_text = re.sub(r"\[ocr_text\]\n.*?(?=\n\[|\Z)", "", organized_text, flags=re.DOTALL).strip()
        item.ocr_text = None

    item.extracted_text = organized_text
    item.parse_status = "completed"
    item.parse_error = None
    if item.parsed_at is None:
        item.parsed_at = datetime.utcnow()

    db.commit()
    db.refresh(item)

    from routers.items import serialize_items

    return serialize_items([item])[0]


@router.post("/items/{item_id}/analysis", response_model=AiItemAnalysisResponse)
async def analyze_item(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = _get_user_item(db, user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    settings = _get_user_settings(db, user_id)
    ai_config = _resolve_ai_config(settings)

    snapshot = _build_items_only_snapshot(db, user_id)
    seed_note = _build_seed_note_from_item(item)
    ranked_related = rank_related_notes(snapshot, seed_note, limit=4) if snapshot.note_count else []

    related_context = "\n\n".join(
        _build_note_context_lines(note, index + 1)
        for index, (note, _) in enumerate(ranked_related)
    ) or "无"
    current_note_context = _build_note_context_lines(seed_note, 0)

    page_notes = _get_item_page_notes(db, user_id, item.id)
    page_notes_context = ""
    if page_notes:
        parts = []
        for pn in page_notes:
            title = _clean_optional_string(pn.title) or "无标题"
            content = _clean_optional_string(pn.content) or ""
            if content:
                parts.append(f"【{title}】\n{content}")
            else:
                parts.append(f"【{title}】")
        page_notes_context = "\n\n用户在这篇文章上的笔记：\n" + _truncate_text("\n\n".join(parts), 4000)

    try:
        response_text = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=[
                {"role": "system", "content": _analysis_system_prompt()},
                {
                    "role": "user",
                    "content": (
                        "请结合正文内容和用户笔记综合分析当前这条笔记。回答必须是 JSON，对象字段如下：\n"
                        "{\n"
                        '  "one_liner": "一句话总结",\n'
                        '  "core_points": ["核心观点1", "核心观点2"],\n'
                        '  "why_saved": "为什么值得保存",\n'
                        '  "themes": ["主题1", "主题2"],\n'
                        '  "thinking_questions": ["问题1", "问题2"]\n'
                        "}\n\n"
                        "当前笔记：\n"
                        f"{current_note_context}{page_notes_context}\n\n"
                        "相关笔记：\n"
                        f"{related_context}"
                    ),
                },
            ],
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    try:
        payload = _extract_json_object(response_text)
    except (ValueError, json.JSONDecodeError):
        payload = {
            "one_liner": _truncate_text(response_text, 220) or (seed_note.summary or seed_note.title),
            "core_points": [],
            "why_saved": seed_note.summary or seed_note.excerpt or "当前返回内容未能解析成结构化 JSON。",
            "themes": [],
            "thinking_questions": [],
        }

    citations = [(seed_note, 1.0), *ranked_related]
    deduped_citations: list[tuple[KnowledgeBaseNote, float]] = []
    _append_unique_ranked_notes(deduped_citations, citations)

    return AiItemAnalysisResponse(
        item_id=item.id,
        note_title=seed_note.title,
        summary_used=seed_note.summary or None,
        one_liner=_clean_optional_string(payload.get("one_liner")) or seed_note.title,
        core_points=_coerce_text_list(payload.get("core_points")),
        why_saved=_clean_optional_string(payload.get("why_saved")) or (seed_note.summary or seed_note.excerpt or "信息不足"),
        themes=_coerce_text_list(payload.get("themes")),
        thinking_questions=_coerce_text_list(payload.get("thinking_questions")),
        citations=_serialize_citations(db, user_id, deduped_citations),
    )


# ---------------------------------------------------------------------------
# Exports download endpoint
# ---------------------------------------------------------------------------

@router.get("/exports/{file_path:path}")
def download_export(file_path: str):
    from fastapi.responses import FileResponse
    from paths import EXPORTS_DIR

    full_path = (EXPORTS_DIR / file_path).resolve()
    if not str(full_path).startswith(str(EXPORTS_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(full_path, filename=full_path.name)
