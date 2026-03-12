import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Folder, Item, ItemFolderLink
from schemas import FolderCreateRequest, FolderListResponse, FolderReorderRequest, FolderResponse, FolderUpdateRequest
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
            sort_order=folder.sort_order or 0,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
            item_count=item_count,
        )
        for folder, item_count in rows
    ]


def _next_folder_sort_order(db: Session, user_id: str) -> int:
    current_max = db.query(func.max(Folder.sort_order)).filter(Folder.user_id == user_id).scalar()
    return int(current_max if current_max is not None else -1) + 1


@router.get("", response_model=FolderListResponse)
def get_folders(db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    folder_rows = (
        db.query(Folder, func.count(Item.id))
        .outerjoin(ItemFolderLink, ItemFolderLink.folder_id == Folder.id)
        .outerjoin(Item, (Item.id == ItemFolderLink.item_id) & (Item.user_id == user_id))
        .filter(Folder.user_id == user_id)
        .group_by(Folder.id)
        .order_by(Folder.sort_order.asc(), Folder.created_at.asc(), Folder.name.asc(), Folder.id.asc())
        .all()
    )
    total_count = db.query(func.count(Item.id)).filter(Item.user_id == user_id).scalar() or 0
    unfiled_count = (
        db.query(func.count(Item.id))
        .outerjoin(ItemFolderLink, ItemFolderLink.item_id == Item.id)
        .filter(Item.user_id == user_id, ItemFolderLink.item_id.is_(None))
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
    folder = Folder(
        user_id=user_id,
        name=name,
        sort_order=_next_folder_sort_order(db, user_id),
        created_at=now,
        updated_at=now,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        sort_order=folder.sort_order or 0,
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
        .join(ItemFolderLink, ItemFolderLink.item_id == Item.id)
        .filter(Item.user_id == user_id, ItemFolderLink.folder_id == folder.id)
        .scalar()
        or 0
    )
    db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        sort_order=folder.sort_order or 0,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        item_count=item_count,
    )


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
def reorder_folders(request: FolderReorderRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    folder_ids: list[str] = []
    seen: set[str] = set()
    for raw_value in request.folder_ids:
        value = (raw_value or "").strip()
        if not value or value in seen:
            continue
        folder_ids.append(value)
        seen.add(value)

    user_folders = (
        db.query(Folder)
        .filter(Folder.user_id == user_id)
        .order_by(Folder.sort_order.asc(), Folder.created_at.asc(), Folder.name.asc(), Folder.id.asc())
        .all()
    )
    current_folder_ids = [folder.id for folder in user_folders]
    if not current_folder_ids:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if len(folder_ids) != len(current_folder_ids) or set(folder_ids) != set(current_folder_ids):
        raise HTTPException(status_code=400, detail="Folder order payload must include every folder exactly once")

    folders_by_id = {folder.id: folder for folder in user_folders}
    now = datetime.datetime.utcnow()
    for index, folder_id in enumerate(folder_ids):
        folder = folders_by_id[folder_id]
        folder.sort_order = index
        folder.updated_at = now

    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_folder(folder_id: str, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == user_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    affected_items = (
        db.query(Item)
        .join(ItemFolderLink, ItemFolderLink.item_id == Item.id)
        .filter(Item.user_id == user_id, ItemFolderLink.folder_id == folder.id)
        .all()
    )
    db.query(ItemFolderLink).filter(ItemFolderLink.folder_id == folder.id).delete(synchronize_session=False)
    db.flush()
    for item in affected_items:
        replacement_link = (
            db.query(ItemFolderLink)
            .join(Folder, Folder.id == ItemFolderLink.folder_id)
            .filter(ItemFolderLink.item_id == item.id, Folder.user_id == user_id)
            .order_by(ItemFolderLink.created_at.asc(), Folder.created_at.asc(), Folder.name.asc())
            .first()
        )
        item.folder_id = replacement_link.folder_id if replacement_link else None
    db.delete(folder)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
