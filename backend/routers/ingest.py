from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import Item
from schemas import IngestRequest, IngestResponse, ExtractRequest, ExtractResponse
from services.extractor import extract_content

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
            canonical_text_length=len(result.text),
            platform=result.platform,
            status="ready",
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)

        return ExtractResponse(
            item_id=new_item.id,
            title=result.title,
            status="ready",
            platform=result.platform,
            text_length=len(result.text),
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
