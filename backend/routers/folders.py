import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Folder, Item
from schemas import FolderCreateRequest, FolderListResponse, FolderResponse, FolderUpdateRequest
from tenant import get_current_user_id

router = APIRouter(
    prefix="/api/folders",
    tags=["folders"]
)


def _clean_folder_name(value: str) -> str:
    return (value or "").strip()


def _find_folder_by_name(
    db: Session,
    user_id: str,
    name: str,
    *,
    exclude_folder_id: str | None = None,
) -> Folder | None:
    query = db.query(Folder).filter(
        Folder.user_id == user_id,
        func.lower(Folder.name) == name.lower(),
    )
    if exclude_folder_id:
        query = query.filter(Folder.id != exclude_folder_id)
    return query.first()


def _serialize_folder_rows(rows: list[tuple[Folder, int]]) -> list[FolderResponse]:
    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
            item_count=item_count,
        )
        for folder, item_count in rows
    ]


@router.get("", response_model=FolderListResponse)
def get_folders(db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    folder_rows = (
        db.query(Folder, func.count(Item.id))
        .outerjoin(Item, (Item.folder_id == Folder.id) & (Item.user_id == user_id))
        .filter(Folder.user_id == user_id)
        .group_by(Folder.id)
        .order_by(Folder.updated_at.desc(), Folder.created_at.desc(), Folder.name.asc())
        .all()
    )
    total_count = db.query(func.count(Item.id)).filter(Item.user_id == user_id).scalar() or 0
    unfiled_count = (
        db.query(func.count(Item.id))
        .filter(Item.user_id == user_id, Item.folder_id.is_(None))
        .scalar()
        or 0
    )
    return FolderListResponse(
        folders=_serialize_folder_rows(folder_rows),
        total_count=total_count,
        unfiled_count=unfiled_count,
    )


@router.post("", response_model=FolderResponse, status_code=status.HTTP_201_CREATED)
def create_folder(request: FolderCreateRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    name = _clean_folder_name(request.name)
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if _find_folder_by_name(db, user_id, name):
        raise HTTPException(status_code=409, detail="Folder name already exists")

    now = datetime.datetime.utcnow()
    folder = Folder(user_id=user_id, name=name, created_at=now, updated_at=now)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        item_count=0,
    )


@router.patch("/{folder_id}", response_model=FolderResponse)
def update_folder(folder_id: str, request: FolderUpdateRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == user_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    name = _clean_folder_name(request.name)
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    if _find_folder_by_name(db, user_id, name, exclude_folder_id=folder.id):
        raise HTTPException(status_code=409, detail="Folder name already exists")

    folder.name = name
    folder.updated_at = datetime.datetime.utcnow()
    db.commit()
    item_count = (
        db.query(func.count(Item.id))
        .filter(Item.user_id == user_id, Item.folder_id == folder.id)
        .scalar()
        or 0
    )
    db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        item_count=item_count,
    )


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(folder_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == user_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    db.query(Item).filter(Item.user_id == user_id, Item.folder_id == folder.id).update({"folder_id": None})
    db.delete(folder)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
