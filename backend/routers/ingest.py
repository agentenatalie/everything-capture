from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db, SessionLocal
from models import Item, Media, Settings
from schemas import IngestRequest, IngestResponse, ExtractRequest, ExtractResponse
from services.extractor import extract_content
from services.downloader import download_media_list
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["ingest"]
)

import asyncio
from routers.connect import sync_to_notion, sync_to_obsidian

def background_auto_sync(item_id: str):
    db = SessionLocal()
    try:
        settings = db.query(Settings).first()
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

@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_page(request: IngestRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    try:
        new_item = Item(
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
        
        background_tasks.add_task(background_auto_sync, new_item.id)
        
        return IngestResponse(item_id=new_item.id, status="ready")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract", response_model=ExtractResponse, status_code=status.HTTP_201_CREATED)
async def extract_page(request: ExtractRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """服务端提取：传入 URL，后端抓取内容并存储"""
    try:
        result = await extract_content(request.url)
        has_media = bool(result.media_urls)
        stored_text = (result.text or "").strip()
        if not stored_text and has_media:
            stored_text = (result.title or request.url).strip()

        if not stored_text or (len(stored_text) < 20 and not has_media):
            raise HTTPException(
                status_code=422,
                detail=f"内容提取失败或内容过短 (平台: {result.platform}，长度: {len(stored_text)})"
            )

        new_item = Item(
            source_url=request.url,
            final_url=result.final_url,
            title=result.title,
            canonical_text=stored_text,
            canonical_text_length=len(stored_text),
            platform=result.platform,
            status="ready",
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)

        # 下载媒体文件（图片/视频）
        media_count = 0
        if result.media_urls:
            referer = result.final_url or request.url
            downloaded = await download_media_list(
                item_id=new_item.id,
                media_list=result.media_urls,
                referer=referer,
            )
            # Build original_url → local_url map for substituting into content_blocks
            url_map: dict[str, str] = {}
            for dl in downloaded:
                media_record = Media(
                    item_id=new_item.id,
                    type=dl["type"],
                    original_url=dl["original_url"],
                    local_path=dl["local_path"],
                    file_size=dl["file_size"],
                    display_order=dl["display_order"],
                    inline_position=dl.get("inline_position", -1.0),
                )
                db.add(media_record)
                url_map[dl["original_url"]] = f"/static/{dl['local_path']}" if dl["local_path"] else dl["original_url"]

            # Save content_blocks_json with local URLs substituted in
            if result.content_blocks:
                import json as _json
                final_blocks = []
                for block in result.content_blocks:
                    if block["type"] in {"image", "video"}:
                        local_url = url_map.get(block["url"])
                        if local_url:
                            final_blocks.append({"type": block["type"], "url": local_url})
                    else:
                        final_blocks.append(block)
                if final_blocks:
                    new_item.content_blocks_json = _json.dumps(final_blocks, ensure_ascii=False)
                    db.add(new_item)

            # Build and save canonical_html with replaced image URLs
            if result.content_html:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(result.content_html, "html.parser")
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    # Match normalized URL to url_map
                    local_url = url_map.get(src)
                    if local_url:
                        img["src"] = local_url
                    else:
                        img.decompose()  # Remove if it wasn't downloaded

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
                
                new_item.canonical_html = str(soup)
                db.add(new_item)

            db.commit()
            media_count = len(downloaded)
            logger.info("已下载 %d 个媒体文件 (item: %s)", media_count, new_item.id)

        background_tasks.add_task(background_auto_sync, new_item.id)

        return ExtractResponse(
            item_id=new_item.id,
            title=result.title,
            status="ready",
            platform=result.platform,
            text_length=len(stored_text),
            media_count=media_count,
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
