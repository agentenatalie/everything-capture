from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Item
from schemas import ItemResponse, MediaResponse
from typing import List

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
                    display_order=m.display_order,
                ))
        results.append(ItemResponse(
            id=item.id,
            created_at=item.created_at,
            source_url=item.source_url,
            title=item.title,
            canonical_text=item.canonical_text,
            canonical_html=getattr(item, 'canonical_html', None),
            status=item.status,
            platform=item.platform,
            media=media_list,
        ))
    return results
