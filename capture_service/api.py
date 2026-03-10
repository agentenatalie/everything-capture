import json
import os
import secrets
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from capture_service.database import Base, engine, get_db
from capture_service.models import CaptureItem
from capture_service.schemas import (
    CaptureClaimRequest,
    CaptureClaimResponse,
    CaptureCompleteRequest,
    CaptureCreateRequest,
    CaptureCreateResponse,
    CaptureFailRequest,
    CaptureItemResponse,
    CaptureListResponse,
)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Everything Grabber Capture Service", version="1.0.0")


def _require_service_token(authorization: str | None = Header(default=None)) -> None:
    configured = (os.environ.get("CAPTURE_SERVICE_TOKEN") or "").strip()
    if not configured:
        return
    incoming = (authorization or "").strip()
    expected = f"Bearer {configured}"
    if incoming != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid capture service token")


def _normalize_folder_names(folder_names: list[str]) -> list[str]:
    normalized: list[str] = []
    for name in folder_names:
        value = (name or "").strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _serialize_item(item: CaptureItem) -> CaptureItemResponse:
    folder_names = []
    if item.folder_names_json:
        try:
            folder_names = json.loads(item.folder_names_json)
        except json.JSONDecodeError:
            folder_names = []
    return CaptureItemResponse(
        id=item.id,
        raw_text=item.raw_text,
        raw_url=item.raw_url,
        title=item.title,
        source=item.source,
        source_app=item.source_app,
        client_timestamp=item.client_timestamp,
        folder_names=folder_names,
        status=item.status,
        lease_token=item.lease_token,
        error_reason=item.error_reason,
        local_item_id=item.local_item_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        processed_at=item.processed_at,
    )


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/capture", response_model=CaptureCreateResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_require_service_token)])
def create_capture(request: CaptureCreateRequest, db: Session = Depends(get_db)):
    if not (request.text or "").strip() and not (request.url or "").strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Either text or url is required")

    item = CaptureItem(
        raw_text=(request.text or "").strip() or None,
        raw_url=(request.url or "").strip() or None,
        title=(request.title or "").strip() or None,
        source=(request.source or "unknown").strip() or "unknown",
        source_app=(request.source_app or "").strip() or None,
        client_timestamp=request.timestamp,
        folder_names_json=json.dumps(_normalize_folder_names(request.folder_names), ensure_ascii=False),
        status="pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return CaptureCreateResponse(item=_serialize_item(item))


@app.get("/api/items", response_model=CaptureListResponse, dependencies=[Depends(_require_service_token)])
def list_items(
    status_filter: str = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(CaptureItem).order_by(CaptureItem.created_at.asc())
    if status_filter != "all":
        query = query.filter(CaptureItem.status == status_filter)
    items = query.limit(limit).all()
    return CaptureListResponse(
        items=[_serialize_item(item) for item in items],
        total_count=len(items),
    )


@app.post("/api/items/{item_id}/claim", response_model=CaptureClaimResponse, dependencies=[Depends(_require_service_token)])
def claim_item(item_id: str, request: CaptureClaimRequest, db: Session = Depends(get_db)):
    item = db.query(CaptureItem).filter(CaptureItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture item not found")
    if item.status != "pending":
        return CaptureClaimResponse(success=False, item=_serialize_item(item))

    item.status = "processing"
    item.lease_token = secrets.token_urlsafe(24)
    item.leased_at = datetime.utcnow()
    item.error_reason = None
    item.result_json = json.dumps({"worker_id": request.worker_id}, ensure_ascii=False)
    db.add(item)
    db.commit()
    db.refresh(item)
    return CaptureClaimResponse(success=True, item=_serialize_item(item))


@app.post("/api/items/{item_id}/complete", response_model=CaptureItemResponse, dependencies=[Depends(_require_service_token)])
def complete_item(item_id: str, request: CaptureCompleteRequest, db: Session = Depends(get_db)):
    item = db.query(CaptureItem).filter(CaptureItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture item not found")
    if item.lease_token != request.lease_token:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lease token mismatch")

    item.status = "processed"
    item.processed_at = datetime.utcnow()
    item.local_item_id = request.local_item_id
    item.result_json = request.result_json
    item.lease_token = None
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_item(item)


@app.post("/api/items/{item_id}/fail", response_model=CaptureItemResponse, dependencies=[Depends(_require_service_token)])
def fail_item(item_id: str, request: CaptureFailRequest, db: Session = Depends(get_db)):
    item = db.query(CaptureItem).filter(CaptureItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture item not found")
    if item.lease_token != request.lease_token:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Lease token mismatch")

    item.status = "failed"
    item.failed_at = datetime.utcnow()
    item.error_reason = request.error_reason.strip()[:2000]
    item.lease_token = None
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_item(item)
