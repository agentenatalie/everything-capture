from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Item
from schemas import ItemResponse, MediaResponse
from typing import List
from paths import STATIC_DIR

router = APIRouter(
    prefix="/api",
    tags=["items"]
)

@router.get("/items", response_model=List[ItemResponse])
def get_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(Item).order_by(Item.created_at.desc()).offset(skip).limit(limit).all()
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

import os
import shutil

@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    db.delete(item)
    db.commit()
    return None

import io
import zipfile
import re
from fastapi.responses import StreamingResponse
from urllib.parse import quote

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
