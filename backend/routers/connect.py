from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Item, Settings
import httpx
import logging
import json

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/connect",
    tags=["connect"]
)

from fastapi.responses import RedirectResponse
import base64
import urllib.parse

@router.get("/notion/oauth/url")
async def get_notion_oauth_url(db: Session = Depends(get_db)):
    settings = db.query(Settings).first()
    if not settings or not settings.notion_client_id or not settings.notion_redirect_uri:
        raise HTTPException(status_code=400, detail="Notion Client ID or Redirect URI not configured in Settings.")
    
    encoded_redirect = urllib.parse.quote(settings.notion_redirect_uri, safe='')
    auth_url = f"https://api.notion.com/v1/oauth/authorize?client_id={settings.notion_client_id}&response_type=code&owner=user&redirect_uri={encoded_redirect}"
    return {"url": auth_url}

@router.get("/notion/oauth/callback")
async def notion_oauth_callback(code: str, error: str = None, db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(url=f"/?notion_auth=failed&error={urllib.parse.quote(error)}")
        
    settings = db.query(Settings).first()
    if not settings or not settings.notion_client_id or not settings.notion_client_secret or not settings.notion_redirect_uri:
        return RedirectResponse(url="/?notion_auth=failed&error=missing_config")

    # Exchange code for access token
    auth_string = f"{settings.notion_client_id}:{settings.notion_client_secret}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.notion_redirect_uri
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://api.notion.com/v1/oauth/token", headers=headers, json=payload, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                settings.notion_api_token = data.get("access_token")
                db.commit()
                return RedirectResponse(url="/?notion_auth=success")
            else:
                logger.error(f"Notion OAuth token exchange failed: {response.text}")
                return RedirectResponse(url="/?notion_auth=failed&error=exchange_failed")
        except Exception as e:
            logger.error(f"Notion OAuth token exchange error: {str(e)}")
            return RedirectResponse(url="/?notion_auth=failed&error=network_error")

@router.post("/notion/sync/{item_id}")
async def sync_to_notion(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    settings = db.query(Settings).first()
    if not settings or not settings.notion_api_token or not settings.notion_database_id:
        raise HTTPException(status_code=400, detail="Notion settings are incomplete")
        
    if item.notion_page_id:
        # Already synced
        return {"status": "ok", "message": "Already synced", "notion_page_id": item.notion_page_id}

    # Construct Notion API request
    headers = {
        "Authorization": f"Bearer {settings.notion_api_token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # We create basic blocks from canonical_text, chunking by paragraphs to build Notion blocks
    blocks = []
    
    # 1. Add images
    for m in sorted(item.media, key=lambda x: x.display_order):
        if m.type == "image" and m.original_url:
            blocks.append({
                "object": "block",
                "type": "image",
                "image": {
                    "type": "external",
                    "external": {
                        "url": m.original_url
                    }
                }
            })
            
    # 2. Add text blocks
    text_content = item.canonical_text or "No content available."
    paragraphs = text_content.split('\n\n')
    
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
            
        chunks = [p[i:i+2000] for i in range(0, len(p), 2000)]
        for chunk in chunks:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {
                            "type": "text",
                            "text": {
                                "content": chunk
                            }
                        }
                    ]
                }
            })
            
    # 3. Add source URL at the end
    blocks.append({
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                {
                    "type": "text",
                    "text": {
                        "content": "Source: "
                    }
                },
                {
                    "type": "text",
                    "text": {
                        "content": item.source_url,
                        "link": {"url": item.source_url}
                    }
                }
            ]
        }
    })

    # Notion pages can only be created with 100 blocks at most per request
    blocks = blocks[:100]

    payload = {
        "parent": { "type": "database_id", "database_id": settings.notion_database_id },
        "properties": {
            "Name": { # Default title property name in Notion databases
                "title": [
                    {
                        "text": {
                            "content": item.title or "Untitled"
                        }
                    }
                ]
            }
        },
        "children": blocks
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://api.notion.com/v1/pages", headers=headers, json=payload, timeout=20.0)
            if response.status_code != 200:
                error_body = response.text
                logger.error(f"Notion API error: {error_body}")
                raise HTTPException(status_code=500, detail=f"Notion API returned {response.status_code}: {error_body}")
                
            data = response.json()
            page_id = data.get("id")
            
            # Save the notion page ID
            item.notion_page_id = page_id
            db.commit()
            
            return {"status": "ok", "notion_page_id": page_id}
            
        except httpx.RequestError as e:
            logger.error(f"Network error to Notion API: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Network error connecting to Notion: {str(e)}")

import os
import re

@router.post("/obsidian/sync/{item_id}")
async def sync_to_obsidian(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    settings = db.query(Settings).first()
    if not settings or not settings.obsidian_rest_api_url or not settings.obsidian_api_key:
        raise HTTPException(status_code=400, detail="Obsidian settings are incomplete")
        
    if item.obsidian_path:
        # Already synced
        return {"status": "ok", "message": "Already synced", "obsidian_path": item.obsidian_path}

    # Construct Obsidian API request
    # Documentation typically follows Obsidian Local REST API format
    url_base = settings.obsidian_rest_api_url.rstrip('/')
    headers = {
        "Authorization": f"Bearer {settings.obsidian_api_key}",
        "Content-Type": "text/markdown"
    }
    
    # 1. Upload media files first (to 'EverythingCapture_Media' folder)
    media_references = {}
    media_folder_name = "EverythingCapture_Media"
    
    async with httpx.AsyncClient() as client:
        # We don't necessarily need to create the folder explicitly, but the REST plugin usually requires it
        # Try to create folder using POST /vault/foldername/
        folder_url = f"{url_base}/vault/{media_folder_name}/"
        try:
            await client.post(folder_url, headers={"Authorization": f"Bearer {settings.obsidian_api_key}"})
        except Exception:
            pass # Ignore if it exists
        
        for m in item.media:
            if m.local_path:
                local_file_path = os.path.join("static", m.local_path)
                if os.path.exists(local_file_path):
                    filename = os.path.basename(m.local_path)
                    vault_path = f"{media_folder_name}/{filename}"
                    try:
                        with open(local_file_path, "rb") as f:
                            file_data = f.read()
                        res = await client.post(
                            f"{url_base}/vault/{vault_path}", 
                            headers={"Authorization": f"Bearer {settings.obsidian_api_key}", "Content-Type": "application/octet-stream"},
                            content=file_data
                        )
                        if res.status_code in [200, 201, 204] or (res.status_code == 400 and "exists" in res.text):
                            media_references[m.original_url] = vault_path
                    except Exception as e:
                        logger.error(f"Failed to upload media to Obsidian: {e}")
                        
        # 2. Build Markdown payload
        # Ensure title is a safe filename
        safe_title = re.sub(r'[\\/:*?"<>|]', '_', item.title or f"Capture_{item.id}")[:100]
        note_path = f"{safe_title}.md"
        
        yaml_frontmatter = f"---\nsource: {item.source_url}\nplatform: {item.platform}\ndate: {item.created_at.isoformat()}\n---\n\n"
        
        markdown_body = f"# {item.title}\n\n"
        
        # If we have content_blocks_json, we can reconstruct the document order
        if item.content_blocks_json:
            import json as _json
            try:
                blocks = _json.loads(item.content_blocks_json)
                for block in blocks:
                    if block["type"] == "text" and block.get("content"):
                        markdown_body += block["content"] + "\n\n"
                    elif block["type"] == "image" and block.get("url"):
                        local_url = block["url"]
                        # We need to map static url back to vault url
                        # /static/media/item_id/filename.ext
                        filename = os.path.basename(local_url)
                        vault_path = f"{media_folder_name}/{filename}"
                        markdown_body += f"![[{vault_path}]]\n\n"
            except Exception:
                markdown_body += str(item.canonical_text) + "\n\n"
        else:
            # Fallback to text then append images
            markdown_body += str(item.canonical_text) + "\n\n"
            for vault_path in media_references.values():
                markdown_body += f"![[{vault_path}]]\n\n"
        
        full_content = yaml_frontmatter + markdown_body
        
        # 3. Upload Markdown note
        try:
            res = await client.post(
                f"{url_base}/vault/{note_path}",
                headers=headers,
                content=full_content.encode('utf-8')
            )
            if res.status_code not in [200, 201, 204] and (res.status_code != 400 or "exists" not in res.text):
                raise HTTPException(status_code=500, detail=f"Obsidian API error: {res.text}")
                
            item.obsidian_path = note_path
            db.commit()
            
            return {"status": "ok", "obsidian_path": note_path}
            
        except httpx.RequestError as e:
            logger.error(f"Network error to Obsidian API: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Network error connecting to Obsidian: {str(e)}")

