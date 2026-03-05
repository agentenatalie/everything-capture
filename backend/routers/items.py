from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Item
from schemas import ItemResponse, MediaResponse
from typing import List
import shutil
import os
import logging

logger = logging.getLogger(__name__)

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

@router.delete("/items/{item_id}")
def delete_item(item_id: str, db: Session = Depends(get_db)):
    from models import Media
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # 删除磁盘上的媒体文件夹
    media_dir = os.path.join("static", "media", item_id)
    if os.path.exists(media_dir):
        try:
            shutil.rmtree(media_dir)
            logger.info(f"已删除媒体文件夹: {media_dir}")
        except Exception as e:
            logger.error(f"删除媒体文件夹失败 {media_dir}: {e}")

    # 删除数据库记录
    db.query(Media).filter(Media.item_id == item_id).delete()
    db.delete(item)
    db.commit()

    return {"message": "Success", "id": item_id}
