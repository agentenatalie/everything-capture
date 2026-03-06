from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Item, Settings
import httpx
import logging
from paths import STATIC_DIR
from pydantic import BaseModel, Field

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
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote

NOTION_VERSION = "2025-09-03"
NOTION_RICH_TEXT_LIMIT = 2000
NOTION_CHILDREN_LIMIT = 100
OBSIDIAN_MEDIA_FOLDER = "EverythingCapture_Media"

_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")


class SyncStatusRefreshRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)

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


def _notion_headers(token: str, *, json_body: bool = True) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _truncate_text(value: str | None, limit: int, fallback: str = "") -> str:
    text = (value or fallback or "").strip()
    return text[:limit] if text else fallback


def _split_rich_text_chunks(text: str, limit: int = NOTION_RICH_TEXT_LIMIT) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    return [normalized[i:i + limit] for i in range(0, len(normalized), limit)]


def _safe_note_name(title: str | None, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", (title or fallback).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or fallback)[:100]


def _encode_obsidian_vault_path(vault_path: str) -> str:
    return quote(vault_path, safe="/")


def _normalize_obsidian_folder_path(value: str | None) -> str | None:
    cleaned = _clean_optional_string(value)
    if not cleaned:
        return None
    return cleaned.strip("/").strip()


def _build_obsidian_note_path(item: Item, folder_path: str | None) -> str:
    note_name = f"{_safe_note_name(item.title, f'Capture_{item.id}')}-{item.id[:8]}.md"
    if folder_path:
        return f"{folder_path}/{note_name}"
    return note_name


def _persist_obsidian_url_base(settings: Settings | None, db: Session, url_base: str) -> None:
    if not settings:
        return
    normalized = _clean_optional_string(settings.obsidian_rest_api_url)
    if normalized == url_base:
        return
    settings.obsidian_rest_api_url = url_base
    db.commit()


def _load_content_blocks(item: Item) -> list[dict]:
    if not item.content_blocks_json:
        return []
    try:
        blocks = json.loads(item.content_blocks_json)
    except json.JSONDecodeError:
        logger.warning("Failed to decode content_blocks_json for item %s", item.id)
        return []
    return blocks if isinstance(blocks, list) else []


def _fallback_structured_blocks(item: Item) -> list[dict]:
    blocks: list[dict] = []

    for paragraph in re.split(r"\n{2,}", item.canonical_text or ""):
        text = paragraph.strip()
        if text:
            blocks.append({"type": "text", "content": text})

    for media in sorted(item.media, key=lambda entry: (entry.display_order, entry.original_url or "")):
        if media.type not in {"image", "cover", "video"}:
            continue
        media_url = f"/static/{media.local_path}" if media.local_path else media.original_url
        if not media_url:
            continue
        blocks.append({"type": media.type, "url": media_url})

    return blocks


def _get_structured_blocks(item: Item) -> list[dict]:
    blocks = _load_content_blocks(item)
    return blocks if blocks else _fallback_structured_blocks(item)


def _media_lookup(item: Item) -> dict[str, object]:
    lookup: dict[str, object] = {}
    for media in item.media:
        if media.local_path:
            lookup[f"/static/{media.local_path}"] = media
        if media.original_url:
            lookup[media.original_url] = media
    return lookup


def _collect_referenced_media(item: Item, blocks: list[dict]) -> list:
    lookup = _media_lookup(item)
    referenced = []
    seen_ids = set()

    for block in blocks:
        media = lookup.get(block.get("url", "")) if isinstance(block, dict) else None
        if not media or media.id in seen_ids:
            continue
        seen_ids.add(media.id)
        referenced.append(media)

    if referenced:
        return referenced

    return sorted(
        [media for media in item.media if media.type in {"image", "cover", "video"}],
        key=lambda entry: (entry.display_order, entry.original_url or ""),
    )


async def _notion_page_exists(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
) -> bool | None:
    response = await client.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=headers,
        timeout=20.0,
    )
    if response.status_code == 200:
        payload = response.json()
        return not bool(payload.get("archived") or payload.get("in_trash"))
    if response.status_code in {400, 404}:
        return False
    if response.status_code in {401, 403}:
        logger.warning("Cannot verify Notion page %s due to auth/access error: %s", page_id, response.text)
        return None
    logger.warning("Unexpected Notion page lookup response for %s: %s", page_id, response.text)
    return None


async def _append_notion_children(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
    children: list[dict],
) -> None:
    for start in range(0, len(children), NOTION_CHILDREN_LIMIT):
        batch = children[start:start + NOTION_CHILDREN_LIMIT]
        response = await client.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            json={"children": batch},
            timeout=30.0,
        )
        if response.status_code != 200:
            logger.error("Failed to append Notion children for %s: %s", page_id, response.text)
            raise HTTPException(
                status_code=500,
                detail=f"Notion block append failed: {response.text}",
            )


async def _upload_file_to_notion(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    file_path: Path,
    filename: str,
) -> str | None:
    if not file_path.exists():
        return None

    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    create_response = await client.post(
        "https://api.notion.com/v1/file_uploads",
        headers=auth_headers,
        json={
            "mode": "single_part",
            "filename": filename,
            "content_type": content_type,
        },
        timeout=30.0,
    )
    if create_response.status_code not in {200, 201}:
        logger.warning("Failed to create Notion file upload for %s: %s", filename, create_response.text)
        return None

    upload_id = create_response.json().get("id")
    if not upload_id:
        return None

    with open(file_path, "rb") as file_handle:
        send_response = await client.post(
            f"https://api.notion.com/v1/file_uploads/{upload_id}/send",
            headers={
                "Authorization": auth_headers["Authorization"],
                "Notion-Version": auth_headers["Notion-Version"],
            },
            files={"file": (filename, file_handle, content_type)},
            timeout=120.0,
        )
    if send_response.status_code not in {200, 201}:
        logger.warning("Failed to upload file bytes to Notion for %s: %s", filename, send_response.text)
        return None

    return upload_id


async def _build_notion_children(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    item: Item,
) -> list[dict]:
    structured_blocks = _get_structured_blocks(item)
    media_lookup = _media_lookup(item)
    notion_children: list[dict] = []
    upload_cache: dict[str, dict] = {}

    for block in structured_blocks:
        block_type = block.get("type")
        if block_type == "text":
            for chunk in _split_rich_text_chunks(block.get("content", "")):
                notion_children.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": chunk},
                                }
                            ]
                        },
                    }
                )
        elif block_type in {"image", "cover"}:
            block_url = block.get("url", "")
            media = media_lookup.get(block_url)
            image_payload = None

            if media and media.local_path:
                local_file_path = STATIC_DIR / media.local_path
                cache_key = media.local_path
                cached = upload_cache.get(cache_key)
                if cached:
                    image_payload = cached
                else:
                    upload_id = await _upload_file_to_notion(
                        client,
                        auth_headers,
                        local_file_path,
                        os.path.basename(media.local_path),
                    )
                    if upload_id:
                        image_payload = {
                            "type": "file_upload",
                            "file_upload": {"id": upload_id},
                        }
                        upload_cache[cache_key] = image_payload

            if not image_payload and media and media.original_url:
                image_payload = {
                    "type": "external",
                    "external": {"url": media.original_url},
                }
            elif not image_payload and block_url.startswith("http"):
                image_payload = {
                    "type": "external",
                    "external": {"url": block_url},
                }

            if image_payload:
                notion_children.append(
                    {
                        "object": "block",
                        "type": "image",
                        "image": image_payload,
                    }
                )
        elif block_type == "video":
            block_url = block.get("url", "")
            media = media_lookup.get(block_url)
            target_url = media.original_url if media and media.original_url else block_url
            if target_url:
                notion_children.append(
                    {
                        "object": "block",
                        "type": "bookmark",
                        "bookmark": {"url": target_url},
                    }
                )

    source_url = _clean_optional_string(item.source_url)
    if source_url:
        notion_children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Source: "}},
                        {
                            "type": "text",
                            "text": {
                                "content": source_url,
                                "link": {"url": source_url},
                            },
                        },
                    ]
                },
            }
        )

    return notion_children


def _obsidian_headers(api_key: str, content_type: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": content_type,
    }


async def _obsidian_note_exists(
    client: httpx.AsyncClient,
    url_base: str,
    api_key: str,
    vault_path: str,
) -> tuple[str, str | None]:
    response = await client.get(
        f"{url_base}/vault/{_encode_obsidian_vault_path(vault_path)}",
        headers=_obsidian_headers(api_key, "text/markdown"),
        timeout=20.0,
    )
    if 200 <= response.status_code < 300:
        return "exists", response.text
    if response.status_code == 404:
        return "missing", None
    if response.status_code in {401, 403}:
        logger.warning("Cannot verify Obsidian note %s due to auth/access error: %s", vault_path, response.text)
        return "unknown", None
    logger.warning("Unexpected Obsidian lookup response for %s: %s", vault_path, response.text)
    return "unknown", None


def _obsidian_note_matches_item(note_content: str, item: Item) -> bool:
    if f"item_id: {item.id}" in note_content:
        return True
    source_url = _clean_optional_string(item.source_url)
    if source_url and f"source: {source_url}" in note_content:
        return True
    return False


def _build_obsidian_note(item: Item, media_references: dict[str, str]) -> str:
    structured_blocks = _get_structured_blocks(item)
    yaml_frontmatter = (
        f"---\nitem_id: {item.id}\nsource: {item.source_url}\nplatform: {item.platform}\ndate: {item.created_at.isoformat()}\n---\n\n"
    )
    title = item.title or f"Capture {item.id}"
    parts = [yaml_frontmatter, f"# {title}\n\n"]

    for block in structured_blocks:
        block_type = block.get("type")
        if block_type == "text":
            content = (block.get("content") or "").strip()
            if content:
                parts.append(f"{content}\n\n")
        elif block_type in {"image", "cover"}:
            media_path = media_references.get(block.get("url", ""))
            if media_path:
                parts.append(f"![[{media_path}]]\n\n")
        elif block_type == "video":
            media_path = media_references.get(block.get("url", ""))
            if media_path:
                parts.append(f"![[{media_path}]]\n\n")

    if item.source_url:
        parts.append(f"[Source]({item.source_url})\n")

    return "".join(parts)

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
        "Notion-Version": NOTION_VERSION,
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
        **_notion_headers(notion_api_token),
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
    notion_headers = _notion_headers(notion_api_token)

    async with httpx.AsyncClient() as client:
        try:
            if item.notion_page_id:
                page_exists = await _notion_page_exists(client, notion_headers, item.notion_page_id)
                if page_exists:
                    return {"status": "ok", "message": "Already synced", "notion_page_id": item.notion_page_id}
                if page_exists is None:
                    return {"status": "ok", "message": "Unable to verify existing page", "notion_page_id": item.notion_page_id}
                if page_exists is False:
                    item.notion_page_id = None
                    db.commit()

            notion_target = None
            target_value = settings.notion_database_id if settings else None
            if target_value:
                try:
                    notion_target = await _resolve_notion_target(client, notion_headers, target_value)
                    if settings and notion_target.get("id") != _normalize_notion_id(target_value):
                        settings.notion_database_id = notion_target["id"]
                        db.commit()
                except HTTPException as exc:
                    if exc.status_code != 400:
                        raise
                    notion_target = await _discover_single_notion_target(client, notion_headers)
                    settings.notion_database_id = notion_target["id"]
                    db.commit()
            else:
                notion_target = await _discover_single_notion_target(client, notion_headers)
                settings.notion_database_id = notion_target["id"]
                db.commit()

            children = await _build_notion_children(client, notion_headers, item)
            first_batch = children[:NOTION_CHILDREN_LIMIT]
            remaining_children = children[NOTION_CHILDREN_LIMIT:]
            title_content = _truncate_text(item.title, NOTION_RICH_TEXT_LIMIT, "Untitled")

            if notion_target["object"] == "database":
                payload = {
                    "parent": { "type": "database_id", "database_id": notion_target["id"] },
                    "properties": {
                        notion_target["title_property_name"]: {
                            "title": [
                                {
                                    "text": {
                                        "content": title_content
                                    }
                                }
                            ]
                        }
                    },
                    "children": first_batch
                }
            else:
                payload = {
                    "parent": { "type": "page_id", "page_id": notion_target["id"] },
                    "properties": {
                        "title": {
                            "title": [
                                {
                                    "text": {
                                        "content": title_content
                                    }
                                }
                            ]
                        }
                    },
                    "children": first_batch
                }

            response = await client.post("https://api.notion.com/v1/pages", headers=notion_headers, json=payload, timeout=30.0)
            if response.status_code != 200:
                error_body = response.text
                logger.error(f"Notion API error: {error_body}")
                raise HTTPException(status_code=500, detail=f"Notion API returned {response.status_code}: {error_body}")
                
            data = response.json()
            page_id = data.get("id")

            if remaining_children:
                await _append_notion_children(client, notion_headers, page_id, remaining_children)
            
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

    url_bases = _obsidian_candidate_bases(settings.obsidian_rest_api_url)
    folder_path = _normalize_obsidian_folder_path(settings.obsidian_folder_path)
    note_path = _build_obsidian_note_path(item, folder_path)
    last_error = None
    for url_base in url_bases:
        async with httpx.AsyncClient(**_obsidian_client_kwargs(url_base)) as client:
            try:
                if item.obsidian_path:
                    note_state, note_content = await _obsidian_note_exists(client, url_base, settings.obsidian_api_key, item.obsidian_path)
                    if note_state == "exists" and note_content and _obsidian_note_matches_item(note_content, item):
                        _persist_obsidian_url_base(settings, db, url_base)
                        return {"status": "ok", "message": "Already synced", "obsidian_path": item.obsidian_path}
                    if note_state == "unknown":
                        return {"status": "ok", "message": "Unable to verify existing note", "obsidian_path": item.obsidian_path}
                    if note_state in {"missing", "exists"}:
                        item.obsidian_path = None
                        db.commit()
                structured_blocks = _get_structured_blocks(item)
                media_references: dict[str, str] = {}
                media_folder = f"{OBSIDIAN_MEDIA_FOLDER}/{item.id}"
                referenced_media = _collect_referenced_media(item, structured_blocks)

                for media in referenced_media:
                    if not media.local_path:
                        continue
                    local_file_path = STATIC_DIR / media.local_path
                    if not os.path.exists(local_file_path):
                        continue

                    filename = os.path.basename(media.local_path)
                    vault_path = f"{media_folder}/{filename}"
                    with open(local_file_path, "rb") as file_handle:
                        upload_response = await client.put(
                            f"{url_base}/vault/{_encode_obsidian_vault_path(vault_path)}",
                            headers=_obsidian_headers(settings.obsidian_api_key, "application/octet-stream"),
                            content=file_handle.read(),
                            timeout=120.0,
                        )
                    if upload_response.status_code not in [200, 201, 204]:
                        logger.error("Failed to upload media to Obsidian: %s", upload_response.text)
                        continue

                    if media.original_url:
                        media_references[media.original_url] = vault_path
                    media_references[f"/static/{media.local_path}"] = vault_path

                full_content = _build_obsidian_note(item, media_references)
                note_response = await client.put(
                    f"{url_base}/vault/{_encode_obsidian_vault_path(note_path)}",
                    headers=_obsidian_headers(settings.obsidian_api_key, "text/markdown; charset=utf-8"),
                    content=full_content.encode("utf-8"),
                    timeout=120.0,
                )
                if note_response.status_code not in [200, 201, 204]:
                    raise HTTPException(status_code=500, detail=f"Obsidian API error: {note_response.text}")

                item.obsidian_path = note_path
                _persist_obsidian_url_base(settings, db, url_base)
                db.commit()

                return {"status": "ok", "obsidian_path": note_path}
            except httpx.RequestError as e:
                last_error = e
                logger.error("Network error to Obsidian API via %s: %s", url_base, str(e))
                continue

    error_message = f"Network error connecting to Obsidian: {str(last_error)}" if last_error else "Network error connecting to Obsidian"
    raise HTTPException(status_code=500, detail=error_message)


@router.post("/sync-status/refresh")
async def refresh_sync_status(request: SyncStatusRefreshRequest, db: Session = Depends(get_db)):
    item_ids = [item_id for item_id in request.item_ids if item_id]
    if not item_ids:
        return {"items": []}

    items = db.query(Item).filter(Item.id.in_(item_ids)).all()
    if not items:
        return {"items": []}

    settings = db.query(Settings).first()
    notion_token = _clean_optional_string(settings.notion_api_token if settings else None)
    obsidian_url = _clean_optional_string(settings.obsidian_rest_api_url if settings else None)
    obsidian_api_key = _clean_optional_string(settings.obsidian_api_key if settings else None)

    notion_headers = _notion_headers(notion_token) if notion_token else None
    status_payload = []
    dirty = False

    async with httpx.AsyncClient() as notion_client:
        for item in items:
            if item.notion_page_id and notion_headers:
                try:
                    page_exists = await _notion_page_exists(notion_client, notion_headers, item.notion_page_id)
                    if page_exists is False:
                        item.notion_page_id = None
                        dirty = True
                except httpx.RequestError as exc:
                    logger.warning("Failed to refresh Notion sync status for %s: %s", item.id, exc)

            if item.obsidian_path and obsidian_url and obsidian_api_key:
                note_state = "unknown"
                note_content = None
                for url_base in _obsidian_candidate_bases(obsidian_url):
                    try:
                        async with httpx.AsyncClient(**_obsidian_client_kwargs(url_base)) as obsidian_client:
                            note_state, note_content = await _obsidian_note_exists(
                                obsidian_client,
                                url_base,
                                obsidian_api_key,
                                item.obsidian_path,
                            )
                    except httpx.RequestError as exc:
                        logger.warning("Failed to refresh Obsidian sync status for %s via %s: %s", item.id, url_base, exc)
                        continue

                    if note_state != "unknown":
                        break

                if note_state == "missing" or (note_state == "exists" and note_content and not _obsidian_note_matches_item(note_content, item)):
                    item.obsidian_path = None
                    dirty = True

            status_payload.append(
                {
                    "id": item.id,
                    "notion_page_id": item.notion_page_id,
                    "obsidian_path": item.obsidian_path,
                }
            )

    if dirty:
        db.commit()

    return {"items": status_payload}


@router.post("/obsidian/test")
async def test_obsidian_connection(db: Session = Depends(get_db)):
    settings = db.query(Settings).first()
    if not settings or not settings.obsidian_rest_api_url or not settings.obsidian_api_key:
        raise HTTPException(status_code=400, detail="Obsidian settings are incomplete")

    folder_path = _normalize_obsidian_folder_path(settings.obsidian_folder_path)
    probe_name = f"__everything_grabber_probe_{os.urandom(4).hex()}.md"
    probe_path = f"{folder_path}/{probe_name}" if folder_path else probe_name
    probe_body = (
        "---\n"
        "probe: everything-grabber\n"
        f"path: {probe_path}\n"
        "---\n\n"
        "Obsidian connectivity probe.\n"
    )

    last_error = None
    for url_base in _obsidian_candidate_bases(settings.obsidian_rest_api_url):
        async with httpx.AsyncClient(**_obsidian_client_kwargs(url_base)) as client:
            try:
                put_response = await client.put(
                    f"{url_base}/vault/{_encode_obsidian_vault_path(probe_path)}",
                    headers=_obsidian_headers(settings.obsidian_api_key, "text/markdown; charset=utf-8"),
                    content=probe_body.encode("utf-8"),
                    timeout=60.0,
                )
                if put_response.status_code not in [200, 201, 204]:
                    raise HTTPException(status_code=500, detail=f"Obsidian probe write failed: {put_response.text}")

                get_response = await client.get(
                    f"{url_base}/vault/{_encode_obsidian_vault_path(probe_path)}",
                    headers=_obsidian_headers(settings.obsidian_api_key, "text/markdown"),
                    timeout=60.0,
                )
                if get_response.status_code != 200 or "probe: everything-grabber" not in get_response.text:
                    raise HTTPException(status_code=500, detail="Obsidian probe read-back verification failed.")

                delete_response = await client.delete(
                    f"{url_base}/vault/{_encode_obsidian_vault_path(probe_path)}",
                    headers=_obsidian_headers(settings.obsidian_api_key, "text/markdown"),
                    timeout=60.0,
                )
                if delete_response.status_code not in [200, 204]:
                    raise HTTPException(status_code=500, detail=f"Obsidian probe cleanup failed: {delete_response.text}")

                _persist_obsidian_url_base(settings, db, url_base)
                return {
                    "status": "ok",
                    "url_base": url_base,
                    "vault_path": probe_path,
                    "target_folder": folder_path or "",
                    "write_location_hint": f"当前打开的 Obsidian Vault /{folder_path}" if folder_path else "当前打开的 Obsidian Vault 根目录",
                }
            except httpx.RequestError as exc:
                last_error = exc
                logger.warning("Obsidian probe failed via %s: %s", url_base, exc)
                continue

    error_message = f"Network error connecting to Obsidian: {last_error}" if last_error else "Network error connecting to Obsidian"
    raise HTTPException(status_code=500, detail=error_message)
