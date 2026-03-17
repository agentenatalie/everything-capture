from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
from models import AiConversation, Folder, Item, ItemPageNote, Settings
from schemas import (
    AiAskRequest,
    AiAskResponse,
    AiAssistantRequest,
    AiAssistantResponse,
    AiCitationResponse,
    AiConversationListResponse,
    AiConversationResponse,
    AiConversationSaveRequest,
    AiConversationStoredMessage,
    AiConversationSummaryResponse,
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
    rank_notes_for_expanded_queries,
    rank_notes_for_query,
    rank_related_notes,
)
from tenant import get_current_user_id

router = APIRouter(prefix="/api/ai", tags=["ai"])

_JSON_FENCE_PATTERN = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")
_CITATION_INDEX_PATTERN = re.compile(r"\[(\d{1,2})\]")
_CHAT_HISTORY_LIMIT = 10
_SAVED_CHAT_HISTORY_LIMIT = 120
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


def _get_item_page_notes(db: Session, user_id: str, item_id: str) -> list[ItemPageNote]:
    return db.query(ItemPageNote).filter(ItemPageNote.user_id == user_id, ItemPageNote.item_id == item_id).all()


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


def _filter_ranked_notes_by_citation_markers(
    answer_text: str | None,
    ranked_notes: list[tuple[KnowledgeBaseNote, float]],
) -> list[tuple[KnowledgeBaseNote, float]]:
    if not ranked_notes:
        return []

    referenced_positions: list[int] = []
    seen_positions: set[int] = set()
    for raw_index in _CITATION_INDEX_PATTERN.findall(str(answer_text or "")):
        try:
            index = int(raw_index)
        except ValueError:
            continue
        if index < 1 or index > len(ranked_notes) or index in seen_positions:
            continue
        referenced_positions.append(index)
        seen_positions.add(index)

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
        "你是一个读过用户个人知识库的研究助理。"
        "只能基于提供的笔记回答，不要引入外部常识来补空。"
        "优先使用每篇笔记已有的 `summary` / `摘要`，不要重复整理同一份知识。"
        "如果证据不足，必须明确说信息不足。"
        "只有在你实际引用了某条笔记时，才使用 [1] [2] 这样的引用编号。"
        "如果答案没有直接引用具体笔记，就不要输出引用编号。"
        "\n\n"
        "【重要】仔细审查所有提供的笔记，不要只看标题是否字面匹配用户问题。"
        "要深入理解每篇笔记的实际内容和用途，判断它是否能间接回答用户的问题。"
        "例如：用户问'找实习要用什么工具'，一篇关于'简历自动填写'的笔记就是高度相关的。"
    )


def _analysis_system_prompt() -> str:
    return (
        "你是一个读过用户知识库的研究助理。"
        "当前任务是分析一条笔记，不要机械复述现有摘要。"
        "分析时要结合正文内容和用户在文章上的笔记内容一起综合判断。"
        "要以现有摘要为锚点，补充更高层次的理解、归类、关联和思考方向。"
        "只基于提供的内容做判断，不要编造。"
        "返回严格 JSON。"
    )


def _assistant_chat_system_prompt() -> str:
    return (
        "你是用户网站里的 AI chatbot。"
        "你的职责是和用户的个人知识库以及当前打开的文章对话，而不是泛泛聊天。"
        "如果提供了当前文章上下文，优先依据当前文章的内容分析、抓取文本、OCR / 帧文字以及用户在文章上的笔记综合回答。"
        "回答时要结合正文内容和用户笔记内容一起分析，而不是只看其中一个。"
        "如果同时提供了知识库笔记，优先使用已有 `summary` / `摘要` 作为辅助，不要机械重复整理。"
        "只能基于提供的上下文回答；若上下文不足，必须明确说明。"
        "回答请使用中文，保持简洁。"
        "只有在你实际引用了某条知识库笔记时，才使用 [1] [2] 引用编号。"
        "如果没有直接引用具体笔记，就不要输出引用编号。"
        "\n\n"
        "【重要】仔细审查所有提供的笔记，不要只看标题是否字面匹配用户问题。"
        "要深入理解每篇笔记的实际内容和用途，判断它是否能间接回答用户的问题。"
        "例如：用户问'找实习要用什么工具'，一篇关于'简历自动填写'的笔记就是高度相关的。"
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
        "只有在你最终说明里直接引用了某条知识库笔记时，才使用 [1] [2] 引用编号。"
        "如果没有直接引用具体笔记，就不要输出引用编号。"
        "\n\n"
        "【重要：智能检索策略】\n"
        "当用户提问时，你必须主动进行多轮、多角度的知识库检索，而不是只搜索一次：\n"
        "1. 先用用户原始问题的关键词搜索一次。\n"
        "2. 然后思考用户真正想要找的内容可能以什么形式保存在知识库中——"
        "考虑同义词、相关概念、不同的表述方式。"
        "例如用户问'申请实习用什么工具'，你应该额外搜索'简历''求职''resume''job application'等。\n"
        "3. 如果第一次搜索结果不够理想（分数低或明显不相关），务必用不同的关键词再搜索1-2次。\n"
        "4. 同时使用 search_knowledge_base 和 search_library_items 来扩大搜索范围。\n"
        "5. 综合所有搜索结果后再给出最终回答。\n"
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
    "帮助在个人知识库中通过关键词匹配找到相关内容。\n"
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
# Stage 2: Unified TF-IDF candidate retrieval (Obsidian notes + DB items)
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


def _build_unified_snapshot(
    snapshot: KnowledgeBaseSnapshot,
    db_items: list[Item] | None = None,
) -> KnowledgeBaseSnapshot:
    """Merge Obsidian notes with database items into one searchable snapshot."""
    seen_item_ids: set[str] = set()
    all_notes: list[KnowledgeBaseNote] = list(snapshot.notes)
    for note in snapshot.notes:
        if note.item_id:
            seen_item_ids.add(note.item_id)

    if db_items:
        for item in db_items:
            if item.id in seen_item_ids:
                continue
            virtual_note = _item_to_virtual_note(item)
            virtual_note = prepare_note_for_similarity(virtual_note)
            all_notes.append(virtual_note)
            seen_item_ids.add(item.id)

    return KnowledgeBaseSnapshot(
        root_path=snapshot.root_path,
        notes=all_notes,
        loaded_at=snapshot.loaded_at,
    )


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
    "你是知识库语义精排助手。下面列出了一组候选内容的编号、标题和摘要。"
    "请根据用户的问题，选出所有真正相关的条目编号。\n"
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
    """Three-stage semantic search: expand → retrieve → rerank.

    Works with any knowledge base size:
    - Stage 1 (expand): AI generates synonym/related-concept queries (~100 tokens)
    - Stage 2 (retrieve): TF-IDF across ALL content (Obsidian + DB), takes top 30
    - Stage 3 (rerank): AI picks the truly relevant ones from 30 candidates (~3k tokens)
    """
    # Build unified searchable snapshot (Obsidian + DB items)
    db_items = _load_all_user_items(db, user_id) if db and user_id else None
    unified = _build_unified_snapshot(snapshot, db_items=db_items)

    # Stage 1: AI query expansion
    expanded_queries = await _expand_search_queries(ai_config, question)

    # Stage 2: TF-IDF candidate retrieval with expanded queries
    candidates = _retrieve_candidates(unified, expanded_queries, pool_size=_CANDIDATE_POOL_SIZE)

    if not candidates:
        return []

    # Stage 3: AI reranker on the candidate pool
    reranked = await _ai_rerank_candidates(ai_config, candidates, question, limit=limit)

    # If reranker returned nothing (e.g. API failure), fall back to TF-IDF order
    if not reranked:
        return candidates[:limit]

    return reranked


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
                "knowledge_base_path": _clean_optional_string(payload.get("knowledge_base_path")),
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
                "description": (
                    "Search the Obsidian knowledge base and return the most relevant notes. "
                    "The search uses keyword matching, so choose your query terms carefully. "
                    "Tips: use specific keywords rather than full sentences; "
                    "try synonyms and related concepts if the first search doesn't yield good results; "
                    "call this tool multiple times with different queries to improve recall."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search keywords or short phrase. Use specific, concrete terms."},
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
                "description": "Search saved library items in the website database. Complements search_knowledge_base - use both for comprehensive results. Try different keywords if initial results are not satisfying.",
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
    ai_config: dict[str, str] | None = None,
) -> tuple[dict[str, Any], AiToolEventResponse, list[tuple[KnowledgeBaseNote, float]], list[dict[str, Any]]]:
    limit = max(1, min(int(arguments.get("limit") or 5), 10))

    if tool_name == "search_knowledge_base":
        query = _clean_optional_string(arguments.get("query"))
        if not query:
            result = {"status": "error", "message": "query is required"}
            return result, AiToolEventResponse(name=tool_name, status="failed", summary="知识库检索失败：缺少 query"), [], []
        if ai_config:
            ranked = await _semantic_rank_notes(ai_config, snapshot, query, limit=limit, db=db, user_id=user_id)
        else:
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
    current_page_notes = _get_item_page_notes(db, user_id, current_item.id) if current_item else []
    current_item_context = _build_current_item_context(current_item, current_item_note, current_page_notes) if current_item is not None else ""
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
                citations=_serialize_citations(
                    db,
                    user_id,
                    _filter_ranked_notes_by_citation_markers(final_message, collected_notes),
                ),
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
                    ai_config=ai_config,
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
        citations=_serialize_citations(
            db,
            user_id,
            _filter_ranked_notes_by_citation_markers(final_text, collected_notes),
        ),
        tool_events=tool_events,
        knowledge_base_path=snapshot.root_path,
        note_count=snapshot.note_count,
        insufficient_context=False,
        agent_permissions=agent_permissions,
        updated_items=updated_items,
    )


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

    snapshot = load_knowledge_base_snapshot()

    top_k = max(3, min(int(request.top_k or 6), 10))
    ranked_notes = await _semantic_rank_notes(ai_config, snapshot, question, limit=top_k, db=db, user_id=user_id)
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
        citations=_serialize_citations(
            db,
            user_id,
            _filter_ranked_notes_by_citation_markers(answer, ranked_notes),
        ),
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
    current_page_notes: list[ItemPageNote] = []
    if current_item:
        current_item_note = snapshot.notes_by_item_id.get(current_item.id) if snapshot.note_count else None
        current_item_note = _build_seed_note_from_item(current_item, current_item_note)
        current_page_notes = _get_item_page_notes(db, user_id, current_item.id)

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

    top_k = max(3, min(int(request.top_k or 6), 10))
    ranked_notes = await _semantic_rank_notes(ai_config, snapshot, latest_question, limit=top_k, db=db, user_id=user_id)
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
    current_item_context = _build_current_item_context(current_item, current_item_note, current_page_notes) if current_item is not None else ""
    system_message = _compose_system_message(
        _assistant_chat_system_prompt(),
        (
            "下面是当前文章上下文（包括正文内容和用户笔记）。回答时请结合正文内容和用户笔记综合分析。\n\n"
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
        citations=_serialize_citations(
            db,
            user_id,
            _filter_ranked_notes_by_citation_markers(answer, combined_ranked_notes),
        ),
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
        knowledge_base_path=snapshot.root_path,
    )
