from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from sqlalchemy.orm import Session

from database import get_db
from models import Item
from routers.ingest import execute_extract_request
from routers.items import normalize_requested_folder_ids, resolve_folders, sync_item_folder_assignments
from schemas import ExtractResponse, PhoneExtractRequest
from tenant import get_current_user_id

router = APIRouter(
    prefix="/api",
    tags=["phone-webapp"]
)


def build_phone_extract_item_finalizer(
    request: PhoneExtractRequest,
    db: Session,
    user_id: str,
):
    def finalize_item(item: Item) -> None:
        requested_folder_ids = normalize_requested_folder_ids(request.folder_id, request.folder_ids)
        if not requested_folder_ids:
            return

        folders = resolve_folders(db, user_id, requested_folder_ids)
        sync_item_folder_assignments(item, folders)
        now = datetime.utcnow()
        for folder in folders:
            folder.updated_at = now

    return finalize_item


@router.post("/phone-extract", response_model=ExtractResponse, status_code=status.HTTP_201_CREATED)
async def phone_extract_page(
    request: PhoneExtractRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    response, _ = await execute_extract_request(
        request,
        http_request,
        background_tasks,
        db,
        user_id,
        item_finalizer=build_phone_extract_item_finalizer(request, db, user_id),
    )
    return response
