from contextlib import AsyncExitStack
from time import monotonic

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from database import get_db
from frontend_bridge import build_frontend_url
from models import Item, Settings
import httpx
import logging
from paths import STATIC_DIR
from pydantic import BaseModel, Field
from security import decrypt_secret, encrypt_secret
from tenant import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/connect",
    tags=["connect"]
)

from fastapi.responses import RedirectResponse
import base64
import hashlib
import urllib.parse
import re
import os
import json
import mimetypes
from pathlib import Path
from urllib.parse import urlparse, urlunparse, quote
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup, NavigableString, Tag

NOTION_VERSION = "2025-09-03"
NOTION_RICH_TEXT_LIMIT = 2000
NOTION_CHILDREN_LIMIT = 100
OBSIDIAN_MEDIA_FOLDER = "EverythingCapture_Media"
DISPLAY_TIMEZONE = ZoneInfo("America/New_York")
SYNC_STATUS_CACHE_TTL_SECONDS = 300
SYNC_STATUS_CHECK_TIMEOUT_SECONDS = 4.0
NOTION_SYNC_PROPERTY_SPECS = {
    "Date": {"type": "rich_text", "rich_text": {}},
    "Source": {"type": "url", "url": {}},
    "Platform": {"type": "rich_text", "rich_text": {}},
    "Folder": {"type": "rich_text", "rich_text": {}},
}

_NOTION_ID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})")
_SYNC_TAG_TOKEN_PATTERN = r"#(?:[^\s#\[]+)(?:\[[^\]]+\])?#?"
_SYNC_TAG_ONLY_LINE_RE = re.compile(rf"^\s*(?:{_SYNC_TAG_TOKEN_PATTERN}\s*)+$")
_SYNC_TRAILING_TAGS_RE = re.compile(rf"(?:\s+|^)(?:{_SYNC_TAG_TOKEN_PATTERN}\s*)+$")
_SYNC_TEXT_BLOCK_TYPES = {
    "text",
    "paragraph",
    "heading_1",
    "heading_2",
    "heading_3",
    "bulleted_list_item",
    "numbered_list_item",
    "quote",
}
_SYNC_STATUS_CACHE: dict[str, dict[str, object]] = {}
_OBSIDIAN_APP_CONFIG_PATH = Path.home() / "Library/Application Support/obsidian/obsidian.json"


class SyncStatusRefreshRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)


class ObsidianTestRequest(BaseModel):
    obsidian_rest_api_url: str | None = None
    obsidian_api_key: str | None = None
    obsidian_folder_path: str | None = None


def _get_user_settings(db: Session, user_id: str) -> Settings | None:
    return db.query(Settings).filter(Settings.user_id == user_id).first()


def _get_user_item(db: Session, user_id: str, item_id: str) -> Item | None:
    return db.query(Item).filter(Item.user_id == user_id, Item.id == item_id).first()

def _clean_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_setting_secret(settings: Settings | None, field_name: str) -> str | None:
    if not settings:
        return None
    try:
        return _clean_optional_string(decrypt_secret(getattr(settings, field_name, None)))
    except ValueError as exc:
        logger.error("Stored secret %s could not be decrypted: %s", field_name, exc)
        raise HTTPException(status_code=500, detail=f"Stored secret {field_name} is unreadable") from exc


def _model_fields_set(model: BaseModel | None) -> set[str]:
    if model is None:
        return set()
    fields_set = getattr(model, "model_fields_set", None)
    if fields_set is not None:
        return set(fields_set)
    legacy_fields_set = getattr(model, "__fields_set__", None)
    return set(legacy_fields_set or set())


def _resolve_request_value(
    request_model: BaseModel | None,
    field_name: str,
    saved_value: str | None,
    *,
    normalizer=_clean_optional_string,
) -> str | None:
    if request_model is not None and field_name in _model_fields_set(request_model):
        return normalizer(getattr(request_model, field_name))
    return normalizer(saved_value)


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


def _format_item_datetime(value) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    localized = value.astimezone(DISPLAY_TIMEZONE)
    return localized.strftime("%m/%d %H:%M")


def _split_rich_text_chunks(text: str, limit: int = NOTION_RICH_TEXT_LIMIT) -> list[str]:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []
    return [normalized[i:i + limit] for i in range(0, len(normalized), limit)]


def _parsed_text_appendix(item: Item) -> str:
    text = (item.extracted_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    return text


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


def _open_obsidian_vault_roots() -> list[Path]:
    try:
        payload = json.loads(_OBSIDIAN_APP_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    roots: list[Path] = []
    for meta in (payload.get("vaults") or {}).values():
        if not isinstance(meta, dict) or not meta.get("open"):
            continue
        path = Path(str(meta.get("path") or "")).expanduser()
        if path.is_dir():
            roots.append(path)
    return roots


def _extract_obsidian_item_id_from_file(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for _ in range(20):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("item_id:"):
                    item_id = line.split(":", 1)[1].strip()
                    return item_id or None
    except OSError:
        return None
    return None


def _find_obsidian_notes_by_item_ids(folder_path: str | None, item_ids: set[str]) -> dict[str, str]:
    if not item_ids:
        return {}

    matches: dict[str, str] = {}
    for vault_root in _open_obsidian_vault_roots():
        base_path = vault_root / folder_path if folder_path else vault_root
        if not base_path.is_dir():
            continue
        for note_path in base_path.rglob("*.md"):
            item_id = _extract_obsidian_item_id_from_file(note_path)
            if not item_id or item_id not in item_ids or item_id in matches:
                continue
            try:
                matches[item_id] = note_path.relative_to(vault_root).as_posix()
            except ValueError:
                continue
            if len(matches) == len(item_ids):
                return matches
    return matches


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


def _normalize_media_url(src: str | None, base_url: str | None = None) -> str:
    if not src:
        return ""
    src = src.strip()
    if not src or src.startswith(("data:", "blob:")):
        return ""
    if src.startswith("/static/"):
        return src
    if src.startswith("//"):
        return f"https:{src}"
    if src.startswith("/") and base_url:
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{src}"
    if src.startswith("http") or src.startswith("/static/"):
        return src
    return ""


def _normalize_markdown_lines(text: str) -> str:
    if not text:
        return ""
    lines = []
    last_blank = False
    for raw_line in text.replace("\xa0", " ").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        line = re.sub(r"\s+([,.;:!?])", r"\1", line)
        if not line:
            if last_blank:
                continue
            lines.append("")
            last_blank = True
            continue
        lines.append(line)
        last_blank = False
    return "\n".join(lines).strip()


def _render_inline_markdown(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)

    if not isinstance(node, Tag):
        return ""

    tag_name = (node.name or "").lower()
    if tag_name == "br":
        return "\n"

    inner = "".join(_render_inline_markdown(child) for child in node.children)
    inner = _normalize_markdown_lines(inner) if "\n" in inner else re.sub(r"\s+", " ", inner.replace("\xa0", " ")).strip()

    if tag_name in {"strong", "b"}:
        return f"**{inner}**" if inner else ""
    if tag_name in {"em", "i"}:
        return f"*{inner}*" if inner else ""
    if tag_name == "code":
        code_text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        return f"`{code_text}`" if code_text else ""
    if tag_name == "a":
        href = _normalize_media_url(node.get("href")) or (node.get("href") or "").strip()
        label = inner or href
        return f"[{label}]({href})" if href and label else label

    return inner


def _text_block_payload(node: Tag) -> tuple[str, str]:
    plain = re.sub(r"\s+", " ", node.get_text(" ", strip=True).replace("\xa0", " ")).strip()
    plain = re.sub(r"\s+([,.;:!?])", r"\1", plain)
    markdown = _normalize_markdown_lines("".join(_render_inline_markdown(child) for child in node.children))
    return plain, markdown or plain


def _html_structured_blocks(item: Item) -> list[dict]:
    if not item.canonical_html:
        return []

    soup = BeautifulSoup(item.canonical_html, "html.parser")
    root = soup.body or soup
    blocks: list[dict] = []
    skip_tags = {"script", "style", "nav", "footer", "header", "noscript", "iframe", "form", "button"}
    block_tags = {
        "p", "h1", "h2", "h3", "h4", "h5", "h6",
        "blockquote", "pre", "ul", "ol", "figure", "img", "hr",
    }
    recursive_tags = {
        "div", "section", "article", "main", "figure", "picture",
        "a", "span", "header", "footer",
    }

    def append_text_block(block_type: str, content: str, markdown: str | None = None, **extra) -> None:
        content = (content or "").strip()
        if not content and block_type != "divider":
            return
        block = {"type": block_type, "content": content}
        if markdown:
            block["markdown"] = markdown.strip()
        block.update(extra)
        blocks.append(block)

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, NavigableString):
                continue
            if not isinstance(child, Tag):
                continue

            tag_name = (child.name or "").lower()
            if tag_name in skip_tags:
                continue

            if tag_name == "img":
                src = _normalize_media_url(
                    child.get("src") or child.get("data-src") or child.get("data-original"),
                    item.final_url or item.source_url,
                )
                if src:
                    blocks.append({"type": "image", "url": src})
                continue

            if tag_name == "figure":
                walk(child)
                continue

            if tag_name == "hr":
                blocks.append({"type": "divider"})
                continue

            if tag_name in {"ul", "ol"}:
                list_type = "numbered_list_item" if tag_name == "ol" else "bulleted_list_item"
                for li in child.find_all("li", recursive=False):
                    content, markdown = _text_block_payload(li)
                    append_text_block(list_type, content, markdown)
                continue

            if tag_name == "blockquote":
                content, markdown = _text_block_payload(child)
                append_text_block("quote", content, markdown)
                continue

            if tag_name == "pre":
                # Preserve the source code's original whitespace. GitHub wraps tokens
                # in many inline spans, so using a separator here would inject fake
                # newlines between every token and destroy readability.
                code_text = child.get_text("", strip=False).replace("\r\n", "\n").replace("\r", "\n").strip("\n")
                language = ""
                class_names = child.get("class") or []
                for class_name in class_names:
                    if class_name.startswith("language-"):
                        language = class_name.split("-", 1)[1]
                        break
                if code_text:
                    blocks.append({"type": "code", "content": code_text, "language": language})
                continue

            if tag_name in {"h1", "h2", "h3"}:
                content, markdown = _text_block_payload(child)
                append_text_block(tag_name.replace("h", "heading_"), content, markdown)
                continue

            if tag_name in {"h4", "h5", "h6"}:
                content, markdown = _text_block_payload(child)
                append_text_block("heading_3", content, markdown)
                continue

            if tag_name == "p":
                if child.find("img", recursive=True):
                    text_before = []
                    for grandchild in child.children:
                        if isinstance(grandchild, NavigableString):
                            inline_text = re.sub(r"\s+", " ", str(grandchild).replace("\xa0", " ")).strip()
                            if inline_text:
                                text_before.append(inline_text)
                            continue
                        if not isinstance(grandchild, Tag):
                            continue
                        if grandchild.name == "img" or grandchild.find("img", recursive=True):
                            if text_before:
                                text_content = " ".join(text_before).strip()
                                append_text_block("paragraph", text_content, text_content)
                                text_before.clear()
                            if grandchild.name == "img":
                                src = _normalize_media_url(
                                    grandchild.get("src") or grandchild.get("data-src") or grandchild.get("data-original"),
                                    item.final_url or item.source_url,
                                )
                                if src:
                                    blocks.append({"type": "image", "url": src})
                            else:
                                walk(grandchild)
                            continue
                        content, markdown = _text_block_payload(grandchild)
                        if content:
                            text_before.append(markdown or content)
                    if text_before:
                        text_content = " ".join(text_before).strip()
                        append_text_block("paragraph", text_content, text_content)
                    continue
                content, markdown = _text_block_payload(child)
                append_text_block("paragraph", content, markdown)
                continue

            if tag_name in recursive_tags:
                walk(child)
                continue

            if tag_name not in block_tags:
                if child.find(["img", "picture", "figure"], recursive=True):
                    walk(child)
                    continue
                if child.find(["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "ul", "ol"], recursive=False):
                    walk(child)
                    continue
                content, markdown = _text_block_payload(child)
                if content:
                    append_text_block("paragraph", content, markdown)

    walk(root)
    return [block for block in blocks if block.get("type") != "paragraph" or block.get("content")]


def _get_structured_blocks(item: Item) -> list[dict]:
    blocks = _load_content_blocks(item)
    html_blocks = _html_structured_blocks(item)
    if not blocks:
        return html_blocks if html_blocks else _fallback_structured_blocks(item)
    if not html_blocks:
        return blocks

    media_types = {"image", "video", "cover"}

    def summarize(candidate_blocks: list[dict]) -> dict[str, bool]:
        types = {str(block.get("type") or "") for block in candidate_blocks}
        non_empty_types = {block_type for block_type in types if block_type}
        return {
            "text_only": bool(non_empty_types) and non_empty_types.issubset({"text", "paragraph"}),
            "has_media": any(block.get("type") in media_types for block in candidate_blocks),
            "has_rich_structure": any(
                block.get("type") not in {"text", "paragraph", *media_types}
                for block in candidate_blocks
            ),
        }

    block_summary = summarize(blocks)
    html_summary = summarize(html_blocks)

    if block_summary["text_only"] and (html_summary["has_media"] or html_summary["has_rich_structure"]):
        return html_blocks
    if block_summary["has_media"] and not html_summary["has_media"]:
        return blocks
    if not block_summary["has_media"] and html_summary["has_media"]:
        return html_blocks
    if not block_summary["has_rich_structure"] and html_summary["has_rich_structure"]:
        return html_blocks
    return blocks


def _media_lookup(item: Item) -> dict[str, object]:
    lookup: dict[str, object] = {}
    for media in item.media:
        if media.local_path:
            lookup[f"/static/{media.local_path}"] = media
        if media.original_url:
            lookup[media.original_url] = media
    return lookup


def _ordered_item_folder_names(item: Item) -> list[str]:
    ordered_links = sorted(
        [
            link
            for link in (item.folder_links or [])
            if getattr(link, "folder", None) is not None and getattr(link.folder, "name", None)
        ],
        key=lambda link: (
            getattr(link, "created_at", None) or getattr(item, "created_at", None),
            (link.folder.name or "").lower(),
            link.folder_id,
        ),
    )
    if not ordered_links and item.folder and item.folder.name:
        return [item.folder.name]
    return [link.folder.name for link in ordered_links if link.folder and link.folder.name]


def _folder_property_text(item: Item) -> str:
    return ", ".join(_ordered_item_folder_names(item))


def _strip_sync_tags(text: str | None) -> str:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        return ""

    cleaned_lines: list[str] = []
    for raw_line in normalized.split("\n"):
        stripped_line = raw_line.strip()
        if not stripped_line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        if _SYNC_TAG_ONLY_LINE_RE.fullmatch(stripped_line):
            continue
        cleaned_line = _SYNC_TRAILING_TAGS_RE.sub("", raw_line).strip()
        if cleaned_line:
            cleaned_lines.append(cleaned_line)

    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()

    return "\n".join(cleaned_lines)


def _sync_blocks(item: Item) -> list[dict]:
    raw_blocks = _get_structured_blocks(item)
    has_douyin_video = item.platform == "douyin" and (
        any((block.get("type") or "") == "video" for block in raw_blocks)
        or any((media.type or "") == "video" for media in item.media)
    )

    prepared: list[dict] = []
    for block in raw_blocks:
        block_type = block.get("type")
        if has_douyin_video and block_type == "cover":
            continue

        updated_block = dict(block)
        if block_type in _SYNC_TEXT_BLOCK_TYPES:
            for field_name in ("content", "markdown"):
                field_value = updated_block.get(field_name)
                if isinstance(field_value, str):
                    cleaned_value = _strip_sync_tags(field_value)
                    if cleaned_value:
                        updated_block[field_name] = cleaned_value
                    else:
                        updated_block.pop(field_name, None)
            if not any(updated_block.get(field_name) for field_name in ("content", "markdown")):
                continue

        prepared.append(updated_block)

    return prepared


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
        [
            media
            for media in item.media
            if media.type in {"image", "cover", "video"}
            and not (
                item.platform == "douyin"
                and any((block.get("type") or "") == "video" for block in blocks)
                and media.type == "cover"
            )
        ],
        key=lambda entry: (entry.display_order, entry.original_url or ""),
    )


def _block_markdown(block: dict) -> str:
    block_type = block.get("type")
    content = (block.get("markdown") or block.get("content") or "").strip()

    if block_type in {"text", "paragraph"}:
        return content
    if block_type == "heading_1":
        return f"# {content}" if content else ""
    if block_type == "heading_2":
        return f"## {content}" if content else ""
    if block_type == "heading_3":
        return f"### {content}" if content else ""
    if block_type == "bulleted_list_item":
        return f"- {content}" if content else ""
    if block_type == "numbered_list_item":
        return f"1. {content}" if content else ""
    if block_type == "quote":
        return "\n".join(f"> {line}" if line else ">" for line in content.splitlines()) if content else ""
    if block_type == "code":
        language = (block.get("language") or "").strip()
        body = block.get("content") or ""
        return f"```{language}\n{body}\n```".strip()
    if block_type == "divider":
        return "---"
    return content


async def _notion_page_exists(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
    *,
    timeout: float = 20.0,
) -> bool | None:
    response = await client.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=headers,
        timeout=timeout,
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


async def _list_notion_child_block_ids(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    page_id: str,
) -> list[str]:
    block_ids: list[str] = []
    next_cursor = None
    while True:
        params = {"page_size": 100}
        if next_cursor:
            params["start_cursor"] = next_cursor
        response = await client.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            params=params,
            timeout=30.0,
        )
        if response.status_code != 200:
            logger.error("Failed to list Notion children for %s: %s", page_id, response.text)
            raise HTTPException(status_code=500, detail=f"Notion child listing failed: {response.text}")
        payload = response.json()
        block_ids.extend(
            block.get("id")
            for block in payload.get("results", [])
            if block.get("id")
        )
        if not payload.get("has_more"):
            return block_ids
        next_cursor = payload.get("next_cursor")


async def _archive_notion_blocks(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    block_ids: list[str],
) -> None:
    for block_id in block_ids:
        response = await client.patch(
            f"https://api.notion.com/v1/blocks/{block_id}",
            headers=headers,
            json={"archived": True},
            timeout=30.0,
        )
        if response.status_code != 200:
            logger.error("Failed to archive Notion block %s: %s", block_id, response.text)
            raise HTTPException(status_code=500, detail=f"Notion block archive failed: {response.text}")


def _page_title_property_name(page: dict) -> str:
    properties = page.get("properties") or {}
    for property_name, property_meta in properties.items():
        if property_meta.get("type") == "title":
            return property_name
    raise HTTPException(status_code=500, detail="The target Notion page has no title property.")


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
    structured_blocks = _sync_blocks(item)
    media_lookup = _media_lookup(item)
    notion_children: list[dict] = []
    upload_cache: dict[str, dict] = {}

    for block in structured_blocks:
        block_type = block.get("type")
        notion_text_type = {
            "text": "paragraph",
            "paragraph": "paragraph",
            "heading_1": "heading_1",
            "heading_2": "heading_2",
            "heading_3": "heading_3",
            "bulleted_list_item": "bulleted_list_item",
            "numbered_list_item": "numbered_list_item",
            "quote": "quote",
        }.get(block_type)

        if notion_text_type:
            for chunk in _split_rich_text_chunks(block.get("content", "")):
                notion_children.append(
                    {
                        "object": "block",
                        "type": notion_text_type,
                        notion_text_type: {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": chunk},
                                }
                            ]
                        },
                    }
                )
        elif block_type == "code":
            for chunk in _split_rich_text_chunks(block.get("content", "")):
                notion_children.append(
                    {
                        "object": "block",
                        "type": "code",
                        "code": {
                            "rich_text": [
                                {
                                    "type": "text",
                                    "text": {"content": chunk},
                                }
                            ],
                            "language": (block.get("language") or "plain text"),
                        },
                    }
                )
        elif block_type == "divider":
            notion_children.append(
                {
                    "object": "block",
                    "type": "divider",
                    "divider": {},
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

    parsed_text_appendix = _parsed_text_appendix(item)
    if parsed_text_appendix:
        notion_children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "'''"}},
                    ]
                },
            }
        )
        for chunk in _split_rich_text_chunks(item.extracted_text or ""):
            notion_children.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [
                            {"type": "text", "text": {"content": chunk}},
                        ],
                        "language": "plain text",
                    },
                }
            )
        notion_children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "'''"}},
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
    *,
    timeout: float = 20.0,
) -> tuple[str, str | None]:
    response = await client.get(
        f"{url_base}/vault/{_encode_obsidian_vault_path(vault_path)}",
        headers=_obsidian_headers(api_key, "text/markdown"),
        timeout=timeout,
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


def _normalize_obsidian_note_content(value: str | None) -> str:
    return (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


async def _resolve_obsidian_target_note(
    client: httpx.AsyncClient,
    url_base: str,
    api_key: str,
    item: Item,
    note_path: str,
    discovered_note_path: str | None = None,
) -> tuple[str, str | None, bool]:
    candidate_paths = list(
        dict.fromkeys(path for path in [item.obsidian_path or "", discovered_note_path or "", note_path] if path)
    )
    unknown_detected = False

    for candidate_path in candidate_paths:
        if not candidate_path:
            continue
        note_state, note_content = await _obsidian_note_exists(
            client,
            url_base,
            api_key,
            candidate_path,
        )
        if note_state == "unknown":
            unknown_detected = True
            continue
        if note_state == "exists" and note_content and _obsidian_note_matches_item(note_content, item):
            return candidate_path, note_content, False

    if unknown_detected:
        return item.obsidian_path or note_path, None, True
    return note_path, None, False


def _sync_status_cache_key(item: Item) -> str:
    return "|".join(
        [
            item.id or "",
            item.notion_page_id or "",
            item.obsidian_path or "",
            item.obsidian_last_synced_hash or "",
        ]
    )


def _get_cached_sync_status(item: Item) -> dict[str, str | None] | None:
    cache_key = _sync_status_cache_key(item)
    cached = _SYNC_STATUS_CACHE.get(cache_key)
    if not cached:
        return None

    checked_at = cached.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        _SYNC_STATUS_CACHE.pop(cache_key, None)
        return None

    if monotonic() - checked_at > SYNC_STATUS_CACHE_TTL_SECONDS:
        _SYNC_STATUS_CACHE.pop(cache_key, None)
        return None

    return {
        "id": item.id,
        "notion_page_id": cached.get("notion_page_id"),
        "obsidian_path": cached.get("obsidian_path"),
        "obsidian_sync_state": cached.get("obsidian_sync_state") or _obsidian_sync_state(item),
    }


def _store_sync_status_cache(item: Item) -> None:
    _SYNC_STATUS_CACHE[_sync_status_cache_key(item)] = {
        "checked_at": monotonic(),
        "notion_page_id": item.notion_page_id,
        "obsidian_path": item.obsidian_path,
        "obsidian_sync_state": _obsidian_sync_state(item),
    }


def _obsidian_media_references(item: Item) -> dict[str, str]:
    references: dict[str, str] = {}
    media_folder = f"{OBSIDIAN_MEDIA_FOLDER}/{item.id}"
    for media in item.media or []:
        if not media.local_path:
            continue
        filename = os.path.basename(media.local_path)
        vault_path = f"{media_folder}/{filename}"
        if media.original_url:
            references[media.original_url] = vault_path
        references[f"/static/{media.local_path}"] = vault_path
    return references


def _obsidian_note_hash(note_content: str) -> str:
    normalized = _normalize_obsidian_note_content(note_content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _current_obsidian_note_content(item: Item) -> str:
    return _build_obsidian_note(item, _obsidian_media_references(item))


def _current_obsidian_note_hash(item: Item) -> str:
    return _obsidian_note_hash(_current_obsidian_note_content(item))


def _obsidian_sync_state(item: Item) -> str:
    if not item.obsidian_path:
        return "idle"

    last_synced_hash = item.obsidian_last_synced_hash
    if last_synced_hash is None:
        return "ready"

    return "ready" if last_synced_hash == _current_obsidian_note_hash(item) else "partial"


def _build_obsidian_note(item: Item, media_references: dict[str, str]) -> str:
    structured_blocks = _sync_blocks(item)
    yaml_lines = [
        "---",
        f"item_id: {item.id}",
        f"source: {item.source_url}",
        f"platform: {item.platform}",
        f"date: {_format_item_datetime(item.created_at)}",
    ]
    folder_value = _folder_property_text(item)
    if folder_value:
        yaml_lines.append(f"folder: {json.dumps(folder_value, ensure_ascii=False)}")
    yaml_lines.append("---")
    yaml_frontmatter = "\n".join(yaml_lines) + "\n\n"
    title = item.title or f"Capture {item.id}"
    parts = [yaml_frontmatter, f"# {title}\n\n"]

    for index, block in enumerate(structured_blocks):
        block_type = block.get("type")
        next_block_type = structured_blocks[index + 1].get("type") if index + 1 < len(structured_blocks) else None
        if block_type in {
            "text",
            "paragraph",
            "heading_1",
            "heading_2",
            "heading_3",
            "bulleted_list_item",
            "numbered_list_item",
            "quote",
            "code",
            "divider",
        }:
            content = _block_markdown(block)
            if content:
                separator = "\n" if next_block_type == block_type and block_type in {"bulleted_list_item", "numbered_list_item"} else "\n\n"
                parts.append(f"{content}{separator}")
        elif block_type in {"image", "cover"}:
            media_path = media_references.get(block.get("url", ""))
            if media_path:
                parts.append(f"![[{media_path}]]\n\n")
        elif block_type == "video":
            media_path = media_references.get(block.get("url", ""))
            if media_path:
                parts.append(f"![[{media_path}]]\n\n")

    parsed_text_appendix = _parsed_text_appendix(item)
    if parsed_text_appendix:
        parts.append("\n" if not parts[-1].endswith("\n") else "")
        parts.append("```text\n")
        parts.append(parsed_text_appendix)
        parts.append("\n```\n")

    if item.source_url:
        parts.append(f"[Source]({item.source_url})\n")

    return "".join(parts)

def _extract_notion_missing_fields(settings: Settings | None) -> list[str]:
    missing_fields = []
    if not _get_setting_secret(settings, "notion_api_token"):
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


def _data_source_target_from_payload(data_source: dict) -> dict:
    title_property_name = None
    for property_name, property_meta in data_source.get("properties", {}).items():
        if property_meta.get("type") == "title":
            title_property_name = property_name
            break
    if not title_property_name:
        raise HTTPException(status_code=500, detail="The configured Notion data source has no title property.")
    return {
        "id": data_source.get("id"),
        "object": "data_source",
        "title": _notion_title_plain_text(data_source.get("title", [])),
        "title_property_name": title_property_name,
        "database_id": (data_source.get("parent") or {}).get("database_id"),
        "properties": data_source.get("properties", {}),
    }


async def _ensure_notion_sync_properties(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    notion_target: dict,
) -> dict:
    if notion_target.get("object") != "data_source":
        return notion_target

    existing_properties = notion_target.get("properties") or {}
    properties_to_add = {
        name: schema
        for name, schema in NOTION_SYNC_PROPERTY_SPECS.items()
        if name not in existing_properties
    }

    if properties_to_add:
        response = await client.patch(
            f"https://api.notion.com/v1/data_sources/{notion_target['id']}",
            headers=headers,
            json={"properties": properties_to_add},
            timeout=30.0,
        )
        if response.status_code != 200:
            logger.error("Failed to ensure Notion sync properties for %s: %s", notion_target["id"], response.text)
            raise HTTPException(status_code=500, detail=f"Notion data source update failed: {response.text}")
        notion_target = _data_source_target_from_payload(response.json())

    notion_target["sync_property_names"] = {
        "date": "Date",
        "source": "Source",
        "platform": "Platform",
        "folder": "Folder",
    }
    return notion_target


def _build_notion_page_properties(item: Item, notion_target: dict) -> dict:
    properties = {
        notion_target["title_property_name"]: {
            "title": [
                {
                    "text": {
                        "content": _truncate_text(item.title, NOTION_RICH_TEXT_LIMIT, "Untitled")
                    }
                }
            ]
        }
    }

    sync_property_names = notion_target.get("sync_property_names") or {}
    if sync_property_names.get("date"):
        properties[sync_property_names["date"]] = {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": _format_item_datetime(item.created_at)},
                }
            ]
        }
    if sync_property_names.get("source"):
        properties[sync_property_names["source"]] = {
            "url": _clean_optional_string(item.source_url)
        }
    if sync_property_names.get("platform"):
        properties[sync_property_names["platform"]] = {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": _truncate_text(item.platform, NOTION_RICH_TEXT_LIMIT, "")},
                }
            ]
        }
    if sync_property_names.get("folder"):
        properties[sync_property_names["folder"]] = {
            "rich_text": [
                {
                    "type": "text",
                    "text": {"content": _truncate_text(_folder_property_text(item), NOTION_RICH_TEXT_LIMIT, "")},
                }
            ]
        }

    return properties

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


async def _resolve_single_data_source_target(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    database_id: str,
) -> dict | None:
    response = await client.get(
        f"https://api.notion.com/v1/databases/{database_id}",
        headers=headers,
        timeout=20.0,
    )
    if response.status_code != 200:
        logger.warning("Failed to inspect Notion database %s for data sources: %s", database_id, response.text)
        return None

    data_sources = response.json().get("data_sources", [])
    if len(data_sources) != 1:
        return None

    data_source_id = data_sources[0].get("id")
    if not data_source_id:
        return None

    data_source_response = await client.get(
        f"https://api.notion.com/v1/data_sources/{data_source_id}",
        headers=headers,
        timeout=20.0,
    )
    if data_source_response.status_code != 200:
        logger.warning("Failed to retrieve Notion data source %s: %s", data_source_id, data_source_response.text)
        return None

    return _data_source_target_from_payload(data_source_response.json())

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
        payload["filter"] = {"property": "object", "value": "data_source"}

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
        if object_type not in {"database", "page", "data_source"}:
            continue

        title = (
            _notion_title_plain_text(result.get("title", []))
            if object_type in {"database", "data_source"}
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
        database_payload = db_response.json()
        if database_payload.get("properties"):
            return _database_target_from_payload(database_payload)
        data_source_target = await _resolve_single_data_source_target(client, headers, target_id)
        if data_source_target:
            return data_source_target
        raise HTTPException(status_code=500, detail="The configured Notion database has no directly writable title property.")

    data_source_response = await client.get(
        f"https://api.notion.com/v1/data_sources/{target_id}",
        headers=headers,
        timeout=20.0,
    )
    if data_source_response.status_code == 200:
        return _data_source_target_from_payload(data_source_response.json())

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
        "Notion target resolution failed. database=%s data_source=%s page=%s",
        db_response.text,
        data_source_response.text,
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
    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    notion_client_id = _clean_optional_string(settings.notion_client_id if settings else None)
    notion_redirect_uri = _clean_optional_string(settings.notion_redirect_uri if settings else None)
    if not notion_client_id or not notion_redirect_uri:
        raise HTTPException(status_code=400, detail="Notion Client ID or Redirect URI not configured in Settings.")
    
    encoded_redirect = urllib.parse.quote(notion_redirect_uri, safe='')
    auth_url = f"https://api.notion.com/v1/oauth/authorize?client_id={notion_client_id}&response_type=code&owner=user&redirect_uri={encoded_redirect}"
    return {"url": auth_url}

@router.get("/notion/oauth/callback")
async def notion_oauth_callback(request: Request, code: str, error: str = None, db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(
            url=build_frontend_url(
                request,
                query_params={"notion_auth": "failed", "error": error},
            )
        )
        
    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    if not settings:
        settings = Settings(user_id=user_id)
        db.add(settings)
        db.flush()
    notion_client_id = _clean_optional_string(settings.notion_client_id if settings else None)
    notion_client_secret = _get_setting_secret(settings, "notion_client_secret")
    notion_redirect_uri = _clean_optional_string(settings.notion_redirect_uri if settings else None)
    if not notion_client_id or not notion_client_secret or not notion_redirect_uri:
        return RedirectResponse(
            url=build_frontend_url(
                request,
                query_params={"notion_auth": "failed", "error": "missing_config"},
            )
        )

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
                settings.notion_api_token = encrypt_secret(data.get("access_token"))
                db.commit()
                notion_redirect_state = "success" if _normalize_notion_id(settings.notion_database_id) else "partial"
                return RedirectResponse(
                    url=build_frontend_url(
                        request,
                        query_params={"notion_auth": notion_redirect_state},
                    )
                )
            else:
                logger.error(f"Notion OAuth token exchange failed: {response.text}")
                return RedirectResponse(
                    url=build_frontend_url(
                        request,
                        query_params={"notion_auth": "failed", "error": "exchange_failed"},
                    )
                )
        except Exception as e:
            logger.error(f"Notion OAuth token exchange error: {str(e)}")
            return RedirectResponse(
                url=build_frontend_url(
                    request,
                    query_params={"notion_auth": "failed", "error": "network_error"},
                )
            )

@router.get("/notion/databases")
async def list_notion_databases(db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    notion_api_token = _get_setting_secret(settings, "notion_api_token")
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

async def _sync_item_to_notion(item: Item, db: Session, *, settings: Settings | None = None):
    settings = settings or _get_user_settings(db, item.user_id)
    notion_api_token = _get_setting_secret(settings, "notion_api_token")
    if not notion_api_token:
        raise HTTPException(status_code=400, detail="Notion settings are incomplete: missing notion_api_token")
    notion_headers = _notion_headers(notion_api_token)
    existing_page_id = None

    async with httpx.AsyncClient() as client:
        try:
            if item.notion_page_id:
                page_exists = await _notion_page_exists(client, notion_headers, item.notion_page_id)
                if page_exists:
                    existing_page_id = item.notion_page_id
                    item.notion_page_id = None
                    db.commit()
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

            notion_target = await _ensure_notion_sync_properties(client, notion_headers, notion_target)
            children = await _build_notion_children(client, notion_headers, item)
            first_batch = children[:NOTION_CHILDREN_LIMIT]
            remaining_children = children[NOTION_CHILDREN_LIMIT:]

            if notion_target["object"] in {"database", "data_source"}:
                parent_type = "database_id" if notion_target["object"] == "database" else "data_source_id"
                payload = {
                    "parent": { "type": parent_type, parent_type: notion_target["id"] },
                    "properties": _build_notion_page_properties(item, notion_target),
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
                                        "content": _truncate_text(item.title, NOTION_RICH_TEXT_LIMIT, "Untitled")
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

            if existing_page_id:
                archive_response = await client.patch(
                    f"https://api.notion.com/v1/pages/{existing_page_id}",
                    headers=notion_headers,
                    json={"archived": True},
                    timeout=30.0,
                )
                if archive_response.status_code != 200:
                    logger.warning("Failed to archive previous Notion page %s: %s", existing_page_id, archive_response.text)
            
            return {
                "status": "ok",
                "notion_page_id": page_id,
                "target_id": notion_target["id"],
                "target_object": notion_target["object"],
                "target_title": notion_target.get("title"),
                "replaced_page_id": existing_page_id,
            }
            
        except httpx.RequestError as e:
            logger.error(f"Network error to Notion API: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Network error connecting to Notion: {str(e)}")

@router.post("/notion/sync/{item_id}")
async def sync_to_notion(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = _get_user_item(db, user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return await _sync_item_to_notion(item, db)


async def _sync_item_to_obsidian(
    item: Item,
    db: Session,
    *,
    settings: Settings | None = None,
    discovered_note_path: str | None = None,
):
    settings = settings or _get_user_settings(db, item.user_id)
    obsidian_rest_api_url = _clean_optional_string(settings.obsidian_rest_api_url if settings else None)
    obsidian_api_key = _get_setting_secret(settings, "obsidian_api_key")
    if not settings or not obsidian_rest_api_url or not obsidian_api_key:
        raise HTTPException(status_code=400, detail="Obsidian settings are incomplete")

    url_bases = _obsidian_candidate_bases(obsidian_rest_api_url)
    folder_path = _normalize_obsidian_folder_path(settings.obsidian_folder_path)
    note_path = _build_obsidian_note_path(item, folder_path)
    discovered_note_path = discovered_note_path or _find_obsidian_notes_by_item_ids(folder_path, {item.id}).get(item.id)
    last_error = None
    for url_base in url_bases:
        async with httpx.AsyncClient(**_obsidian_client_kwargs(url_base)) as client:
            try:
                structured_blocks = _sync_blocks(item)
                media_references: dict[str, str] = {}
                media_folder = f"{OBSIDIAN_MEDIA_FOLDER}/{item.id}"
                referenced_media = _collect_referenced_media(item, structured_blocks)
                target_note_path, existing_note_content, verification_unknown = await _resolve_obsidian_target_note(
                    client,
                    url_base,
                    obsidian_api_key,
                    item,
                    note_path,
                    discovered_note_path=discovered_note_path,
                )
                if verification_unknown:
                    return {
                        "status": "ok",
                        "message": "Unable to verify existing note",
                        "obsidian_path": item.obsidian_path or target_note_path,
                        "obsidian_sync_state": _obsidian_sync_state(item),
                    }

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
                            headers=_obsidian_headers(obsidian_api_key, "application/octet-stream"),
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
                current_note_hash = _obsidian_note_hash(full_content)

                note_updated = True
                if _normalize_obsidian_note_content(existing_note_content) != _normalize_obsidian_note_content(full_content):
                    note_response = await client.put(
                        f"{url_base}/vault/{_encode_obsidian_vault_path(target_note_path)}",
                        headers=_obsidian_headers(obsidian_api_key, "text/markdown; charset=utf-8"),
                        content=full_content.encode("utf-8"),
                        timeout=120.0,
                    )
                    if note_response.status_code not in [200, 201, 204]:
                        raise HTTPException(status_code=500, detail=f"Obsidian API error: {note_response.text}")
                else:
                    note_updated = False

                item.obsidian_path = target_note_path
                item.obsidian_last_synced_hash = current_note_hash
                item.obsidian_last_synced_at = datetime.utcnow()
                _persist_obsidian_url_base(settings, db, url_base)
                db.commit()

                return {
                    "status": "ok",
                    "obsidian_path": target_note_path,
                    "obsidian_sync_state": "ready",
                    "updated": note_updated,
                    "unchanged": not note_updated,
                }
            except httpx.RequestError as e:
                last_error = e
                logger.error("Network error to Obsidian API via %s: %s", url_base, str(e))
                continue

    error_message = f"Network error connecting to Obsidian: {str(last_error)}" if last_error else "Network error connecting to Obsidian"
    raise HTTPException(status_code=500, detail=error_message)


@router.post("/obsidian/sync/{item_id}")
async def sync_to_obsidian(item_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item = _get_user_item(db, user_id, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return await _sync_item_to_obsidian(item, db)


@router.post("/notion/sync-all")
async def sync_all_to_notion(db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    items = (
        db.query(Item)
        .filter(Item.user_id == user_id)
        .order_by(Item.created_at.desc())
        .all()
    )

    pending_items = [item for item in items if not item.notion_page_id]
    skipped_count = len(items) - len(pending_items)
    synced_items: list[dict[str, str]] = []
    failed_items: list[dict[str, str]] = []

    for item in pending_items:
        try:
            result = await _sync_item_to_notion(item, db, settings=settings)
            synced_items.append(
                {
                    "id": item.id,
                    "notion_page_id": result.get("notion_page_id") or "",
                }
            )
        except HTTPException as exc:
            failed_items.append(
                {
                    "id": item.id,
                    "message": str(exc.detail),
                }
            )

    return {
        "status": "ok",
        "target": "notion",
        "total_count": len(items),
        "attempted_count": len(pending_items),
        "synced_count": len(synced_items),
        "skipped_count": skipped_count,
        "failed_count": len(failed_items),
        "items": synced_items,
        "errors": failed_items[:10],
    }


@router.post("/obsidian/sync-all")
async def sync_all_to_obsidian(db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    items = (
        db.query(Item)
        .filter(Item.user_id == user_id)
        .order_by(Item.created_at.desc())
        .all()
    )

    folder_path = _normalize_obsidian_folder_path(settings.obsidian_folder_path if settings else None)
    discovered_note_paths = _find_obsidian_notes_by_item_ids(folder_path, {item.id for item in items})
    pending_items = items
    skipped_count = 0
    synced_items: list[dict[str, str]] = []
    failed_items: list[dict[str, str]] = []

    for item in pending_items:
        try:
            result = await _sync_item_to_obsidian(
                item,
                db,
                settings=settings,
                discovered_note_path=discovered_note_paths.get(item.id),
            )
        except HTTPException as exc:
            detail = str(exc.detail)
            if "Network error connecting to Obsidian" in detail:
                try:
                    result = await _sync_item_to_obsidian(
                        item,
                        db,
                        settings=settings,
                        discovered_note_path=discovered_note_paths.get(item.id),
                    )
                except HTTPException as retry_exc:
                    failed_items.append(
                        {
                            "id": item.id,
                            "message": str(retry_exc.detail),
                        }
                    )
                    continue
            else:
                failed_items.append(
                    {
                        "id": item.id,
                        "message": detail,
                    }
                )
                continue

        try:
            if result.get("unchanged"):
                skipped_count += 1
            else:
                synced_items.append(
                    {
                        "id": item.id,
                        "obsidian_path": result.get("obsidian_path") or "",
                    }
                )
        except Exception as exc:
            failed_items.append(
                {
                    "id": item.id,
                    "message": str(exc),
                }
            )

    return {
        "status": "ok",
        "target": "obsidian",
        "total_count": len(items),
        "attempted_count": len(pending_items),
        "synced_count": len(synced_items),
        "skipped_count": skipped_count,
        "failed_count": len(failed_items),
        "items": synced_items,
        "errors": failed_items[:10],
    }


@router.post("/sync-status/refresh")
async def refresh_sync_status(request: SyncStatusRefreshRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    item_ids = [item_id for item_id in request.item_ids if item_id]
    if not item_ids:
        return {"items": []}

    items = db.query(Item).filter(Item.user_id == user_id, Item.id.in_(item_ids)).all()
    if not items:
        return {"items": []}

    settings = _get_user_settings(db, user_id)
    notion_token = _get_setting_secret(settings, "notion_api_token")
    obsidian_url = _clean_optional_string(settings.obsidian_rest_api_url if settings else None)
    obsidian_api_key = _get_setting_secret(settings, "obsidian_api_key")

    notion_headers = _notion_headers(notion_token) if notion_token else None
    status_payload = []
    dirty = False
    folder_path = _normalize_obsidian_folder_path(settings.obsidian_folder_path if settings else None)
    for item in items:
        _SYNC_STATUS_CACHE.pop(_sync_status_cache_key(item), None)

    if items:
        obsidian_bases = _obsidian_candidate_bases(obsidian_url) if obsidian_url and obsidian_api_key else []
        discovered_note_paths = _find_obsidian_notes_by_item_ids(folder_path, {item.id for item in items})

        async with AsyncExitStack() as stack:
            notion_client = await stack.enter_async_context(httpx.AsyncClient()) if notion_headers else None
            obsidian_clients = {
                url_base: await stack.enter_async_context(httpx.AsyncClient(**_obsidian_client_kwargs(url_base)))
                for url_base in obsidian_bases
            }

            for item in items:
                if item.notion_page_id and notion_headers and notion_client is not None:
                    try:
                        page_exists = await _notion_page_exists(
                            notion_client,
                            notion_headers,
                            item.notion_page_id,
                            timeout=SYNC_STATUS_CHECK_TIMEOUT_SECONDS,
                        )
                        if page_exists is False:
                            item.notion_page_id = None
                            dirty = True
                    except httpx.RequestError as exc:
                        logger.warning("Failed to refresh Notion sync status for %s: %s", item.id, exc)

                if obsidian_api_key and obsidian_clients:
                    note_path = _build_obsidian_note_path(item, folder_path)
                    resolved_obsidian_path = item.obsidian_path
                    matched_note_content = None
                    verification_unknown = False
                    verified_obsidian_status = False
                    obsidian_request_failed = False
                    obsidian_binding_missing = False
                    for url_base, obsidian_client in obsidian_clients.items():
                        try:
                            resolved_obsidian_path, matched_note_content, verification_unknown = await _resolve_obsidian_target_note(
                                obsidian_client,
                                url_base,
                                obsidian_api_key,
                                item,
                                note_path,
                                discovered_note_path=discovered_note_paths.get(item.id),
                            )
                            verified_obsidian_status = True
                        except httpx.RequestError as exc:
                            obsidian_request_failed = True
                            logger.warning("Failed to refresh Obsidian sync status for %s via %s: %s", item.id, url_base, exc)
                            continue

                        if verification_unknown or matched_note_content is not None:
                            break

                    if verification_unknown or (obsidian_request_failed and not verified_obsidian_status):
                        pass
                    elif matched_note_content is not None:
                        if item.obsidian_path != resolved_obsidian_path:
                            item.obsidian_path = resolved_obsidian_path
                            dirty = True
                        current_note_hash = _current_obsidian_note_hash(item)
                        remote_note_hash = _obsidian_note_hash(matched_note_content)
                        if remote_note_hash == current_note_hash:
                            if item.obsidian_last_synced_hash != current_note_hash:
                                item.obsidian_last_synced_hash = current_note_hash
                                dirty = True
                            if item.obsidian_last_synced_at is None:
                                item.obsidian_last_synced_at = datetime.utcnow()
                                dirty = True
                        elif item.obsidian_last_synced_hash != "":
                            item.obsidian_last_synced_hash = ""
                            item.obsidian_last_synced_at = None
                            dirty = True
                    elif item.obsidian_path:
                        item.obsidian_path = None
                        item.obsidian_last_synced_hash = None
                        item.obsidian_last_synced_at = None
                        obsidian_binding_missing = True
                        dirty = True

                _store_sync_status_cache(item)
                status_payload.append(
                    {
                        "id": item.id,
                        "notion_page_id": item.notion_page_id,
                        "obsidian_path": item.obsidian_path,
                        "obsidian_sync_state": _obsidian_sync_state(item),
                        "obsidian_binding_missing": obsidian_binding_missing if obsidian_api_key and obsidian_clients else False,
                    }
                )

    if dirty:
        db.commit()

    status_lookup = {entry["id"]: entry for entry in status_payload}
    ordered_status_payload = [status_lookup[item_id] for item_id in item_ids if item_id in status_lookup]
    return {"items": ordered_status_payload}


@router.post("/obsidian/test")
async def test_obsidian_connection(
    request: ObsidianTestRequest | None = None,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    settings = _get_user_settings(db, user_id)
    obsidian_rest_api_url = _resolve_request_value(
        request,
        "obsidian_rest_api_url",
        settings.obsidian_rest_api_url if settings else None,
    )
    obsidian_api_key = _resolve_request_value(
        request,
        "obsidian_api_key",
        _get_setting_secret(settings, "obsidian_api_key"),
    )
    folder_path = _normalize_obsidian_folder_path(
        _resolve_request_value(
            request,
            "obsidian_folder_path",
            settings.obsidian_folder_path if settings else None,
            normalizer=lambda value: value.strip() if isinstance(value, str) else value,
        )
    )
    used_saved_url_base = request is None or "obsidian_rest_api_url" not in _model_fields_set(request)

    if not obsidian_rest_api_url or not obsidian_api_key:
        raise HTTPException(status_code=400, detail="Obsidian settings are incomplete")

    probe_name = f"__everything_capture_probe_{os.urandom(4).hex()}.md"
    probe_path = f"{folder_path}/{probe_name}" if folder_path else probe_name
    probe_body = (
        "---\n"
        "probe: everything-capture\n"
        f"path: {probe_path}\n"
        "---\n\n"
        "Obsidian connectivity probe.\n"
    )

    last_error = None
    for url_base in _obsidian_candidate_bases(obsidian_rest_api_url):
        async with httpx.AsyncClient(**_obsidian_client_kwargs(url_base)) as client:
            try:
                put_response = await client.put(
                    f"{url_base}/vault/{_encode_obsidian_vault_path(probe_path)}",
                    headers=_obsidian_headers(obsidian_api_key, "text/markdown; charset=utf-8"),
                    content=probe_body.encode("utf-8"),
                    timeout=60.0,
                )
                if put_response.status_code not in [200, 201, 204]:
                    raise HTTPException(status_code=500, detail=f"Obsidian probe write failed: {put_response.text}")

                get_response = await client.get(
                    f"{url_base}/vault/{_encode_obsidian_vault_path(probe_path)}",
                    headers=_obsidian_headers(obsidian_api_key, "text/markdown"),
                    timeout=60.0,
                )
                if get_response.status_code != 200 or "probe: everything-capture" not in get_response.text:
                    raise HTTPException(status_code=500, detail="Obsidian probe read-back verification failed.")

                delete_response = await client.delete(
                    f"{url_base}/vault/{_encode_obsidian_vault_path(probe_path)}",
                    headers=_obsidian_headers(obsidian_api_key, "text/markdown"),
                    timeout=60.0,
                )
                if delete_response.status_code not in [200, 204]:
                    raise HTTPException(status_code=500, detail=f"Obsidian probe cleanup failed: {delete_response.text}")

                if used_saved_url_base:
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
