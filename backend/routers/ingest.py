from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import Item, Media
from schemas import IngestRequest, IngestResponse, ExtractRequest, ExtractResponse
from services.extractor import extract_content
from services.downloader import download_media_list
import logging
import re

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["ingest"]
)

@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def ingest_page(request: IngestRequest, db: Session = Depends(get_db)):
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
        
        return IngestResponse(item_id=new_item.id, status="ready")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/extract", response_model=ExtractResponse, status_code=status.HTTP_201_CREATED)
async def extract_page(request: ExtractRequest, db: Session = Depends(get_db)):
    """服务端提取：传入 URL，后端抓取内容并存储"""
    try:
        result = await extract_content(request.url)

        if not result.text or len(result.text.strip()) < 20:
            raise HTTPException(
                status_code=422,
                detail=f"内容提取失败或内容过短 (平台: {result.platform}，长度: {len(result.text)})"
            )

        new_item = Item(
            source_url=request.url,
            final_url=result.final_url,
            title=result.title,
            canonical_text=result.text,
            canonical_html=result.content_html,
            canonical_text_length=len(result.text),
            platform=result.platform,
            status="ready",
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)

        # 下载媒体文件（图片/视频）
        media_count = 0
        url_mapping = {}  # original_url -> local_path (for HTML rewriting)
        referer = result.final_url or request.url

        if result.media_urls:
            downloaded = await download_media_list(
                item_id=new_item.id,
                media_list=result.media_urls,
                referer=referer,
            )
            for dl in downloaded:
                media_record = Media(
                    item_id=new_item.id,
                    type=dl["type"],
                    original_url=dl["original_url"],
                    local_path=dl["local_path"],
                    file_size=dl["file_size"],
                    display_order=dl["display_order"],
                )
                db.add(media_record)
                url_mapping[dl["original_url"]] = f"/static/{dl['local_path']}"
            media_count = len(downloaded)
            logger.info("已下载 %d 个媒体文件 (item: %s)", media_count, new_item.id)

        # 处理 canonical_html: 确保所有图片都用本地路径
        if result.content_html:
            from bs4 import BeautifulSoup

            html_soup = BeautifulSoup(result.content_html, "lxml")

            # 收集 HTML 中所有需要下载但还没下载的图片
            extra_media = []
            extra_order = media_count
            for img in html_soup.find_all("img"):
                src = img.get("src", "")
                if src and src.startswith("http") and src not in url_mapping:
                    extra_media.append({"type": "image", "url": src, "order": extra_order})
                    extra_order += 1

            # 下载 HTML 中遗漏的图片
            if extra_media:
                extra_downloaded = await download_media_list(
                    item_id=new_item.id,
                    media_list=extra_media,
                    referer=referer,
                )
                for dl in extra_downloaded:
                    media_record = Media(
                        item_id=new_item.id,
                        type=dl["type"],
                        original_url=dl["original_url"],
                        local_path=dl["local_path"],
                        file_size=dl["file_size"],
                        display_order=dl["display_order"],
                    )
                    db.add(media_record)
                    url_mapping[dl["original_url"]] = f"/static/{dl['local_path']}"
                media_count += len(extra_downloaded)

            # 用 BeautifulSoup 替换所有 img src 为本地路径
            for img in html_soup.find_all("img"):
                src = img.get("src", "")
                if src in url_mapping:
                    img["src"] = url_mapping[src]
                elif src and src.startswith("http"):
                    # 下载失败的图片，移除以免显示防盗链提示
                    img.decompose()

            # 提取 body 内容（lxml 会自动加 html/body 标签）
            body = html_soup.find("body")
            new_item.canonical_html = str(body.decode_contents()) if body else str(html_soup)

        db.commit()

        return ExtractResponse(
            item_id=new_item.id,
            title=result.title,
            status="ready",
            platform=result.platform,
            text_length=len(result.text),
            media_count=media_count,
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
