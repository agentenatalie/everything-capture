from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Item, Settings
import httpx
import logging
from paths import STATIC_DIR

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/connect",
    tags=["connect"]
)

from fastapi.responses import RedirectResponse
import base64
import urllib.parse
import re
import os
from urllib.parse import urlparse, urlunparse

_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")

def _clean_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None

def _normalize_notion_id(value: str | None) -> str | None:
    cleaned = _clean_optional_string(value)
    if not cleaned:
        return None

    match = _NOTION_ID_RE.search(cleaned)
    if not match:
        return None

    raw = match.group(1).replace("-", "")
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"

def _extract_notion_missing_fields(settings: Settings | None) -> list[str]:
    missing_fields = []
    if not settings or not _clean_optional_string(settings.notion_api_token):
        missing_fields.append("notion_api_token")
    if not _normalize_notion_id(settings.notion_database_id if settings else None):
        missing_fields.append("notion_database_id")
    return missing_fields

def _notion_title_plain_text(rich_text: list[dict]) -> str:
    title = "".join(
        fragment.get("plain_text")
        or fragment.get("text", {}).get("content", "")
        for fragment in rich_text
    ).strip()
    return title or "Untitled"

def _page_title_plain_text(page: dict) -> str:
    properties = page.get("properties") or {}
    for property_meta in properties.values():
        if property_meta.get("type") == "title":
            return _notion_title_plain_text(property_meta.get("title", []))
    return "Untitled"

def _database_target_from_payload(database: dict) -> dict:
    title_property_name = None
    for property_name, property_meta in database.get("properties", {}).items():
        if property_meta.get("type") == "title":
            title_property_name = property_name
            break
    if not title_property_name:
        raise HTTPException(status_code=500, detail="The configured Notion database has no title property.")
    return {
        "id": database.get("id"),
        "object": "database",
        "title": _notion_title_plain_text(database.get("title", [])),
        "title_property_name": title_property_name,
    }

async def _resolve_single_child_database_target(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
) -> dict | None:
    response = await client.get(
        f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100",
        headers=headers,
        timeout=20.0,
    )
    if response.status_code != 200:
        logger.warning("Failed to inspect Notion page children for %s: %s", page_id, response.text)
        return None

    child_database_blocks = [
        block
        for block in response.json().get("results", [])
        if block.get("type") == "child_database" and block.get("id")
    ]
    if len(child_database_blocks) != 1:
        return None

    child_database_id = child_database_blocks[0]["id"]
    database_response = await client.get(
        f"https://api.notion.com/v1/databases/{child_database_id}",
        headers=headers,
        timeout=20.0,
    )
    if database_response.status_code != 200:
        logger.warning(
            "Found child database block %s under page %s, but could not retrieve database: %s",
            child_database_id,
            page_id,
            database_response.text,
        )
        return None

    target = _database_target_from_payload(database_response.json())
    target["resolved_from_page_id"] = page_id
    return target

async def _fetch_notion_title_property_name(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    database_id: str,
) -> str:
    response = await client.get(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers=headers,
        timeout=20.0,
    )
    if response.status_code != 200:
        logger.error("Failed to fetch Notion database metadata: %s", response.text)
        raise HTTPException(
            status_code=400,
            detail="Unable to access the configured Notion database. Check the database ID/URL and integration access.",
        )

    database = response.json()
    for property_name, property_meta in database.get("properties", {}).items():
        if property_meta.get("type") == "title":
            return property_name

    raise HTTPException(status_code=500, detail="The configured Notion database has no title property.")

async def _search_notion_targets(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    databases_only: bool,
) -> list[dict]:
    payload = {"page_size": 50}
    if databases_only:
        payload["filter"] = {"property": "object", "value": "database"}

    response = await client.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json=payload,
        timeout=20.0,
    )
    if response.status_code != 200:
        logger.error("Failed to search Notion targets: %s", response.text)
        raise HTTPException(
            status_code=400,
            detail="Failed to fetch Notion targets. Make sure the integration can access the target page or database.",
        )

    results = []
    for result in response.json().get("results", []):
        object_type = result.get("object")
        if object_type not in {"database", "page"}:
            continue

        title = (
            _notion_title_plain_text(result.get("title", []))
            if object_type == "database"
            else _page_title_plain_text(result)
        )
        results.append(
            {
                "id": result.get("id"),
                "title": title,
                "url": result.get("url"),
                "object": object_type,
                "parent_type": (result.get("parent") or {}).get("type"),
            }
        )
    return results

async def _resolve_notion_target(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    target_value: str | None,
) -> dict:
    target_id = _normalize_notion_id(target_value)
    if not target_id:
        raise HTTPException(status_code=400, detail="No valid Notion sync target is configured.")

    db_response = await client.get(
        f"https://api.notion.com/v1/databases/{target_id}",
        headers=headers,
        timeout=20.0,
    )
    if db_response.status_code == 200:
        return _database_target_from_payload(db_response.json())

    page_response = await client.get(
        f"https://api.notion.com/v1/pages/{target_id}",
        headers=headers,
        timeout=20.0,
    )
    if page_response.status_code == 200:
        page = page_response.json()
        child_database_target = await _resolve_single_child_database_target(client, headers, target_id)
        if child_database_target:
            return child_database_target
        return {
            "id": target_id,
            "object": "page",
            "title": _page_title_plain_text(page),
        }

    logger.error(
        "Notion target resolution failed. database=%s page=%s",
        db_response.text,
        page_response.text,
    )
    raise HTTPException(
        status_code=400,
        detail="Unable to access the configured Notion target. Check the page/database URL and integration access.",
    )

async def _discover_single_notion_target(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> dict:
    databases = await _search_notion_targets(client, headers, databases_only=True)
    if len(databases) == 1:
        return await _resolve_notion_target(client, headers, databases[0]["id"])
    if len(databases) > 1:
        raise HTTPException(
            status_code=400,
            detail="Multiple Notion databases are available. Please choose one explicitly in Settings.",
        )

    all_targets = await _search_notion_targets(client, headers, databases_only=False)
    if len(all_targets) == 1:
        return await _resolve_notion_target(client, headers, all_targets[0]["id"])
    if not all_targets:
        raise HTTPException(
            status_code=400,
            detail="No accessible Notion page or database was found for this integration.",
        )
    root_pages = [
        target
        for target in all_targets
        if target.get("object") == "page" and target.get("parent_type") == "workspace"
    ]
    if len(root_pages) == 1:
        return await _resolve_notion_target(client, headers, root_pages[0]["id"])
    raise HTTPException(
        status_code=400,
        detail="Multiple Notion pages are accessible. Please choose a sync target explicitly in Settings.",
    )

def _obsidian_candidate_bases(url_base: str) -> list[str]:
    cleaned = url_base.rstrip("/")
    candidates = [cleaned]
    parsed = urlparse(cleaned)
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}:
        https_candidate = urlunparse(parsed._replace(scheme="https"))
        if https_candidate not in candidates:
            candidates.append(https_candidate)
    return candidates

def _obsidian_client_kwargs(url_base: str) -> dict:
    parsed = urlparse(url_base)
    verify = True
    if parsed.scheme == "https" and parsed.hostname in {"127.0.0.1", "localhost"}:
        verify = False
    return {"verify": verify}

@router.get("/notion/oauth/url")
async def get_notion_oauth_url(db: Session = Depends(get_db)):
    settings = db.query(Settings).first()
    notion_client_id = _clean_optional_string(settings.notion_client_id if settings else None)
    notion_redirect_uri = _clean_optional_string(settings.notion_redirect_uri if settings else None)
    if not notion_client_id or not notion_redirect_uri:
        raise HTTPException(status_code=400, detail="Notion Client ID or Redirect URI not configured in Settings.")
    
    encoded_redirect = urllib.parse.quote(notion_redirect_uri, safe='')
    auth_url = f"https://api.notion.com/v1/oauth/authorize?client_id={notion_client_id}&response_type=code&owner=user&redirect_uri={encoded_redirect}"
    return {"url": auth_url}

@router.get("/notion/oauth/callback")
async def notion_oauth_callback(code: str, error: str = None, db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(url=f"/?notion_auth=failed&error={urllib.parse.quote(error)}")
        
    settings = db.query(Settings).first()
    notion_client_id = _clean_optional_string(settings.notion_client_id if settings else None)
    notion_client_secret = _clean_optional_string(settings.notion_client_secret if settings else None)
    notion_redirect_uri = _clean_optional_string(settings.notion_redirect_uri if settings else None)
    if not notion_client_id or not notion_client_secret or not notion_redirect_uri:
        return RedirectResponse(url="/?notion_auth=failed&error=missing_config")

    # Exchange code for access token
    auth_string = f"{notion_client_id}:{notion_client_secret}"
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": notion_redirect_uri
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post("https://api.notion.com/v1/oauth/token", headers=headers, json=payload, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                settings.notion_api_token = data.get("access_token")
                db.commit()
                notion_redirect_state = "success" if _normalize_notion_id(settings.notion_database_id) else "partial"
                return RedirectResponse(url=f"/?notion_auth={notion_redirect_state}")
            else:
                logger.error(f"Notion OAuth token exchange failed: {response.text}")
                return RedirectResponse(url="/?notion_auth=failed&error=exchange_failed")
        except Exception as e:
            logger.error(f"Notion OAuth token exchange error: {str(e)}")
            return RedirectResponse(url="/?notion_auth=failed&error=network_error")

@router.get("/notion/databases")
async def list_notion_databases(db: Session = Depends(get_db)):
    settings = db.query(Settings).first()
    notion_api_token = _clean_optional_string(settings.notion_api_token if settings else None)
    if not notion_api_token:
        raise HTTPException(status_code=400, detail="Notion is not authenticated yet.")

    headers = {
        "Authorization": f"Bearer {notion_api_token}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    }
    async with httpx.AsyncClient() as client:
        try:
            results = await _search_notion_targets(client, headers, databases_only=True)
            if not results:
                results = await _search_notion_targets(client, headers, databases_only=False)
        except httpx.RequestError as exc:
            logger.error("Network error while listing Notion databases: %s", exc)
            raise HTTPException(status_code=500, detail=f"Network error connecting to Notion: {exc}") from exc

    results.sort(key=lambda entry: (entry["object"] != "database", entry["title"].lower()))
    return {"results": results}

@router.post("/notion/sync/{item_id}")
async def sync_to_notion(item_id: str, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
        
    settings = db.query(Settings).first()
    notion_api_token = _clean_optional_string(settings.notion_api_token if settings else None)
    if not notion_api_token:
        raise HTTPException(status_code=400, detail="Notion settings are incomplete: missing notion_api_token")
        
    if item.notion_page_id:
        # Already synced
        return {"status": "ok", "message": "Already synced", "notion_page_id": item.notion_page_id}

    # Construct Notion API request
    headers = {
        "Authorization": f"Bearer {notion_api_token}",
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

    async with httpx.AsyncClient() as client:
        try:
            notion_target = None
            target_value = settings.notion_database_id if settings else None
            if target_value:
                try:
                    notion_target = await _resolve_notion_target(client, headers, target_value)
                    if settings and notion_target.get("id") != _normalize_notion_id(target_value):
                        settings.notion_database_id = notion_target["id"]
                        db.commit()
                except HTTPException as exc:
                    if exc.status_code != 400:
                        raise
                    notion_target = await _discover_single_notion_target(client, headers)
                    settings.notion_database_id = notion_target["id"]
                    db.commit()
            else:
                notion_target = await _discover_single_notion_target(client, headers)
                settings.notion_database_id = notion_target["id"]
                db.commit()

            if notion_target["object"] == "database":
                payload = {
                    "parent": { "type": "database_id", "database_id": notion_target["id"] },
                    "properties": {
                        notion_target["title_property_name"]: {
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
            else:
                payload = {
                    "parent": { "type": "page_id", "page_id": notion_target["id"] },
                    "properties": {
                        "title": {
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
            
            return {
                "status": "ok",
                "notion_page_id": page_id,
                "target_id": notion_target["id"],
                "target_object": notion_target["object"],
                "target_title": notion_target.get("title"),
            }
            
        except httpx.RequestError as e:
            logger.error(f"Network error to Notion API: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Network error connecting to Notion: {str(e)}")

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
    url_bases = _obsidian_candidate_bases(settings.obsidian_rest_api_url)
    
    # 1. Upload media files first (to 'EverythingCapture_Media' folder)
    media_references = {}
    media_folder_name = "EverythingCapture_Media"
    last_error = None
    for url_base in url_bases:
        headers = {
            "Authorization": f"Bearer {settings.obsidian_api_key}",
            "Content-Type": "text/markdown"
        }

        async with httpx.AsyncClient(**_obsidian_client_kwargs(url_base)) as client:
            try:
                for m in item.media:
                    if m.local_path:
                        local_file_path = STATIC_DIR / m.local_path
                        if os.path.exists(local_file_path):
                            filename = os.path.basename(m.local_path)
                            vault_path = f"{media_folder_name}/{filename}"
                            try:
                                with open(local_file_path, "rb") as f:
                                    file_data = f.read()
                                res = await client.put(
                                    f"{url_base}/vault/{vault_path}",
                                    headers={"Authorization": f"Bearer {settings.obsidian_api_key}", "Content-Type": "application/octet-stream"},
                                    content=file_data
                                )
                                if res.status_code in [200, 201, 204]:
                                    media_references[m.original_url] = vault_path
                                else:
                                    logger.error("Failed to upload media to Obsidian: %s", res.text)
                            except Exception as e:
                                logger.error(f"Failed to upload media to Obsidian: {e}")
                                
                # 2. Build Markdown payload
                safe_title = re.sub(r'[\\/:*?"<>|]', '_', item.title or f"Capture_{item.id}")[:100]
                note_path = f"{safe_title}.md"
                
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
                                vault_path = f"{media_folder_name}/{filename}"
                                markdown_body += f"![[{vault_path}]]\n\n"
                    except Exception:
                        markdown_body += str(item.canonical_text) + "\n\n"
                else:
                    markdown_body += str(item.canonical_text) + "\n\n"
                    for vault_path in media_references.values():
                        markdown_body += f"![[{vault_path}]]\n\n"
                
                full_content = yaml_frontmatter + markdown_body
                
                # 3. Upload Markdown note
                res = await client.put(
                    f"{url_base}/vault/{note_path}",
                    headers=headers,
                    content=full_content.encode('utf-8')
                )
                if res.status_code not in [200, 201, 204]:
                    raise HTTPException(status_code=500, detail=f"Obsidian API error: {res.text}")
                    
                item.obsidian_path = note_path
                db.commit()
                
                return {"status": "ok", "obsidian_path": note_path}
            except httpx.RequestError as e:
                last_error = e
                logger.error("Network error to Obsidian API via %s: %s", url_base, str(e))
                continue

    error_message = f"Network error connecting to Obsidian: {str(last_error)}" if last_error else "Network error connecting to Obsidian"
    raise HTTPException(status_code=500, detail=error_message)
