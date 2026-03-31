import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Folder, Item, ItemFolderLink
from schemas import FolderCreateRequest, FolderListResponse, FolderMoveRequest, FolderReorderRequest, FolderResponse, FolderUpdateRequest
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
    parent_id: str | None = None,
    exclude_folder_id: str | None = None,
) -> Folder | None:
    query = db.query(Folder).filter(
        Folder.user_id == user_id,
        func.lower(Folder.name) == name.lower(),
    )
    if parent_id:
        query = query.filter(Folder.parent_id == parent_id)
    else:
        query = query.filter(Folder.parent_id.is_(None))
    if exclude_folder_id:
        query = query.filter(Folder.id != exclude_folder_id)
    return query.first()


def _serialize_folder_rows(rows: list[tuple[Folder, int]]) -> list[FolderResponse]:
    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            sort_order=folder.sort_order or 0,
            parent_id=folder.parent_id,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
            item_count=item_count,
        )
        for folder, item_count in rows
    ]


def _next_folder_sort_order(db: Session, user_id: str, parent_id: str | None = None) -> int:
    q = db.query(func.max(Folder.sort_order)).filter(Folder.user_id == user_id)
    if parent_id:
        q = q.filter(Folder.parent_id == parent_id)
    else:
        q = q.filter(Folder.parent_id.is_(None))
    current_max = q.scalar()
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

    parent_id = (request.parent_id or "").strip() or None
    if parent_id:
        parent = db.query(Folder).filter(Folder.id == parent_id, Folder.user_id == user_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        # Limit nesting to 2 levels
        if parent.parent_id:
            raise HTTPException(status_code=400, detail="Maximum nesting depth (2 levels) exceeded")

    if _find_folder_by_name(db, user_id, name, parent_id=parent_id):
        raise HTTPException(status_code=409, detail="Folder name already exists")

    now = datetime.datetime.utcnow()
    folder = Folder(
        user_id=user_id,
        name=name,
        parent_id=parent_id,
        sort_order=_next_folder_sort_order(db, user_id, parent_id),
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
        parent_id=folder.parent_id,
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
    if _find_folder_by_name(db, user_id, name, parent_id=folder.parent_id, exclude_folder_id=folder.id):
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
        parent_id=folder.parent_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
        item_count=item_count,
    )


@router.post("/reorder", status_code=status.HTTP_204_NO_CONTENT)
def reorder_folders(request: FolderReorderRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    parent_id = (request.parent_id or "").strip() or None

    folder_ids: list[str] = []
    seen: set[str] = set()
    for raw_value in request.folder_ids:
        value = (raw_value or "").strip()
        if not value or value in seen:
            continue
        folder_ids.append(value)
        seen.add(value)

    q = db.query(Folder).filter(Folder.user_id == user_id)
    if parent_id:
        q = q.filter(Folder.parent_id == parent_id)
    else:
        q = q.filter(Folder.parent_id.is_(None))
    user_folders = q.order_by(Folder.sort_order.asc(), Folder.created_at.asc(), Folder.name.asc(), Folder.id.asc()).all()
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


def _is_descendant_of(db: Session, folder_id: str, ancestor_id: str) -> bool:
    current = db.query(Folder).filter(Folder.id == folder_id).first()
    visited: set[str] = set()
    while current and current.parent_id:
        if current.parent_id == ancestor_id:
            return True
        if current.parent_id in visited:
            break
        visited.add(current.parent_id)
        current = db.query(Folder).filter(Folder.id == current.parent_id).first()
    return False


@router.patch("/{folder_id}/parent", response_model=FolderResponse)
def move_folder(folder_id: str, request: FolderMoveRequest, db: Session = Depends(get_db)):
    user_id = get_current_user_id()
    folder = db.query(Folder).filter(Folder.id == folder_id, Folder.user_id == user_id).first()
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    new_parent_id = (request.parent_id or "").strip() or None

    if new_parent_id:
        if new_parent_id == folder_id:
            raise HTTPException(status_code=400, detail="A folder cannot be its own parent")
        parent = db.query(Folder).filter(Folder.id == new_parent_id, Folder.user_id == user_id).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent folder not found")
        if parent.parent_id:
            raise HTTPException(status_code=400, detail="Maximum nesting depth (2 levels) exceeded")
        if _is_descendant_of(db, new_parent_id, folder_id):
            raise HTTPException(status_code=400, detail="Circular reference detected")

    folder.parent_id = new_parent_id
    folder.sort_order = _next_folder_sort_order(db, user_id, new_parent_id)
    folder.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(folder)
    item_count = (
        db.query(func.count(Item.id))
        .join(ItemFolderLink, ItemFolderLink.item_id == Item.id)
        .filter(Item.user_id == user_id, ItemFolderLink.folder_id == folder.id)
        .scalar()
        or 0
    )
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        sort_order=folder.sort_order or 0,
        parent_id=folder.parent_id,
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

    # Promote children to the deleted folder's parent
    children = db.query(Folder).filter(Folder.parent_id == folder_id).all()
    for child in children:
        child.parent_id = folder.parent_id
        child.updated_at = datetime.datetime.utcnow()

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
