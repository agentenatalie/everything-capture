import os
import io
import re
import zipfile
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from database import get_db
from models import Item
from schemas import ItemResponse, MediaResponse
from paths import STATIC_DIR

router = APIRouter(
    prefix="/api",
    tags=["items"]
)

PLATFORM_ALIASES = {
    "all": "all",
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
    for item in items:
        media_list = []
        if item.media:
            for m in sorted(item.media, key=lambda x: x.display_order):
                media_list.append(MediaResponse(
                    type=m.type,
                    url=f"/static/{m.local_path}" if m.local_path else "",
                    original_url=m.original_url or "",
                    display_order=m.display_order,
                    inline_position=m.inline_position if m.inline_position is not None else -1.0,
                ))
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
            media=media_list,
        ))
    return results


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
    if normalized == "web":
        return query.filter(
            platform_expr.in_(["web", "generic", "general", "site"])
        ).filter(
            ~source_url_expr.like("%mp.weixin.qq.com%"),
            ~source_url_expr.like("%weixin.qq.com%"),
        )
    if normalized == "x":
        return query.filter(platform_expr.in_(["x", "twitter"]))

    return query.filter(platform_expr == normalized)


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


@router.get("/items", response_model=List[ItemResponse])
def get_items(
    response: Response,
    skip: int = 0,
    limit: int = 100,
    q: Optional[str] = None,
    platform: str = "all",
    db: Session = Depends(get_db),
):
    safe_limit = max(1, min(limit, 200))
    total_count = db.query(func.count(Item.id)).scalar() or 0

    raw_query = (q or "").strip()
    if raw_query:
        candidate_rows = (
            apply_platform_filter(
                db.query(
                    Item.id,
                    Item.title,
                    Item.canonical_text,
                    Item.source_url,
                    Item.platform,
                    Item.created_at,
                ),
                platform,
            )
            .all()
        )
        ranked_item_ids = rank_search_rows(candidate_rows, raw_query)
        visible_count = len(ranked_item_ids)
        page_item_ids = ranked_item_ids[skip: skip + safe_limit]
        if page_item_ids:
            items_by_id = {
                item.id: item
                for item in db.query(Item).filter(Item.id.in_(page_item_ids)).all()
            }
            items = [items_by_id[item_id] for item_id in page_item_ids if item_id in items_by_id]
        else:
            items = []
    else:
        items_query = apply_platform_filter(db.query(Item), platform)
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

@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    db.delete(item)
    db.commit()
    return None

@router.get("/items/{item_id}/export/zip")
def export_item_zip(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', item.title or f"Capture_{item.id}")[:100]
        
        # 1. Add all media files to a media/ folder in the zip
        media_map = {} # original url -> relative zip path
        for m in item.media:
            if m.local_path:
                local_file_path = STATIC_DIR / m.local_path
                if os.path.exists(local_file_path):
                    filename = os.path.basename(m.local_path)
                    zip_media_path = f"media/{filename}"
                    zf.write(local_file_path, arcname=zip_media_path)
                    media_map[m.original_url] = zip_media_path
                    
        # 2. Build Markdown payload
        from routers.connect import _build_obsidian_note

        full_content = _build_obsidian_note(item, media_map)
        
        # Add markdown file
        zf.writestr(f"{safe_title}.md", full_content.encode('utf-8'))
        
    zip_buffer.seek(0)

    download_name = f"{safe_title}.zip"
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]", "_", download_name) or f"capture_{item.id}.zip"
    
    return StreamingResponse(
        iter([zip_buffer.getvalue()]), 
        media_type="application/zip", 
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"{ascii_fallback}\"; "
                f"filename*=UTF-8''{quote(download_name)}"
            )
        }
    )
