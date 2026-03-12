import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from database import get_db
from models import Item
from routers.ingest import execute_extract_request
from routers.items import normalize_requested_folder_ids, resolve_folders, sync_item_folder_assignments
from schemas import ExtractResponse, PhoneExtractRequest
from services.capture_queue import capture_service_enabled, queue_capture
from tenant import get_current_user_id

logger = logging.getLogger(__name__)

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


def _resolve_phone_folder_names(
    request: PhoneExtractRequest,
    db: Session,
    user_id: str,
) -> list[str]:
    requested_folder_ids = normalize_requested_folder_ids(request.folder_id, request.folder_ids)
    if not requested_folder_ids:
        return []

    folders = resolve_folders(db, user_id, requested_folder_ids)
    return [folder.name for folder in folders if folder.name]


@router.post("/phone-extract", response_model=ExtractResponse, status_code=status.HTTP_201_CREATED)
async def phone_extract_page(
    request: PhoneExtractRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user_id = get_current_user_id()
    if capture_service_enabled():
        try:
            capture_payload = await run_in_threadpool(
                queue_capture,
                {
                    "text": request.text,
                    "url": request.url or request.source_url,
                    "title": request.title,
                    "source": "phone-webapp",
                    "source_app": "everything-capture-phone",
                    "folder_names": _resolve_phone_folder_names(request, db, user_id),
                },
            )
            queued_item = capture_payload.get("item") or {}
            queued_title = (
                queued_item.get("title")
                or (request.title or "").strip()
                or (request.url or request.source_url or request.text or "Queued Capture")
            )
            raw_text = (request.text or "").strip()
            return ExtractResponse(
                item_id=str(queued_item.get("id") or ""),
                title=queued_title[:200],
                status=str(queued_item.get("status") or "pending"),
                platform="capture",
                text_length=len(raw_text),
                media_count=0,
            )
        except Exception as exc:
            logger.warning("Capture service queue failed, falling back to local phone processing: %s", exc)

    response, _ = await execute_extract_request(
        request,
        http_request,
        background_tasks,
        db,
        user_id,
        item_finalizer=build_phone_extract_item_finalizer(request, db, user_id),
    )
    return response
