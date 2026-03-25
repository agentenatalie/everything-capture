import os
import json
import re
import threading
import logging
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session
from database import SessionLocal, get_db
from models import AiConversation, Folder, Highlight, Item, ItemFolderLink, ItemPageNote
from schemas import (
    BulkFolderUpdateRequest,
    BulkFolderUpdateResponse,
    HighlightCreateRequest,
    HighlightListResponse,
    HighlightResponse,
    HighlightUpdateRequest,
    ItemContentUpdateRequest,
    ItemFolderUpdateRequest,
    ItemNoteUpdateRequest,
    ItemPageNoteCreateRequest,
    ItemPageNoteListResponse,
    ItemPageNoteResponse,
    ItemPageNoteUpdateRequest,
    ItemResponse,
    MediaResponse,
)
from paths import STATIC_DIR
from services.content_extraction import ContentExtractionError, parse_item_content
from tenant import get_current_user_id
from app_settings import USE_FTS5_SEARCH

router = APIRouter(
    prefix="/api",
    tags=["items"]
)

PLATFORM_ALIASES = {
    "all": "all",
    "github": "github",
    "xiaohongshu": "xiaohongshu",
    "douyin": "douyin",
    "wechat": "wechat",
    "web": "web",
    "generic": "web",
    "general": "web",
    "x": "x",
    "twitter": "x",
}

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9+#._/-]*|[\u4e00-\u9fff]+", re.IGNORECASE)
ASCII_TOKEN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+#._/-]*$", re.IGNORECASE)

COMPOUND_QUERY_EXPANSIONS = {
    "uiux": ("ui", "ux"),
    "uxui": ("ui", "ux"),
    "uix": ("ui", "ux"),
    "vibecoding": ("vibe", "coding", "vibe coding"),
}

SEARCH_INTENT_GROUPS = {
    "ui_design": {
        "triggers": (
            "ui",
            "ux",
            "uiux",
            "ui/ux",
            "界面",
            "交互",
            "设计",
            "设计感",
            "审美",
            "美感",
        ),
        "keywords": (
            ("ui", 2.6),
            ("ux", 2.6),
            ("视觉效果", 2.6),
            ("交互", 1.8),
            ("审美", 2.5),
            ("设计感", 2.2),
            ("美感", 2.0),
            ("组件", 1.5),
            ("组件库", 3.0),
            ("界面", 2.2),
            ("design", 1.4),
            ("component", 1.8),
            ("components", 1.8),
            ("component library", 2.8),
            ("design system", 2.5),
            ("设计系统", 2.8),
            ("shadcn", 3.0),
            ("shadcn/ui", 3.2),
            ("liquid glass", 3.2),
            ("glass", 1.6),
            ("动效", 1.5),
            ("vibe coding", 1.6),
        ),
        "gate_terms": (
            "ui",
            "ux",
            "uiux",
            "界面",
            "交互",
            "审美",
            "美感",
            "组件",
            "组件库",
            "component",
            "components",
            "component library",
            "design system",
            "设计系统",
            "shadcn",
            "shadcn/ui",
            "vibe coding",
        ),
    },
    "visual_effects": {
        "triggers": (
            "视觉效果",
            "特效",
            "动效",
            "liquid glass",
            "glass",
        ),
        "keywords": (
            ("液态玻璃", 4.0),
            ("liquid glass", 4.2),
            ("glass", 2.0),
            ("视觉效果", 3.4),
            ("动效", 2.2),
            ("交互", 1.3),
        ),
        "gate_terms": (
            "视觉效果",
            "液态玻璃",
            "liquid glass",
            "glass",
            "特效",
            "动效",
        ),
    },
    "open_source": {
        "triggers": (
            "github",
            "git",
            "repo",
            "repository",
            "开源",
            "源码",
            "代码",
            "star",
        ),
        "keywords": (
            ("github", 3.4),
            ("github.com", 3.8),
            ("git", 1.3),
            ("repo", 2.0),
            ("repository", 2.0),
            ("开源", 3.2),
            ("开源项目", 3.4),
            ("源码", 2.5),
            ("代码", 1.4),
            ("star", 1.6),
        ),
        "gate_terms": (
            "github",
            "github.com",
            "gitlab",
            "repo",
            "repository",
            "开源",
            "开源项目",
            "源码",
            "source code",
            "star",
        ),
        "require_title_or_source": True,
    },
}

FIELD_WEIGHTS = {
    "title": 4.8,
    "content": 1.9,
    "source_url": 3.2,
    "platform": 1.0,
}

EXACT_QUERY_WEIGHTS = {
    "title": 10.0,
    "content": 4.0,
    "source_url": 5.5,
}

INTENT_MATCH_BONUS = 2.4
MIN_SEARCH_SCORE = 2.5
PROCESSING_PARSE_RECOVERY_LIMIT = 32

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchBoostTerm:
    term: str
    weight: float
    intents: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchQueryPlan:
    raw: str
    normalized: str
    tokens: tuple[str, ...]
    intents: tuple[str, ...]
    boost_terms: tuple[SearchBoostTerm, ...]


def normalize_platform_filter(platform: Optional[str]) -> str:
    value = (platform or "all").strip().lower()
    return PLATFORM_ALIASES.get(value, value or "all")


def serialize_items(items: list[Item]) -> list[ItemResponse]:
    results = []
    from routers.connect import _obsidian_sync_state

    for item in items:
        media_list = []
        if item.media:
            for m in sorted(item.media, key=lambda x: x.display_order):
                media_list.append(MediaResponse(
                    type=m.type,
                    url=f"/static/{m.local_path}" if m.local_path else (m.original_url or ""),
                    original_url=m.original_url or "",
                    display_order=m.display_order,
                    inline_position=m.inline_position if m.inline_position is not None else -1.0,
                ))
        primary_folder_id = getattr(item, "folder_id", None)
        ordered_folder_links = sorted(
            [
                link
                for link in (item.folder_links or [])
                if getattr(link, "folder", None) is not None
            ],
            key=lambda link: (
                0 if primary_folder_id and link.folder_id == primary_folder_id else 1,
                getattr(link, "created_at", None) or datetime.min,
                (link.folder.name or "").lower(),
                link.folder_id,
            ),
        )
        if not ordered_folder_links and item.folder:
            ordered_folder_links = [
                ItemFolderLink(
                    item_id=item.id,
                    folder_id=item.folder.id,
                    folder=item.folder,
                    created_at=getattr(item, "created_at", None),
                )
            ]
        folder_ids = [link.folder_id for link in ordered_folder_links]
        folder_names = [link.folder.name for link in ordered_folder_links if link.folder and link.folder.name]
        primary_folder_id = folder_ids[0] if folder_ids else None
        primary_folder_name = folder_names[0] if folder_names else None

        try:
            frame_texts = json.loads(item.frame_texts_json) if item.frame_texts_json else []
        except json.JSONDecodeError:
            frame_texts = []
        try:
            urls = json.loads(item.urls_json) if item.urls_json else []
        except json.JSONDecodeError:
            urls = []
        try:
            qr_links = json.loads(item.qr_links_json) if item.qr_links_json else []
        except json.JSONDecodeError:
            qr_links = []

        results.append(ItemResponse(
            id=item.id,
            created_at=item.created_at,
            source_url=item.source_url,
            title=item.title,
            canonical_text=item.canonical_text,
            canonical_html=item.canonical_html,
            content_blocks_json=item.content_blocks_json,
            status=item.status,
            platform=item.platform,
            notion_page_id=item.notion_page_id,
            obsidian_path=item.obsidian_path,
            obsidian_sync_state=_obsidian_sync_state(item),
            extracted_text=item.extracted_text,
            ocr_text=item.ocr_text,
            frame_texts=frame_texts if isinstance(frame_texts, list) else [],
            urls=urls if isinstance(urls, list) else [],
            qr_links=qr_links if isinstance(qr_links, list) else [],
            parse_status=(item.parse_status or "idle"),
            parse_error=item.parse_error,
            parsed_at=item.parsed_at,
            folder_id=primary_folder_id,
            folder_name=primary_folder_name,
            folder_ids=folder_ids,
            folder_names=folder_names,
            folder_count=len(folder_ids),
            media=media_list,
        ))
    return results


def _serialize_page_note(note: ItemPageNote) -> ItemPageNoteResponse:
    return ItemPageNoteResponse(
        id=note.id,
        item_id=note.item_id,
        ai_conversation_id=note.ai_conversation_id,
        ai_message_index=note.ai_message_index,
        title=note.title,
        content=note.content or "",
        created_at=note.created_at or datetime.utcnow(),
        updated_at=note.updated_at or note.created_at or datetime.utcnow(),
    )


def _derive_page_note_title(title: str | None, content: str | None) -> str:
    explicit_title = (title or "").strip()
    if explicit_title:
        return explicit_title[:80]

    normalized_content = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    for raw_line in normalized_content.split("\n"):
        line = raw_line.strip().strip("#*- ")
        if line:
            return line[:80]
    return f"页面笔记 {datetime.utcnow().strftime('%m-%d %H:%M')}"


def apply_platform_filter(query, platform: str):
    normalized = normalize_platform_filter(platform)
    if normalized == "all":
        return query

    platform_expr = func.lower(func.coalesce(Item.platform, ""))
    source_url_expr = func.lower(func.coalesce(Item.source_url, ""))

    if normalized == "xiaohongshu":
        return query.filter(platform_expr == "xiaohongshu")
    if normalized == "douyin":
        return query.filter(platform_expr == "douyin")
    if normalized == "wechat":
        return query.filter(
            or_(
                platform_expr.in_(["wechat", "weixin"]),
                source_url_expr.like("%mp.weixin.qq.com%"),
                source_url_expr.like("%weixin.qq.com%"),
            )
        )
    if normalized == "github":
        return query.filter(
            or_(
                platform_expr == "github",
                source_url_expr.like("%github.com/%"),
            )
        )
    if normalized == "web":
        return query.filter(
            platform_expr.in_(["web", "generic", "general", "site"])
        ).filter(
            ~source_url_expr.like("%mp.weixin.qq.com%"),
            ~source_url_expr.like("%weixin.qq.com%"),
            ~source_url_expr.like("%github.com/%"),
        )
    if normalized == "x":
        return query.filter(platform_expr.in_(["x", "twitter"]))

    return query.filter(platform_expr == normalized)


def apply_folder_filter(query, folder_scope: str = "all", folder_id: Optional[str] = None):
    if folder_id:
        linked_item_ids = query.session.query(ItemFolderLink.item_id).filter(ItemFolderLink.folder_id == folder_id)
        return query.filter(Item.id.in_(linked_item_ids))

    normalized_scope = (folder_scope or "all").strip().lower()
    if normalized_scope == "unfiled":
        linked_item_ids = query.session.query(ItemFolderLink.item_id)
        return query.filter(~Item.id.in_(linked_item_ids))
    return query


def normalize_requested_folder_ids(folder_id: Optional[str], folder_ids: Optional[list[str]]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in [*(folder_ids or []), folder_id]:
        value = (raw_value or "").strip()
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def resolve_folders(db: Session, user_id: str, folder_ids: list[str]) -> list[Folder]:
    if not folder_ids:
        return []

    folders = db.query(Folder).filter(Folder.user_id == user_id, Folder.id.in_(folder_ids)).all()
    folders_by_id = {folder.id: folder for folder in folders}
    missing_ids = [folder_id for folder_id in folder_ids if folder_id not in folders_by_id]
    if missing_ids:
        raise HTTPException(status_code=404, detail="Folder not found")
    return [folders_by_id[folder_id] for folder_id in folder_ids]


def sync_item_folder_assignments(item: Item, folders: list[Folder]) -> None:
    selected_folder_ids = [folder.id for folder in folders]
    existing_links = {link.folder_id: link for link in (item.folder_links or [])}

    for folder_id, link in list(existing_links.items()):
        if folder_id not in selected_folder_ids:
            item.folder_links.remove(link)

    for folder in folders:
        if folder.id in existing_links:
            continue
        item.folder_links.append(
            ItemFolderLink(
                item_id=item.id,
                folder_id=folder.id,
                folder=folder,
            )
        )

    item.folder_id = selected_folder_ids[0] if selected_folder_ids else None


def _cleanup_item_media_files(local_paths: list[str]) -> None:
    checked_dirs: set[str] = set()
    for relative_path in {path for path in local_paths if path}:
        absolute_path = STATIC_DIR / relative_path
        if absolute_path.exists():
            try:
                absolute_path.unlink()
            except OSError:
                continue

        current_dir = absolute_path.parent
        while current_dir != STATIC_DIR and current_dir.exists():
            dir_key = str(current_dir)
            if dir_key in checked_dirs:
                break
            checked_dirs.add(dir_key)
            try:
                current_dir.rmdir()
            except OSError:
                break
            current_dir = current_dir.parent


def _store_item_parse_result(item: Item, parse_result) -> None:
    item.extracted_text = parse_result.extracted_text or None
    item.ocr_text = parse_result.ocr_text or None
    item.frame_texts_json = json.dumps(parse_result.frame_texts or [], ensure_ascii=False)
    item.urls_json = json.dumps(parse_result.urls or [], ensure_ascii=False)
    item.qr_links_json = json.dumps(parse_result.qr_links or [], ensure_ascii=False)
    item.parse_status = parse_result.parse_status or "completed"
    item.parse_error = parse_result.parse_error
    item.parsed_at = parse_result.parsed_at


def _store_item_parse_failure(item: Item, message: str) -> None:
    item.parse_status = "failed"
    item.parse_error = str(message or "Content parsing failed")


def parse_item_content_for_item(item: Item) -> None:
    parse_result = parse_item_content(item)
    _store_item_parse_result(item, parse_result)


def background_parse_item_content(item_id: str, user_id: str) -> None:
    with SessionLocal() as db:
        item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
        if not item:
            return

        item.parse_status = "processing"
        item.parse_error = None
        db.commit()
        db.refresh(item)

        try:
            parse_item_content_for_item(item)
            db.commit()
        except Exception as exc:
            db.rollback()
            item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
            if not item:
                return
            _store_item_parse_failure(item, str(exc))
            db.commit()


def _list_processing_parse_jobs(db: Session, *, limit: int = PROCESSING_PARSE_RECOVERY_LIMIT) -> list[tuple[str, str]]:
    rows = (
        db.query(Item.id, Item.user_id)
        .filter(Item.parse_status == "processing")
        .order_by(Item.created_at.asc())
        .limit(max(1, int(limit)))
        .all()
    )
    return [(str(item_id), str(user_id)) for item_id, user_id in rows if item_id and user_id]


def recover_processing_item_parsing(*, limit: int = PROCESSING_PARSE_RECOVERY_LIMIT) -> int:
    with SessionLocal() as db:
        jobs = _list_processing_parse_jobs(db, limit=limit)

    if not jobs:
        return 0

    logger.info("恢复后台内容解析任务 %d 个", len(jobs))
    recovered = 0
    for item_id, user_id in jobs:
        try:
            background_parse_item_content(item_id, user_id)
            recovered += 1
        except Exception as exc:
            logger.exception("恢复内容解析失败 %s: %s", item_id, exc)
    return recovered


def schedule_processing_item_parsing_recovery(*, limit: int = PROCESSING_PARSE_RECOVERY_LIMIT) -> None:
    thread = threading.Thread(
        target=recover_processing_item_parsing,
        kwargs={"limit": limit},
        daemon=True,
        name="item-parse-recovery",
    )
    thread.start()


def normalize_search_text(value: str) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return ""
    normalized = normalized.replace("ui/ux", "uiux")
    normalized = normalized.replace("ux/ui", "uiux")
    normalized = normalized.replace("vibe-coding", "vibe coding")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def tokenize_search_query(query: str) -> list[str]:
    normalized = normalize_search_text(query)
    if not normalized:
        return []

    tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in TOKEN_PATTERN.findall(normalized):
        token = raw_token.strip().lower()
        if not token:
            continue

        expanded_tokens = (token, *COMPOUND_QUERY_EXPANSIONS.get(token, ()))
        for expanded in expanded_tokens:
            cleaned = expanded.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            tokens.append(cleaned)
            seen.add(cleaned)
    return tokens


def detect_search_intents(normalized_query: str, tokens: list[str]) -> list[str]:
    matched: list[str] = []
    token_set = set(tokens)
    for intent_name, config in SEARCH_INTENT_GROUPS.items():
        triggers = config["triggers"]
        if any(trigger in normalized_query for trigger in triggers) or token_set.intersection(triggers):
            matched.append(intent_name)
    return matched


def build_search_query_plan(query: str) -> SearchQueryPlan:
    normalized = normalize_search_text(query)
    tokens = tokenize_search_query(normalized)
    intents = detect_search_intents(normalized, tokens)

    term_registry: OrderedDict[str, dict] = OrderedDict()

    def register_term(term: str, weight: float, *, intent: str | None = None) -> None:
        normalized_term = normalize_search_text(term)
        if not normalized_term:
            return

        entry = term_registry.setdefault(
            normalized_term,
            {"weight": weight, "intents": set()},
        )
        entry["weight"] = max(entry["weight"], weight)
        if intent:
            entry["intents"].add(intent)

    for token in tokens:
        register_term(token, 2.8)

    if normalized and " " in normalized:
        register_term(normalized, 4.2)

    for intent_name in intents:
        for keyword, weight in SEARCH_INTENT_GROUPS[intent_name]["keywords"]:
            register_term(keyword, weight, intent=intent_name)

    boost_terms = tuple(
        SearchBoostTerm(
            term=term,
            weight=entry["weight"],
            intents=tuple(sorted(entry["intents"])),
        )
        for term, entry in term_registry.items()
    )
    return SearchQueryPlan(
        raw=query,
        normalized=normalized,
        tokens=tuple(tokens),
        intents=tuple(intents),
        boost_terms=boost_terms,
    )


def contains_search_term(text_value: str, term: str) -> bool:
    if not text_value or not term:
        return False
    if ASCII_TOKEN_PATTERN.fullmatch(term):
        pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        return re.search(pattern, text_value, flags=re.IGNORECASE) is not None
    return term in text_value


def has_any_term(text_value: str, terms: tuple[str, ...]) -> bool:
    return any(contains_search_term(text_value, term) for term in terms)


def item_matches_intent_gates(
    plan: SearchQueryPlan,
    *,
    title_text: str,
    content_text: str,
    source_url_text: str,
    platform_text: str,
) -> bool:
    if not plan.intents:
        return True

    for intent_name in plan.intents:
        config = SEARCH_INTENT_GROUPS.get(intent_name, {})
        gate_terms = tuple(config.get("gate_terms", ()))
        if not gate_terms:
            continue

        title_or_source_match = (
            has_any_term(title_text, gate_terms)
            or has_any_term(source_url_text, gate_terms)
            or has_any_term(platform_text, gate_terms)
        )
        content_match = has_any_term(content_text, gate_terms)

        if config.get("require_title_or_source"):
            if title_or_source_match:
                return True
            continue

        if title_or_source_match or content_match:
            return True

    return False


def score_item_for_search(item, plan: SearchQueryPlan) -> float:
    if not plan.normalized:
        return 0.0

    title_text = normalize_search_text(getattr(item, "title", "") or "")
    content_text = normalize_search_text(getattr(item, "canonical_text", "") or "")
    source_url_text = normalize_search_text(getattr(item, "source_url", "") or "")
    platform_text = normalize_search_text(getattr(item, "platform", "") or "")

    if not item_matches_intent_gates(
        plan,
        title_text=title_text,
        content_text=content_text,
        source_url_text=source_url_text,
        platform_text=platform_text,
    ):
        return 0.0

    score = 0.0
    matched_intents: set[str] = set()

    for field_name, field_value in (
        ("title", title_text),
        ("content", content_text),
        ("source_url", source_url_text),
    ):
        if field_value and plan.normalized in field_value:
            score += EXACT_QUERY_WEIGHTS[field_name]

    for boost_term in plan.boost_terms:
        for field_name, field_value in (
            ("title", title_text),
            ("content", content_text),
            ("source_url", source_url_text),
            ("platform", platform_text),
        ):
            if contains_search_term(field_value, boost_term.term):
                score += boost_term.weight * FIELD_WEIGHTS[field_name]
                matched_intents.update(boost_term.intents)

    if matched_intents:
        score += len(matched_intents) * INTENT_MATCH_BONUS

    created_at = getattr(item, "created_at", None)
    if isinstance(created_at, datetime):
        age_days = max((datetime.utcnow() - created_at).total_seconds() / 86400.0, 0.0)
        score += max(0.0, 1.2 - age_days * 0.04)

    return score


def rank_search_rows(rows: list, query: str) -> list[str]:
    plan = build_search_query_plan(query)
    if not plan.boost_terms:
        return []

    scored_rows: list[tuple[float, datetime, str]] = []
    for row in rows:
        score = score_item_for_search(row, plan)
        if score < MIN_SEARCH_SCORE:
            continue
        created_at = getattr(row, "created_at", None) or datetime.min
        scored_rows.append((score, created_at, row.id))

    scored_rows.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
    return [item_id for _, _, item_id in scored_rows]


def build_fts_query(user_query: str) -> str:
    """
    将用户查询转换为FTS5查询表达式（trigram tokenizer）

    trigram tokenizer 将文本拆分为3字符序列，MATCH 相当于子串搜索。
    查询词必须至少3个字符才能匹配。
    多个词用 OR 组合以扩大召回。
    """
    tokens = tokenize_search_query(user_query)
    if not tokens:
        return ""

    # trigram tokenizer 要求每个搜索项至少3个字符
    fts_tokens = []
    for token in tokens:
        # 清理FTS5特殊语法字符，但保留中文和常规字符
        clean_token = re.sub(r'["*(){}^]', '', token).strip()
        if len(clean_token) >= 3:
            # 用双引号包裹，确保作为子串搜索而非FTS语法
            fts_tokens.append(f'"{clean_token}"')

    if not fts_tokens:
        # 所有token都太短，尝试用原始查询（如果够长）
        normalized = normalize_search_text(user_query)
        clean_raw = re.sub(r'["*(){}^]', '', normalized).strip()
        if len(clean_raw) >= 3:
            return f'"{clean_raw}"'
        return ""

    if len(fts_tokens) == 1:
        return fts_tokens[0]

    # 多个token用OR组合，扩大召回范围
    return " OR ".join(fts_tokens)


def search_with_fts5(db: Session, user_id: str, query: str, limit: int = 1000):
    """
    使用FTS5搜索相关项目
    返回: [(item_id, score), ...] 按相关性排序
    """
    fts_query = build_fts_query(query)
    if not fts_query:
        return []

    try:
        results = db.execute(
            text("""
            SELECT item_id, bm25(items_fts) as score
            FROM items_fts
            WHERE items_fts MATCH :fts_query
              AND item_id IN (SELECT id FROM items WHERE user_id = :user_id)
            ORDER BY score
            LIMIT :limit
            """),
            {"fts_query": fts_query, "user_id": user_id, "limit": limit}
        ).fetchall()
        return [(row[0], row[1]) for row in results]
    except Exception as exc:
        logger.warning("FTS5 search failed for query %r: %s", query, exc)
        return []


@router.get("/items/search-suggestions")
def get_search_suggestions(
    q: str,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """获取搜索建议"""
    user_id = get_current_user_id()

    if not q or len(q) < 2:
        return []

    fts_query = build_fts_query(q)
    if not fts_query:
        return []

    try:
        suggestions = db.execute(
            text("""
            SELECT
                item_id,
                snippet(items_fts, 1, '<mark>', '</mark>', '...', 16) as snippet,
                bm25(items_fts) as score
            FROM items_fts
            WHERE items_fts MATCH :fts_query
              AND item_id IN (SELECT id FROM items WHERE user_id = :user_id)
            ORDER BY score
            LIMIT :limit
            """),
            {"fts_query": fts_query, "user_id": user_id, "limit": limit}
        ).fetchall()

        return [
            {
                "item_id": row[0],
                "snippet": row[1],
                "score": row[2]
            }
            for row in suggestions
        ]
    except Exception as exc:
        logger.warning("FTS5 search-suggestions failed for query %r: %s", q, exc)
        return []


@router.get("/items/{item_id}", response_model=ItemResponse)
def get_item(
    item_id: str,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.user_id == user_id, Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return serialize_items([item])[0]


@router.get("/items", response_model=List[ItemResponse])
def get_items(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    platform: str = "all",
    folder_scope: str = "all",
    folder_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    safe_limit = max(1, min(limit, 10000))
    total_count = db.query(func.count(Item.id)).filter(Item.user_id == user_id).scalar() or 0

    raw_query = (q or "").strip()
    if raw_query:
        use_fts = USE_FTS5_SEARCH
        fts_results = None

        if use_fts:
            fts_results = search_with_fts5(db, user_id, raw_query, limit=1000)
            # FTS5 returned empty — could be a query too short for trigram;
            # fall through to legacy scoring so users still get results.
            if not fts_results:
                use_fts = False

        if use_fts and fts_results:
            # 提取item_id列表
            fts_item_ids = [item_id for item_id, score in fts_results]

            # 应用平台和文件夹过滤
            base_query = db.query(Item).filter(
                Item.user_id == user_id,
                Item.id.in_(fts_item_ids)
            )

            filtered_query = apply_folder_filter(
                apply_platform_filter(base_query, platform),
                folder_scope,
                folder_id
            )

            filtered_items = filtered_query.all()

            # 保持FTS5排序（bm25分数越低相关性越高）
            score_map = {item_id: score for item_id, score in fts_results}
            sorted_items = sorted(
                filtered_items,
                key=lambda item: score_map.get(item.id, 1000000)
            )

            visible_count = len(sorted_items)
            page_items = sorted_items[skip:skip + safe_limit]
            items = page_items
        else:
            # 使用原有搜索逻辑
            candidate_rows = (
                apply_folder_filter(
                    apply_platform_filter(
                        db.query(
                            Item.id,
                            Item.user_id,
                            Item.title,
                            Item.canonical_text,
                            Item.source_url,
                            Item.platform,
                            Item.created_at,
                        ).filter(Item.user_id == user_id),
                        platform,
                    ),
                    folder_scope,
                    folder_id,
                )
                .all()
            )
            ranked_item_ids = rank_search_rows(candidate_rows, raw_query)
            visible_count = len(ranked_item_ids)
            page_item_ids = ranked_item_ids[skip: skip + safe_limit]
            if page_item_ids:
                items_by_id = {
                    item.id: item
                    for item in db.query(Item).filter(Item.user_id == user_id, Item.id.in_(page_item_ids)).all()
                }
                items = [items_by_id[item_id] for item_id in page_item_ids if item_id in items_by_id]
            else:
                items = []
    else:
        items_query = apply_folder_filter(
            apply_platform_filter(db.query(Item).filter(Item.user_id == user_id), platform),
            folder_scope,
            folder_id,
        )
        visible_count = items_query.count()
        items = (
            items_query
            .order_by(Item.created_at.desc())
            .offset(skip)
            .limit(safe_limit)
            .all()
        )

    response.headers["X-Total-Count"] = str(total_count)
    response.headers["X-Visible-Count"] = str(visible_count)
    response.headers["X-Returned-Count"] = str(len(items))
    return serialize_items(items)


@router.patch("/items/{item_id}/folder", response_model=ItemResponse)
def update_item_folder(
    item_id: str,
    request: ItemFolderUpdateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    requested_folder_ids = normalize_requested_folder_ids(request.folder_id, request.folder_ids)
    folders = resolve_folders(db, user_id, requested_folder_ids)
    sync_item_folder_assignments(item, folders)
    now = datetime.utcnow()
    for folder in folders:
        folder.updated_at = now

    db.commit()
    db.refresh(item)
    return serialize_items([item])[0]


@router.post("/items/bulk-folder", response_model=BulkFolderUpdateResponse)
def bulk_update_item_folder(
    request: BulkFolderUpdateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    item_ids = [item_id for item_id in request.item_ids if item_id]
    if not item_ids:
        raise HTTPException(status_code=400, detail="item_ids is required")

    requested_folder_ids = normalize_requested_folder_ids(request.folder_id, request.folder_ids)
    folders = resolve_folders(db, user_id, requested_folder_ids)
    items = db.query(Item).filter(Item.user_id == user_id, Item.id.in_(item_ids)).all()
    if not items:
        raise HTTPException(status_code=404, detail="Items not found")

    now = datetime.utcnow()
    for item in items:
        sync_item_folder_assignments(item, folders)
    for folder in folders:
        folder.updated_at = now

    db.commit()
    return BulkFolderUpdateResponse(updated_count=len(items))


@router.post("/items/{item_id}/parse-content", response_model=ItemResponse)
def parse_item_content_endpoint(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.parse_status = "processing"
    item.parse_error = None
    db.commit()
    db.refresh(item)

    try:
        parse_item_content_for_item(item)
        db.commit()
        db.refresh(item)
        return serialize_items([item])[0]
    except ContentExtractionError as exc:
        db.rollback()
        item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
        if item:
            _store_item_parse_failure(item, str(exc))
            db.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
        if item:
            _store_item_parse_failure(item, "Content parsing failed")
            db.commit()
        raise HTTPException(status_code=500, detail="Content parsing failed") from exc


@router.patch("/items/{item_id}/content", response_model=ItemResponse)
def update_item_content(
    item_id: str,
    request: ItemContentUpdateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if request.title is not None:
        new_title = request.title.strip() or None
        item.title = new_title
        # Also update [detected_title] in extracted_text so getDisplayItemTitle picks it up
        if new_title and item.extracted_text:
            if re.search(r'^\[detected_title\]', item.extracted_text, re.MULTILINE):
                item.extracted_text = re.sub(
                    r'(\[detected_title\]\n?).*?(?=\n\[|\Z)',
                    rf'\g<1>{new_title}\n',
                    item.extracted_text,
                    count=1,
                    flags=re.DOTALL,
                )
            else:
                item.extracted_text = f"[detected_title]\n{new_title}\n{item.extracted_text}"
    if request.canonical_text is not None:
        item.canonical_text = request.canonical_text
        item.canonical_text_length = len(request.canonical_text) if request.canonical_text else 0
    if request.canonical_html is not None:
        item.canonical_html = request.canonical_html
        # Clear content_blocks_json so renderWebArticle falls back to canonical_html
        item.content_blocks_json = None

    db.commit()
    db.refresh(item)
    return serialize_items([item])[0]


@router.patch("/items/{item_id}/note", response_model=ItemResponse)
def update_item_note(
    item_id: str,
    request: ItemNoteUpdateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    next_text = (request.extracted_text or "").strip()
    item.extracted_text = next_text or None
    if item.extracted_text and (item.parse_status or "idle") == "idle":
        item.parse_status = "completed"
    if item.extracted_text and item.parsed_at is None:
        item.parsed_at = datetime.utcnow()

    db.commit()
    db.refresh(item)
    return serialize_items([item])[0]


@router.get("/items/{item_id}/page-notes", response_model=ItemPageNoteListResponse)
def list_item_page_notes(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    notes = (
        db.query(ItemPageNote)
        .filter(ItemPageNote.item_id == item_id, ItemPageNote.user_id == user_id)
        .order_by(ItemPageNote.updated_at.desc(), ItemPageNote.created_at.desc())
        .all()
    )
    return ItemPageNoteListResponse(notes=[_serialize_page_note(note) for note in notes])


@router.post("/items/{item_id}/page-notes", response_model=ItemPageNoteResponse)
def create_item_page_note(
    item_id: str,
    request: ItemPageNoteCreateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    ai_conversation_id = (request.ai_conversation_id or "").strip() or None
    if ai_conversation_id:
        conversation = (
            db.query(AiConversation)
            .filter(AiConversation.id == ai_conversation_id, AiConversation.user_id == user_id)
            .first()
        )
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")

    now = datetime.utcnow()
    note = ItemPageNote(
        item_id=item.id,
        user_id=user_id,
        workspace_id=item.workspace_id,
        ai_conversation_id=ai_conversation_id,
        ai_message_index=request.ai_message_index,
        title=_derive_page_note_title(request.title, request.content),
        content=(request.content or "").strip(),
        created_at=now,
        updated_at=now,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _serialize_page_note(note)


@router.patch("/items/{item_id}/page-notes/{note_id}", response_model=ItemPageNoteResponse)
def update_item_page_note(
    item_id: str,
    note_id: str,
    request: ItemPageNoteUpdateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    note = (
        db.query(ItemPageNote)
        .filter(
            ItemPageNote.id == note_id,
            ItemPageNote.item_id == item_id,
            ItemPageNote.user_id == user_id,
        )
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Page note not found")

    next_content = note.content
    if request.content is not None:
        next_content = request.content.strip()

    if request.title is not None:
        note.title = _derive_page_note_title(request.title, next_content)
    if request.content is not None:
        note.content = next_content
        if request.title is None and not (note.title or "").strip():
            note.title = _derive_page_note_title(None, note.content)
    note.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(note)
    return _serialize_page_note(note)


@router.delete("/items/{item_id}/page-notes/{note_id}", status_code=204)
def delete_item_page_note(item_id: str, note_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    note = (
        db.query(ItemPageNote)
        .filter(
            ItemPageNote.id == note_id,
            ItemPageNote.item_id == item_id,
            ItemPageNote.user_id == user_id,
        )
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Page note not found")

    db.delete(note)
    db.commit()
    return None

# ── Highlights ──────────────────────────────────────────────────────────


def _serialize_highlight(h: Highlight) -> HighlightResponse:
    return HighlightResponse(
        id=h.id,
        item_id=h.item_id,
        color=h.color or "yellow",
        text=h.text or "",
        selector_path=h.selector_path or "",
        start_text_node_index=h.start_text_node_index or 0,
        start_offset=h.start_offset or 0,
        end_selector_path=h.end_selector_path or "",
        end_text_node_index=h.end_text_node_index or 0,
        end_offset=h.end_offset or 0,
        context_before=h.context_before or "",
        context_after=h.context_after or "",
        page_note_id=h.page_note_id,
        created_at=h.created_at,
        updated_at=h.updated_at,
    )


@router.get("/items/{item_id}/highlights", response_model=HighlightListResponse)
def list_item_highlights(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    highlights = (
        db.query(Highlight)
        .filter(Highlight.item_id == item_id, Highlight.user_id == user_id)
        .order_by(Highlight.created_at.asc())
        .all()
    )
    return HighlightListResponse(highlights=[_serialize_highlight(h) for h in highlights])


@router.post("/items/{item_id}/highlights", response_model=HighlightResponse)
def create_item_highlight(
    item_id: str,
    request: HighlightCreateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    page_note_id = (request.page_note_id or "").strip() or None
    if page_note_id:
        note = (
            db.query(ItemPageNote)
            .filter(ItemPageNote.id == page_note_id, ItemPageNote.user_id == user_id)
            .first()
        )
        if not note:
            raise HTTPException(status_code=404, detail="Page note not found")

    now = datetime.utcnow()
    highlight = Highlight(
        item_id=item.id,
        user_id=user_id,
        workspace_id=item.workspace_id,
        color=request.color,
        text=request.text,
        selector_path=request.selector_path,
        start_text_node_index=request.start_text_node_index,
        start_offset=request.start_offset,
        end_selector_path=request.end_selector_path,
        end_text_node_index=request.end_text_node_index,
        end_offset=request.end_offset,
        context_before=request.context_before[:200] if request.context_before else "",
        context_after=request.context_after[:200] if request.context_after else "",
        page_note_id=page_note_id,
        created_at=now,
        updated_at=now,
    )
    db.add(highlight)
    db.commit()
    db.refresh(highlight)
    return _serialize_highlight(highlight)


@router.patch("/items/{item_id}/highlights/{highlight_id}", response_model=HighlightResponse)
def update_item_highlight(
    item_id: str,
    highlight_id: str,
    request: HighlightUpdateRequest,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    highlight = (
        db.query(Highlight)
        .filter(
            Highlight.id == highlight_id,
            Highlight.item_id == item_id,
            Highlight.user_id == user_id,
        )
        .first()
    )
    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")

    if request.color is not None:
        highlight.color = request.color
    if request.page_note_id is not None:
        page_note_id = request.page_note_id.strip() or None
        if page_note_id:
            note = (
                db.query(ItemPageNote)
                .filter(ItemPageNote.id == page_note_id, ItemPageNote.user_id == user_id)
                .first()
            )
            if not note:
                raise HTTPException(status_code=404, detail="Page note not found")
        highlight.page_note_id = page_note_id
    highlight.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(highlight)
    return _serialize_highlight(highlight)


@router.delete("/items/{item_id}/highlights/{highlight_id}", status_code=204)
def delete_item_highlight(item_id: str, highlight_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    highlight = (
        db.query(Highlight)
        .filter(
            Highlight.id == highlight_id,
            Highlight.item_id == item_id,
            Highlight.user_id == user_id,
        )
        .first()
    )
    if not highlight:
        raise HTTPException(status_code=404, detail="Highlight not found")

    db.delete(highlight)
    db.commit()
    return None


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    local_paths = [media.local_path for media in item.media if media.local_path]
    db.delete(item)
    db.commit()
    _cleanup_item_media_files(local_paths)
    return None


# NOTE: /items/search-suggestions route is defined above /items/{item_id}
# to prevent FastAPI from capturing "search-suggestions" as an item_id path param.
