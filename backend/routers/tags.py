import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import ItemTagLink, Tag
from schemas import TagCreateRequest, TagListResponse, TagResponse, TagUpdateRequest
from tenant import get_current_user_id

router = APIRouter(
    prefix="/api/tags",
    tags=["tags"],
)


def _clean_tag_name(value: str) -> str:
    return (value or "").strip()


@router.get("", response_model=TagListResponse)
def get_tags(db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    rows = (
        db.query(Tag, func.count(ItemTagLink.item_id))
        .outerjoin(ItemTagLink, ItemTagLink.tag_id == Tag.id)
        .filter(Tag.user_id == user_id)
        .group_by(Tag.id)
        .order_by(Tag.name.asc())
        .all()
    )
    return TagListResponse(
        tags=[
            TagResponse(
                id=tag.id,
                name=tag.name,
                color=tag.color,
                item_count=count,
                created_at=tag.created_at,
            )
            for tag, count in rows
        ]
    )


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
def create_tag(request: TagCreateRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    name = _clean_tag_name(request.name)
    if not name:
        raise HTTPException(status_code=400, detail="Tag name is required")

    existing = (
        db.query(Tag)
        .filter(Tag.user_id == user_id, func.lower(Tag.name) == name.lower())
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Tag name already exists")

    tag = Tag(
        user_id=user_id,
        name=name,
        color=request.color,
        created_at=datetime.datetime.utcnow(),
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        item_count=0,
        created_at=tag.created_at,
    )


@router.patch("/{tag_id}", response_model=TagResponse)
def update_tag(tag_id: str, request: TagUpdateRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if request.name is not None:
        name = _clean_tag_name(request.name)
        if not name:
            raise HTTPException(status_code=400, detail="Tag name is required")
        existing = (
            db.query(Tag)
            .filter(Tag.user_id == user_id, func.lower(Tag.name) == name.lower(), Tag.id != tag_id)
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Tag name already exists")
        tag.name = name

    if request.color is not None:
        tag.color = request.color

    db.commit()
    db.refresh(tag)
    item_count = db.query(func.count(ItemTagLink.item_id)).filter(ItemTagLink.tag_id == tag_id).scalar() or 0
    return TagResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        item_count=item_count,
        created_at=tag.created_at,
    )


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    tag = db.query(Tag).filter(Tag.id == tag_id, Tag.user_id == user_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.query(ItemTagLink).filter(ItemTagLink.tag_id == tag_id).delete(synchronize_session=False)
    db.delete(tag)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
