from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Folder, Item, Settings
from schemas import (
    AiAskRequest,
    AiAskResponse,
    AiAssistantRequest,
    AiAssistantResponse,
    AiCitationResponse,
    AiItemAnalysisResponse,
    AiRelatedNotesResponse,
    AiToolEventResponse,
    ItemResponse,
)
from security import decrypt_secret
from services.ai_client import (
    AiClientError,
    chat_completion,
    create_chat_completion,
    extract_assistant_message,
    extract_message_text,
    extract_tool_calls,
)
from services.ai_defaults import (
    AI_AGENT_DEFAULT_CAN_MANAGE_FOLDERS,
    AI_AGENT_DEFAULT_CAN_PARSE_CONTENT,
    AI_AGENT_DEFAULT_CAN_SYNC_NOTION,
    AI_AGENT_DEFAULT_CAN_SYNC_OBSIDIAN,
    AI_DEFAULT_BASE_URL,
    AI_DEFAULT_MODEL,
    coerce_bool,
)
from services.knowledge_base import (
    KnowledgeBaseNote,
    KnowledgeBaseSnapshot,
    detect_knowledge_base_path,
    load_knowledge_base_snapshot,
    prepare_note_for_similarity,
    rank_notes_for_query,
    rank_related_notes,
)
from tenant import get_current_user_id

router = APIRouter(prefix="/api/ai", tags=["ai"])

_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")
_CHAT_HISTORY_LIMIT = 10
_AGENT_TOOL_STEP_LIMIT = 6


def _clean_optional_string(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _get_user_settings(db: Session, user_id: str) -> Settings | None:
    return db.query(Settings).filter(Settings.user_id == user_id).first()


def _get_user_item(db: Session, user_id: str, item_id: str) -> Item | None:
    return db.query(Item).filter(Item.user_id == user_id, Item.id == item_id).first()


def _get_setting_secret(settings: Settings | None, field_name: str) -> str | None:
    if not settings:
        return None
    try:
        return _clean_optional_string(decrypt_secret(getattr(settings, field_name, None)))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=f"Stored secret {field_name} is unreadable") from exc


def _resolve_ai_config(settings: Settings | None) -> dict[str, str]:
    api_key = _get_setting_secret(settings, "ai_api_key")
    base_url = _clean_optional_string(settings.ai_base_url if settings else None) or AI_DEFAULT_BASE_URL
    model = _clean_optional_string(settings.ai_model if settings else None) or AI_DEFAULT_MODEL
    if not api_key:
        raise HTTPException(status_code=400, detail="AI settings are incomplete: ai_api_key")
    return {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
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


def _build_current_item_context(item: Item, note: KnowledgeBaseNote | None = None) -> str:
    folder_names = _extract_item_folder_names(item)
    analysis_text = _normalize_multiline_text(item.extracted_text)
    canonical_text = _normalize_multiline_text(item.canonical_text)
    ocr_text = _normalize_multiline_text(item.ocr_text)
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
            "这篇内容在知识库里的已有摘要：",
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
        _truncate_text(analysis_text, 8000),
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
        "你是一个读过用户个人知识库的研究助理。"
        "只能基于提供的笔记回答，不要引入外部常识来补空。"
        "优先使用每篇笔记已有的 `summary` / `摘要`，不要重复整理同一份知识。"
        "如果证据不足，必须明确说信息不足。"
        "回答时尽量使用 [1] [2] 这样的引用编号。"
    )


def _analysis_system_prompt() -> str:
    return (
        "你是一个读过用户知识库的研究助理。"
        "当前任务是分析一条笔记，不要机械复述现有摘要。"
        "要以现有摘要为锚点，补充更高层次的理解、归类、关联和思考方向。"
        "只基于提供的内容做判断，不要编造。"
        "返回严格 JSON。"
    )


def _assistant_chat_system_prompt() -> str:
    return (
        "你是用户网站里的 AI chatbot。"
        "你的职责是和用户的个人知识库以及当前打开的文章对话，而不是泛泛聊天。"
        "如果提供了当前文章上下文，优先依据当前文章的内容分析、抓取文本和 OCR / 帧文字回答。"
        "如果同时提供了知识库笔记，优先使用已有 `summary` / `摘要` 作为辅助，不要机械重复整理。"
        "只能基于提供的上下文回答；若上下文不足，必须明确说明。"
        "回答请使用中文，保持简洁，并尽量用 [1] [2] 引用编号。"
    )


def _assistant_agent_system_prompt(agent_permissions: list[str], snapshot: KnowledgeBaseSnapshot) -> str:
    permission_lines = {
        "read_knowledge_base": "读取与检索知识库",
        "manage_folders": "调整笔记文件夹归属",
        "parse_content": "触发笔记内容解析",
        "sync_obsidian": "触发同步到 Obsidian",
        "sync_notion": "触发同步到 Notion",
    }
    readable_permissions = "、".join(permission_lines[key] for key in agent_permissions if key in permission_lines)
    if not readable_permissions:
        readable_permissions = "只读知识库"

    knowledge_base_hint = snapshot.root_path or "当前未检测到可读取的 Obsidian 知识库目录"
    return (
        "你是用户网站里的 AI agent。"
        "你既可以回答问题，也可以在工具确认成功时代表用户执行站内操作。"
        "你必须优先基于用户自己的知识库和工具返回的信息工作，不要编造。"
        "当用户要求执行动作时，必须调用工具，不要只描述你会怎么做。"
        "如果某个权限没有开放，或某个工具执行失败，必须直接说明。"
        "只有在工具结果明确成功时，才能说操作已经完成。"
        "回答请使用中文，保持清楚直接。"
        f"当前知识库位置：{knowledge_base_hint}。"
        f"当前可用权限：{readable_permissions}。"
    )


def _compose_system_message(*parts: str | None) -> str:
    sections = [str(part).strip() for part in parts if str(part or "").strip()]
    return "\n\n".join(sections).strip()


def _analysis_organizer_system_prompt() -> str:
    return (
        "你是一个内容整理助手。"
        "你的任务是把当前文章已有的内容分析文字整理成适合阅读侧栏直接展示的结构化文本。"
        "不要整理正文，不要改写抓取正文、OCR 或帧文字，也不要把正文重新誊写进结果里。"
        "只允许基于提供的内容整理，不要补外部知识，不要编造。"
        "输出必须是纯文本，不要解释，不要加代码块。"
        "如果原文里已经有像 [detected_title]、[urls]、[qr_links] 这样的结构标记，优先保留并整理它们。"
        "优先输出以下结构："
        "[detected_title] 对整理后的标题；"
        "[body] 对整理后的内容分析。"
        "[body] 内请按“摘要 / 核心要点 / 链接与待确认”组织内容，修正乱换行、重复片段和层级混乱。"
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
                    value = _normalize_multiline_text(_strip_leading_analysis_heading(value))
                if not value and key != "detected_title":
                    continue
                normalized_sections.append(f"[{key}]\n{value}".rstrip())
            normalized = "\n\n".join(section for section in normalized_sections if section.strip()).strip()
        return normalized

    sections: list[str] = []
    if fallback_title:
        sections.append(f"[detected_title]\n{fallback_title}")
    sections.append(f"[body]\n{normalized}")
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
    return {
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
    }


def _agent_permissions(settings: Settings | None) -> list[str]:
    permissions = ["read_knowledge_base"]
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
    return permissions


def _build_agent_tools(agent_permissions: list[str]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "search_knowledge_base",
                "description": "Search the Obsidian knowledge base semantically and return the most relevant notes.",
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
                "name": "search_library_items",
                "description": "Search saved library items in the website and return item IDs for later actions.",
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
                "description": "List the most recent notes from the knowledge base.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_related_notes",
                "description": "Find related notes for one saved item by item_id.",
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
    ]

    if "manage_folders" in agent_permissions:
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


async def _execute_agent_tool(
    *,
    tool_name: str,
    arguments: dict[str, Any],
    db: Session,
    user_id: str,
    snapshot: KnowledgeBaseSnapshot,
    agent_permissions: list[str],
) -> tuple[dict[str, Any], AiToolEventResponse, list[tuple[KnowledgeBaseNote, float]], list[dict[str, Any]]]:
    limit = max(1, min(int(arguments.get("limit") or 5), 10))

    if tool_name == "search_knowledge_base":
        query = _clean_optional_string(arguments.get("query"))
        if not query:
            result = {"status": "error", "message": "query is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="知识库检索失败：缺少 query"), [], []
        ranked = rank_notes_for_query(snapshot, query, limit=limit) if snapshot.note_count else []
        result = {
            "status": "ok",
            "query": query,
            "results": [_tool_note_result(note, score) for note, score in ranked],
            "knowledge_base_path": snapshot.root_path,
            "note_count": snapshot.note_count,
        }
        summary = f"知识库检索完成，找到 {len(ranked)} 条相关笔记"
        return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, []

    if tool_name == "search_library_items":
        query = _clean_optional_string(arguments.get("query"))
        if not query:
            result = {"status": "error", "message": "query is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="站内搜索失败：缺少 query"), [], []
        from routers.items import rank_search_rows

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
        ranked_item_ids = rank_search_rows(candidate_rows, query)[:limit]
        items = db.query(Item).filter(Item.user_id == user_id, Item.id.in_(ranked_item_ids)).all() if ranked_item_ids else []
        items_by_id = {item.id: item for item in items}
        ordered_items = [items_by_id[item_id] for item_id in ranked_item_ids if item_id in items_by_id]
        ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
        for item in ordered_items:
            note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
            if note:
                ranked_notes.append((note, 1.0))
        result = {
            "status": "ok",
            "query": query,
            "results": [_tool_item_result(item, snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None) for item in ordered_items],
        }
        summary = f"站内内容搜索完成，找到 {len(ordered_items)} 条结果"
        return result, AiToolEventResponse(name=tool_name, summary=summary), ranked_notes, []

    if tool_name == "get_item_details":
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="读取笔记详情失败：Item not found"), [], []
        note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
        ranked = [(note, 1.0)] if note else []
        result = {"status": "ok", "item": _tool_item_result(item, note)}
        return result, AiToolEventResponse(name=tool_name, summary=f"已读取《{item.title or item.id}》的详情"), ranked, []

    if tool_name == "list_recent_notes":
        if snapshot.note_count:
            ranked = [(note, 1.0) for note in snapshot.notes[:limit]]
            result = {
                "status": "ok",
                "results": [_tool_note_result(note, score) for note, score in ranked],
                "knowledge_base_path": snapshot.root_path,
            }
            summary = f"已列出最近 {len(ranked)} 条知识库笔记"
            return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, []

        items = (
            db.query(Item)
            .filter(Item.user_id == user_id)
            .order_by(Item.created_at.desc())
            .limit(limit)
            .all()
        )
        result = {"status": "ok", "results": [_tool_item_result(item) for item in items]}
        summary = f"当前知识库为空，已列出最近 {len(items)} 条站内内容"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], []

    if tool_name == "get_related_notes":
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="查找相关笔记失败：Item not found"), [], []
        existing_note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
        seed_note = _build_seed_note_from_item(item, existing_note)
        ranked = rank_related_notes(snapshot, seed_note, limit=limit) if snapshot.note_count else []
        result = {
            "status": "ok",
            "item_id": item.id,
            "results": [_tool_note_result(note, score) for note, score in ranked],
        }
        summary = f"已找到 {len(ranked)} 条相关笔记"
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
                }
                for folder in folders
            ],
        }
        summary = f"已列出 {len(folders)} 个文件夹"
        return result, AiToolEventResponse(name=tool_name, summary=summary), [], []

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
        note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
        updated_item = serialize_items([item])[0].model_dump(mode="json")
        result = {
            "status": "ok",
            "item": _tool_item_result(item, note),
        }
        folder_text = "、".join(_extract_item_folder_names(item)) or "未归档"
        summary = f"已更新《{item.title or item.id}》的文件夹为：{folder_text}"
        ranked = [(note, 1.0)] if note else []
        return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, [updated_item]

    if tool_name == "parse_item_content":
        if "parse_content" not in agent_permissions:
            result = {"status": "error", "message": "Permission denied"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="没有开放内容解析权限"), [], []
        item_id = _clean_optional_string(arguments.get("item_id"))
        item = _get_user_item(db, user_id, item_id or "")
        if not item:
            result = {"status": "error", "message": "Item not found"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="内容解析失败：Item not found"), [], []

        from routers.items import _store_item_parse_failure, parse_item_content_for_item, serialize_items

        try:
            item.parse_status = "processing"
            item.parse_error = None
            db.commit()
            db.refresh(item)
            parse_item_content_for_item(item)
            db.commit()
            db.refresh(item)
            note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
            updated_item = serialize_items([item])[0].model_dump(mode="json")
            result = {
                "status": "ok",
                "item": _tool_item_result(item, note),
            }
            summary = f"已完成《{item.title or item.id}》的内容解析"
            ranked = [(note, 1.0)] if note else []
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
            note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
            ranked = [(note, 1.0)] if note else []
            updated_item = serialize_items([item])[0].model_dump(mode="json")
            return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, [updated_item]
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
            note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
            ranked = [(note, 1.0)] if note else []
            updated_item = serialize_items([item])[0].model_dump(mode="json")
            return result, AiToolEventResponse(name=tool_name, summary=summary), ranked, [updated_item]
        except HTTPException as exc:
            result = {"status": "error", "message": str(exc.detail)}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"Notion 同步失败：{exc.detail}"), [], []

    result = {"status": "error", "message": f"Unknown tool: {tool_name}"}
    return result, AiToolEventResponse(name=tool_name, status="failed", summary=f"未知工具：{tool_name}"), [], []


async def _run_agent_assistant(
    *,
    db: Session,
    user_id: str,
    ai_config: dict[str, str],
    settings: Settings | None,
    snapshot: KnowledgeBaseSnapshot,
    conversation: list[dict[str, str]],
    current_item: Item | None = None,
    current_item_note: KnowledgeBaseNote | None = None,
) -> AiAssistantResponse:
    agent_permissions = _agent_permissions(settings)
    tools = _build_agent_tools(agent_permissions)
    current_item_context = _build_current_item_context(current_item, current_item_note) if current_item is not None else ""
    system_message = _compose_system_message(
        _assistant_agent_system_prompt(agent_permissions, snapshot),
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

    for _ in range(_AGENT_TOOL_STEP_LIMIT):
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
                citations=_serialize_citations(db, user_id, collected_notes),
                tool_events=tool_events,
                knowledge_base_path=snapshot.root_path,
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
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else {}
            except json.JSONDecodeError:
                arguments = {}
                result = {"status": "error", "message": "Invalid JSON arguments"}
                event = AiToolEventResponse(name=tool_name, status="failed", summary=f"{tool_name} 参数解析失败")
                ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
                changed_items: list[dict[str, Any]] = []
            else:
                result, event, ranked_notes, changed_items = await _execute_agent_tool(
                    tool_name=tool_name,
                    arguments=arguments,
                    db=db,
                    user_id=user_id,
                    snapshot=snapshot,
                    agent_permissions=agent_permissions,
                )
            tool_events.append(event)
            _append_unique_ranked_notes(collected_notes, ranked_notes)
            _append_unique_updated_items(updated_items, changed_items)
            model_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "name": tool_name,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                }
            )

    model_messages.append(
        {
            "role": "system",
            "content": "停止继续调用工具。现在基于已有工具结果，给出最终简洁回答。",
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
        citations=_serialize_citations(db, user_id, collected_notes),
        tool_events=tool_events,
        knowledge_base_path=snapshot.root_path,
        note_count=snapshot.note_count,
        insufficient_context=False,
        agent_permissions=agent_permissions,
        updated_items=updated_items,
    )


@router.post("/ask", response_model=AiAskResponse)
async def ask_ai(request: AiAskRequest, db: Session = Depends(get_db)):
    question = (request.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    ai_config = _resolve_ai_config(settings)

    snapshot = load_knowledge_base_snapshot()
    if snapshot.note_count == 0:
        return AiAskResponse(
            question=question,
            answer="当前没有检测到可读取的 Obsidian 知识库笔记，所以无法基于知识库回答这个问题。",
            citations=[],
            knowledge_base_path=detect_knowledge_base_path(),
            note_count=0,
            insufficient_context=True,
        )

    top_k = max(3, min(int(request.top_k or 6), 10))
    ranked_notes = rank_notes_for_query(snapshot, question, limit=top_k)
    if not ranked_notes:
        return AiAskResponse(
            question=question,
            answer="知识库里没有找到足够相关的笔记，因此无法基于现有笔记回答这个问题。",
            citations=[],
            knowledge_base_path=snapshot.root_path,
            note_count=snapshot.note_count,
            insufficient_context=True,
        )

    note_context = "\n\n".join(
        _build_note_context_lines(note, index + 1)
        for index, (note, _) in enumerate(ranked_notes)
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
                    "content": (
                        f"用户问题：{question}\n\n"
                        "请基于下面这些笔记回答。若信息不够，请直接说明缺口。\n\n"
                        f"{note_context}"
                    ),
                },
            ],
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    return AiAskResponse(
        question=question,
        answer=answer.strip(),
        citations=_serialize_citations(db, user_id, ranked_notes),
        knowledge_base_path=snapshot.root_path,
        note_count=snapshot.note_count,
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
    snapshot = load_knowledge_base_snapshot()
    mode = "agent" if (request.mode or "").strip().lower() == "agent" else "chat"
    current_item_id = _clean_optional_string(request.current_item_id)
    current_item = _get_user_item(db, user_id, current_item_id) if current_item_id else None
    current_item_note = None
    if current_item:
        current_item_note = snapshot.notes_by_item_id.get(current_item.id) if snapshot.note_count else None
        current_item_note = _build_seed_note_from_item(current_item, current_item_note)

    if mode == "agent":
        return await _run_agent_assistant(
            db=db,
            user_id=user_id,
            ai_config=ai_config,
            settings=settings,
            snapshot=snapshot,
            conversation=conversation,
            current_item=current_item,
            current_item_note=current_item_note,
        )

    latest_question = ""
    for message in reversed(conversation):
        if message["role"] == "user":
            latest_question = message["content"]
            break
    if not latest_question:
        raise HTTPException(status_code=400, detail="At least one user message is required")

    if snapshot.note_count == 0 and current_item_note is None:
        return AiAssistantResponse(
            mode="chat",
            message="当前没有检测到可读取的 Obsidian 知识库笔记，所以我现在还不能基于知识库回答。",
            citations=[],
            knowledge_base_path=detect_knowledge_base_path(),
            note_count=0,
            insufficient_context=True,
            agent_permissions=_agent_permissions(settings),
            updated_items=[],
        )

    top_k = max(3, min(int(request.top_k or 6), 10))
    ranked_notes = rank_notes_for_query(snapshot, latest_question, limit=top_k) if snapshot.note_count else []
    combined_ranked_notes: list[tuple[KnowledgeBaseNote, float]] = []
    if current_item_note is not None:
        combined_ranked_notes.append((current_item_note, 1.0))
    for note, score in ranked_notes:
        if current_item_note is not None and note.note_id == current_item_note.note_id:
            continue
        combined_ranked_notes.append((note, score))

    if not combined_ranked_notes and current_item is not None:
        combined_ranked_notes.append((_build_seed_note_from_item(current_item, current_item_note), 1.0))

    if not combined_ranked_notes:
        return AiAssistantResponse(
            mode="chat",
            message="知识库里没有找到足够相关的笔记，因此我不能基于现有笔记回答这个问题。",
            citations=[],
            knowledge_base_path=snapshot.root_path,
            note_count=snapshot.note_count,
            insufficient_context=True,
            agent_permissions=_agent_permissions(settings),
            updated_items=[],
        )

    note_context = "\n\n".join(
        _build_note_context_lines(note, index + 1)
        for index, (note, _) in enumerate(combined_ranked_notes)
    )
    current_item_context = _build_current_item_context(current_item, current_item_note) if current_item is not None else ""
    system_message = _compose_system_message(
        _assistant_chat_system_prompt(),
        (
            "下面是当前文章上下文。回答当前文章相关问题时，优先依据这里的内容分析、抓取文本和 OCR / 帧文字。\n\n"
            f"{current_item_context}"
        ) if current_item_context else "",
        (
            "下面是本轮回答可用的知识库上下文。请把这些笔记作为辅助参考，优先使用已有 summary / 摘要，不要重复整理。\n\n"
            f"{note_context}"
        ) if note_context else "",
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

    return AiAssistantResponse(
        mode="chat",
        message=answer.strip(),
        citations=_serialize_citations(db, user_id, combined_ranked_notes),
        tool_events=[],
        knowledge_base_path=snapshot.root_path,
        note_count=snapshot.note_count,
        insufficient_context=False,
        agent_permissions=_agent_permissions(settings),
        updated_items=[],
    )


@router.get("/items/{item_id}/related", response_model=AiRelatedNotesResponse)
def related_notes(item_id: str, limit: int = 5, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = _get_user_item(db, user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    snapshot = load_knowledge_base_snapshot()
    existing_note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
    seed_note = _build_seed_note_from_item(item, existing_note)
    ranked_related = rank_related_notes(snapshot, seed_note, limit=max(1, min(limit, 8))) if snapshot.note_count else []

    return AiRelatedNotesResponse(
        item_id=item.id,
        related=_serialize_citations(db, user_id, ranked_related),
        knowledge_base_path=snapshot.root_path,
        note_count=snapshot.note_count,
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
    source_context = _build_analysis_organizer_context(item)

    try:
        response_text = await chat_completion(
            api_key=ai_config["api_key"],
            base_url=ai_config["base_url"],
            model=ai_config["model"],
            messages=[
                {"role": "system", "content": _analysis_organizer_system_prompt()},
                {
                    "role": "user",
                    "content": (
                        "请直接整理下面这条“内容分析”文本，并输出最终可保存的内容分析文本。\n\n"
                        f"{source_context}"
                    ),
                },
            ],
            temperature=0.2,
        )
    except AiClientError as exc:
        raise _ai_request_failed(exc) from exc

    organized_text = _normalize_organized_analysis_text(
        response_text,
        fallback_title=_clean_optional_string(item.title) or f"Item {item.id}",
    )
    if not organized_text:
        raise HTTPException(status_code=502, detail="AI returned empty organized analysis")

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

    snapshot = load_knowledge_base_snapshot()
    existing_note = snapshot.notes_by_item_id.get(item.id) if snapshot.note_count else None
    seed_note = _build_seed_note_from_item(item, existing_note)
    ranked_related = rank_related_notes(snapshot, seed_note, limit=4) if snapshot.note_count else []

    related_context = "\n\n".join(
        _build_note_context_lines(note, index + 1)
        for index, (note, _) in enumerate(ranked_related)
    ) or "无"
    current_note_context = _build_note_context_lines(seed_note, 0)

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
                        "请分析当前这条笔记。回答必须是 JSON，对象字段如下：\n"
                        "{\n"
                        '  "one_liner": "一句话总结",\n'
                        '  "core_points": ["核心观点1", "核心观点2"],\n'
                        '  "why_saved": "为什么值得保存",\n'
                        '  "themes": ["主题1", "主题2"],\n'
                        '  "thinking_questions": ["问题1", "问题2"]\n'
                        "}\n\n"
                        "当前笔记：\n"
                        f"{current_note_context}\n\n"
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
        knowledge_base_path=snapshot.root_path,
    )
