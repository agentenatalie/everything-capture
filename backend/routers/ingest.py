import html
import json
import logging
import re
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Request
from sqlalchemy.orm import Session
from auth import extract_session_token, is_shortcut_bearer_token
from database import get_db, SessionLocal
from models import Item, Media, Settings
from schemas import IngestRequest, IngestResponse, ExtractRequest, ExtractResponse
from services.extractor import extract_content
from services.downloader import download_media_list, probe_video_duration_seconds
from tenant import get_current_user_id
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["ingest"]
)

import asyncio
from routers.connect import sync_to_notion, sync_to_obsidian

HTTP_URL_PATTERN = re.compile(r"https?://[^\s<>'\"`]+", re.IGNORECASE)

def background_auto_sync(item_id: str, user_id: str):
    db = SessionLocal()
    try:
        settings = db.query(Settings).filter(Settings.user_id == user_id).first()
        if not settings or settings.auto_sync_target == "none":
            return
            
        target = settings.auto_sync_target
        
        # sync_to_notion and sync_to_obsidian are async methods, we need to run them
        # in the background task loop
        async def run_sync():
            if target in ["notion", "both"]:
                try:
                    await sync_to_notion(item_id, db)
                except Exception as e:
                    logger.error(f"Auto-sync to Notion failed for {item_id}: {e}")
            if target in ["obsidian", "both"]:
                try:
                    await sync_to_obsidian(item_id, db)
                except Exception as e:
                    logger.error(f"Auto-sync to Obsidian failed for {item_id}: {e}")
                    
        asyncio.run(run_sync())
    finally:
        db.close()


def _normalize_http_url(candidate: str | None) -> str | None:
    value = (candidate or "").strip()
    if not value:
        return None
    trimmed = re.sub(r"[)\]}>.,!?;:'\"。，！？；：]+$", "", value)
    if not re.match(r"^https?://", trimmed, re.IGNORECASE):
        return None
    return trimmed


def _extract_first_http_url(value: str | None) -> str | None:
    if not value:
        return None
    match = HTTP_URL_PATTERN.search(value)
    if not match:
        return None
    return _normalize_http_url(match.group(0))


def _resolve_extract_url(request: ExtractRequest) -> str | None:
    return (
        _normalize_http_url(request.url)
        or _normalize_http_url(request.source_url)
        or _extract_first_http_url(request.text)
    )


def _fallback_text_title(request: ExtractRequest, text: str) -> str:
    explicit_title = (request.title or "").strip()
    if explicit_title:
        return explicit_title[:200]

    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:200]
    return "Shared Text"


def _serialize_content_blocks(content_blocks: list[dict] | None) -> str | None:
    if not content_blocks:
        return None
    return json.dumps(content_blocks, ensure_ascii=False)


def _replace_media_urls_in_blocks(content_blocks: list[dict] | None, url_map: dict[str, str]) -> str | None:
    if not content_blocks:
        return None

    final_blocks = []
    for block in content_blocks:
        if block["type"] in {"image", "video"}:
            local_url = url_map.get(block["url"])
            if local_url:
                final_blocks.append({"type": block["type"], "url": local_url})
        else:
            final_blocks.append(block)
    return _serialize_content_blocks(final_blocks)


def _replace_media_urls_in_html(content_html: str | None, url_map: dict[str, str]) -> str | None:
    if not content_html:
        return None

    soup = BeautifulSoup(content_html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "")
        local_url = url_map.get(src)
        if local_url:
            img["src"] = local_url
        else:
            img.decompose()

    for video in soup.find_all("video"):
        src = video.get("src", "")
        if src:
            local_url = url_map.get(src)
            if local_url:
                video["src"] = local_url
        for source in video.find_all("source"):
            source_src = source.get("src", "")
            if not source_src:
                continue
            local_url = url_map.get(source_src)
            if local_url:
                source["src"] = local_url

    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        local_url = url_map.get(src)
        if local_url:
            iframe["src"] = local_url

    return str(soup)


def _store_initial_extracted_content(item: Item, content_blocks: list[dict] | None, content_html: str | None) -> None:
    item.content_blocks_json = _serialize_content_blocks(content_blocks)
    item.canonical_html = content_html or item.canonical_html


async def _download_and_apply_media_updates(
    db: Session,
    item: Item,
    media_list: list[dict],
    content_blocks: list[dict] | None,
    content_html: str | None,
    referer: str,
    user_id: str,
) -> int:
    downloaded = await download_media_list(
        item_id=item.id,
        media_list=media_list,
        referer=referer,
        user_id=user_id,
    )

    db.query(Media).filter(Media.item_id == item.id, Media.user_id == user_id).delete()

    url_map: dict[str, str] = {}
    for dl in downloaded:
        media_record = Media(
            user_id=user_id,
            item_id=item.id,
            type=dl["type"],
            original_url=dl["original_url"],
            local_path=dl["local_path"],
            file_size=dl["file_size"],
            display_order=dl["display_order"],
            inline_position=dl.get("inline_position", -1.0),
        )
        db.add(media_record)
        url_map[dl["original_url"]] = f"/static/{dl['local_path']}" if dl["local_path"] else dl["original_url"]

    localized_blocks = _replace_media_urls_in_blocks(content_blocks, url_map)
    if localized_blocks is not None:
        item.content_blocks_json = localized_blocks

    localized_html = _replace_media_urls_in_html(content_html, url_map)
    if localized_html is not None:
        item.canonical_html = localized_html

    db.add(item)
    return len(downloaded)


async def _should_background_media_processing(
    http_request: Request,
    media_list: list[dict],
    referer: str,
) -> bool:
    raw_token = extract_session_token(http_request)
    is_shortcut_request = is_shortcut_bearer_token(raw_token)
    user_agent = (http_request.headers.get("user-agent") or "").lower()
    is_mobile_request = "mobile" in user_agent or "iphone" in user_agent or "android" in user_agent

    if not is_shortcut_request and not is_mobile_request:
        return False

    video_candidates = [media for media in media_list if media.get("type") == "video" and media.get("url")]
    if not video_candidates:
        return False

    duration_seconds = await probe_video_duration_seconds(
        video_candidates[0]["url"],
        "video",
        referer=referer,
    )
    return bool(duration_seconds and duration_seconds > 15 * 60)


def background_finalize_extracted_media(
    item_id: str,
    media_list: list[dict],
    content_blocks: list[dict] | None,
    content_html: str | None,
    referer: str,
    user_id: str,
) -> None:
    db = SessionLocal()
    try:
        item = db.query(Item).filter(Item.id == item_id, Item.user_id == user_id).first()
        if not item:
            return

        downloaded_count = asyncio.run(
            _download_and_apply_media_updates(
                db,
                item,
                media_list=media_list,
                content_blocks=content_blocks,
                content_html=content_html,
                referer=referer,
                user_id=user_id,
            )
        )
        db.commit()
        logger.info("后台媒体处理完成 %d 个文件 (item: %s)", downloaded_count, item_id)

        background_auto_sync(item_id, user_id)
    except Exception as exc:
        db.rollback()
        logger.error("后台媒体处理失败 %s: %s", item_id, exc)
    finally:
        db.close()


def _store_shared_text_capture_record(
    request: ExtractRequest,
    db: Session,
    user_id: str,
    background_tasks: BackgroundTasks,
    item_finalizer: Callable[[Item], None] | None = None,
) -> tuple[ExtractResponse, Item]:
    shared_text = (request.text or "").strip()
    if len(shared_text) < 3:
        raise HTTPException(status_code=422, detail="未检测到可保存的链接或文本内容")

    source_url = _normalize_http_url(request.source_url) or ""
    title = _fallback_text_title(request, shared_text)
    paragraphs = [segment.strip() for segment in re.split(r"\n{2,}", shared_text) if segment.strip()]
    canonical_html = "".join(f"<p>{html.escape(paragraph)}</p>" for paragraph in paragraphs)

    new_item = Item(
        user_id=user_id,
        source_url=source_url,
        final_url=source_url or None,
        title=title,
        canonical_text=shared_text,
        canonical_text_length=len(shared_text),
        canonical_html=canonical_html or None,
        platform="web",
        status="ready",
    )
    try:
        db.add(new_item)
        if item_finalizer:
            item_finalizer(new_item)
        db.commit()
        db.refresh(new_item)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    background_tasks.add_task(background_auto_sync, new_item.id, user_id)

    response = ExtractResponse(
        item_id=new_item.id,
        title=title,
        status="ready",
        platform="web",
        text_length=len(shared_text),
        media_count=0,
    )
    return response, new_item


def _store_shared_text_capture(
    request: ExtractRequest,
    db: Session,
    user_id: str,
    background_tasks: BackgroundTasks,
) -> ExtractResponse:
    response, _ = _store_shared_text_capture_record(
        request,
        db,
        user_id,
        background_tasks,
    )
    return response


async def execute_extract_request(
    request: ExtractRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: Session,
    user_id: str,
    item_finalizer: Callable[[Item], None] | None = None,
) -> tuple[ExtractResponse, Item]:
    resolved_url = _resolve_extract_url(request)
    if not resolved_url:
        return _store_shared_text_capture_record(
            request,
            db,
            user_id,
            background_tasks,
            item_finalizer=item_finalizer,
        )

    try:
        result = await extract_content(resolved_url)
        has_media = bool(result.media_urls)
        stored_text = (result.text or "").strip()
        if not stored_text and has_media:
            stored_text = (result.title or resolved_url).strip()

        if not stored_text or (len(stored_text) < 20 and not has_media):
            raise HTTPException(
                status_code=422,
                detail=f"内容提取失败或内容过短 (平台: {result.platform}，长度: {len(stored_text)})"
            )

        new_item = Item(
            user_id=user_id,
            source_url=resolved_url,
            final_url=result.final_url,
            title=result.title,
            canonical_text=stored_text,
            canonical_text_length=len(stored_text),
            platform=result.platform,
            status="ready",
        )
        db.add(new_item)
        _store_initial_extracted_content(new_item, result.content_blocks, result.content_html)
        if item_finalizer:
            item_finalizer(new_item)
        db.commit()
        db.refresh(new_item)

        media_count = len(result.media_urls or [])
        if result.media_urls:
            referer = result.final_url or resolved_url
            if await _should_background_media_processing(http_request, result.media_urls, referer):
                background_tasks.add_task(
                    background_finalize_extracted_media,
                    new_item.id,
                    result.media_urls,
                    result.content_blocks,
                    result.content_html,
                    referer,
                    user_id,
                )
            else:
                media_count = await _download_and_apply_media_updates(
                    db,
                    new_item,
                    result.media_urls,
                    result.content_blocks,
                    result.content_html,
                    referer,
                    user_id,
                )
                db.commit()
                logger.info("同步媒体处理完成 %d 个文件 (item: %s)", media_count, new_item.id)
                background_tasks.add_task(background_auto_sync, new_item.id, user_id)
        else:
            background_tasks.add_task(background_auto_sync, new_item.id, user_id)

        response = ExtractResponse(
            item_id=new_item.id,
            title=result.title,
            status="ready",
            platform=result.platform,
            text_length=len(stored_text),
            media_count=media_count,
        )
        return response, new_item
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_page(request: IngestRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    try:
        new_item = Item(
            user_id=user_id,
            source_url=request.source_url,
            final_url=request.final_url,
            title=request.title,
            canonical_text=request.canonical_text,
            canonical_text_length=len(request.canonical_text),
            platform=request.client.platform,
            status="ready",
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)

        background_tasks.add_task(background_auto_sync, new_item.id, user_id)

        return IngestResponse(item_id=new_item.id, status="ready")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract", response_model=ExtractResponse, status_code=status.HTTP_201_CREATED)
async def extract_page(request: ExtractRequest, http_request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """服务端提取：优先提取 URL，兼容快捷指令 text 载荷并支持文本兜底入库"""
    user_id = get_current_user_id()
    response, _ = await execute_extract_request(
        request,
        http_request,
        background_tasks,
        db,
        user_id,
    )
    return response
