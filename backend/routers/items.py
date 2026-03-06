import os
import io
import re
import zipfile
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, text
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


def tokenize_search_query(query: str) -> list[str]:
    return [token.strip() for token in re.split(r"\s+", query) if token.strip()]


def build_match_query(tokens: list[str]) -> str:
    escaped_tokens = [token.replace('"', '""') for token in tokens if token]
    return " ".join(f'"{token}"' for token in escaped_tokens)


def build_like_search_condition(tokens: list[str]):
    title_expr = func.lower(func.coalesce(Item.title, ""))
    content_expr = func.lower(func.coalesce(Item.canonical_text, ""))
    source_url_expr = func.lower(func.coalesce(Item.source_url, ""))

    token_clauses = []
    for token in tokens:
        lowered = token.lower()
        pattern = f"%{lowered}%"
        token_clauses.append(
            or_(
                title_expr.like(pattern),
                content_expr.like(pattern),
                source_url_expr.like(pattern),
            )
        )

    if not token_clauses:
        return None
    return and_(*token_clauses)


def build_items_query(db: Session, q: Optional[str], platform: str):
    query = db.query(Item)
    query = apply_platform_filter(query, platform)

    raw_query = (q or "").strip()
    if not raw_query:
        return query

    tokens = tokenize_search_query(raw_query)
    if not tokens:
        return query

    if all(len(token) >= 3 for token in tokens):
        item_ids = db.execute(
            text(
                """
                SELECT item_id
                FROM items_fts
                WHERE items_fts MATCH :match_query
                """
            ),
            {"match_query": build_match_query(tokens)},
        ).scalars().all()

        if not item_ids:
            return query.filter(text("1 = 0"))
        return query.filter(Item.id.in_(item_ids))

    like_condition = build_like_search_condition(tokens)
    if like_condition is None:
        return query
    return query.filter(like_condition)


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
    items_query = build_items_query(db, q=q, platform=platform)
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
        yaml_frontmatter = f"---\nsource: {item.source_url}\nplatform: {item.platform}\ndate: {item.created_at.isoformat()}\n---\n\n"
        markdown_body = f"# {item.title}\n\n"
        
        if item.content_blocks_json:
            import json as _json
            try:
                blocks = _json.loads(item.content_blocks_json)
                for block in blocks:
                    if block["type"] == "text" and block.get("content"):
                        markdown_body += block["content"] + "\n\n"
                    elif block["type"] == "image" and block.get("url"):
                        local_url = block["url"]
                        filename = os.path.basename(local_url)
                        zip_media_path = f"media/{filename}"
                        markdown_body += f"![[{zip_media_path}]]\n\n"
            except Exception:
                markdown_body += str(item.canonical_text) + "\n\n"
        else:
            markdown_body += str(item.canonical_text) + "\n\n"
            for zip_media_path in media_map.values():
                 markdown_body += f"![[{zip_media_path}]]\n\n"
                 
        full_content = yaml_frontmatter + markdown_body
        
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
