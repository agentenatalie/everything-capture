import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func
from sqlalchemy.orm import Session

from capture_service.database import Base, engine, get_db, get_storage_info
from capture_service.models import CaptureFolder, CaptureItem, CaptureWorkerHeartbeat
from capture_service.schemas import (
    CaptureClaimRequest,
    CaptureClaimResponse,
    CaptureCompleteRequest,
    CaptureCreateRequest,
    CaptureCreateResponse,
    CaptureFailRequest,
    CaptureFolderCreateRequest,
    CaptureFolderListResponse,
    CaptureFolderResponse,
    CaptureItemResponse,
    CaptureListResponse,
    CaptureWorkerHeartbeatRequest,
    CaptureWorkerStatusResponse,
)


Base.metadata.create_all(bind=engine)
STATIC_DIR = Path(__file__).resolve().parent / "static"
FOLDER_SEED_PATH = Path(__file__).resolve().parent / "folder_seed.json"

app = FastAPI(title="Everything Grabber Capture Service", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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


def _serialize_folder(folder: CaptureFolder) -> CaptureFolderResponse:
    return CaptureFolderResponse(
        id=folder.id,
        name=folder.name,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


def _get_lease_timeout_seconds() -> int:
    raw_value = (os.environ.get("CAPTURE_SERVICE_LEASE_TIMEOUT_SECONDS") or "").strip()
    try:
        lease_timeout = int(raw_value) if raw_value else 6 * 60 * 60
    except ValueError:
        lease_timeout = 6 * 60 * 60
    return max(lease_timeout, 60)


def _release_stale_processing_items(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(seconds=_get_lease_timeout_seconds())
    stale_items = (
        db.query(CaptureItem)
        .filter(CaptureItem.status == "processing")
        .filter(CaptureItem.leased_at.isnot(None))
        .filter(CaptureItem.leased_at < cutoff)
        .all()
    )
    if not stale_items:
        return 0

    for item in stale_items:
        item.status = "pending"
        item.lease_token = None
        item.leased_at = None
        item.error_reason = None
        db.add(item)

    db.commit()
    return len(stale_items)


def _build_status_counts(db: Session) -> dict[str, int]:
    rows = db.query(CaptureItem.status, func.count(CaptureItem.id)).group_by(CaptureItem.status).all()
    status_counts = {status: count for status, count in rows}
    for status_name in ("pending", "processing", "processed", "failed"):
        status_counts.setdefault(status_name, 0)
    return status_counts


def _get_worker_timeout_seconds() -> int:
    raw_value = (os.environ.get("CAPTURE_SERVICE_WORKER_TIMEOUT_SECONDS") or "").strip()
    try:
        worker_timeout = int(raw_value) if raw_value else 45
    except ValueError:
        worker_timeout = 45
    return max(worker_timeout, 10)


def _build_worker_status(db: Session) -> CaptureWorkerStatusResponse:
    cutoff = datetime.utcnow() - timedelta(seconds=_get_worker_timeout_seconds())
    connected_workers = (
        db.query(CaptureWorkerHeartbeat)
        .filter(CaptureWorkerHeartbeat.last_seen_at >= cutoff)
        .order_by(CaptureWorkerHeartbeat.last_seen_at.desc())
        .all()
    )
    latest_worker = (
        db.query(CaptureWorkerHeartbeat)
        .order_by(CaptureWorkerHeartbeat.updated_at.desc())
        .first()
    )

    if connected_workers:
        freshest = connected_workers[0]
        return CaptureWorkerStatusResponse(
            connected=True,
            status_label="后端已连接",
            connected_worker_count=len(connected_workers),
            last_seen_at=freshest.last_seen_at,
            last_success_at=freshest.last_success_at,
            last_error=freshest.last_error,
        )

    return CaptureWorkerStatusResponse(
        connected=False,
        status_label="后端未连接",
        connected_worker_count=0,
        last_seen_at=latest_worker.last_seen_at if latest_worker else None,
        last_success_at=latest_worker.last_success_at if latest_worker else None,
        last_error=latest_worker.last_error if latest_worker else None,
    )


def _ensure_seed_folders() -> None:
    if not FOLDER_SEED_PATH.exists():
        return

    try:
        payload = json.loads(FOLDER_SEED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    folder_names = []
    for entry in payload if isinstance(payload, list) else []:
        name = str((entry or {}).get("name") or "").strip()
        if name and name not in folder_names:
            folder_names.append(name)

    if not folder_names:
        return

    db = Session(bind=engine)
    try:
        existing_names = {
            folder.name
            for folder in db.query(CaptureFolder).filter(CaptureFolder.name.in_(folder_names)).all()
        }
        created = False
        for name in folder_names:
            if name in existing_names:
                continue
            db.add(CaptureFolder(name=name))
            created = True
        if created:
            db.commit()
    finally:
        db.close()


_ensure_seed_folders()


@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/api/app-config")
def app_config():
    return {
        "success": True,
        "service": "everything-grabber-capture-service",
        "capture_endpoint": "/api/capture",
        "folders_endpoint": "/api/folders",
        "items_endpoint": "/api/items",
        "worker_status_endpoint": "/api/worker-status",
        "supports_folder_creation": True,
        "storage": get_storage_info(),
    }


@app.get("/api/worker-status", response_model=CaptureWorkerStatusResponse)
def worker_status(db: Session = Depends(get_db)):
    return _build_worker_status(db)


@app.post("/api/worker-heartbeat", response_model=CaptureWorkerStatusResponse, dependencies=[Depends(_require_service_token)])
def worker_heartbeat(request: CaptureWorkerHeartbeatRequest, db: Session = Depends(get_db)):
    worker_id = (request.worker_id or "").strip()
    if not worker_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="worker_id is required")

    worker = db.query(CaptureWorkerHeartbeat).filter(CaptureWorkerHeartbeat.worker_id == worker_id).first()
    if not worker:
        worker = CaptureWorkerHeartbeat(worker_id=worker_id, created_at=datetime.utcnow())

    now = datetime.utcnow()
    worker.hostname = (request.hostname or "").strip() or None
    worker.state = (request.state or "connected").strip() or "connected"
    worker.last_seen_at = now
    worker.processed_count = max(int(request.processed_count or 0), 0)

    last_error = (request.last_error or "").strip()
    if worker.state == "connected":
        worker.last_success_at = now
        worker.last_error = None
    elif last_error:
        worker.last_error = last_error[:2000]
        worker.last_error_at = now

    db.add(worker)
    db.commit()
    return _build_worker_status(db)


@app.get("/api/folders", response_model=CaptureFolderListResponse, dependencies=[Depends(_require_service_token)])
def list_folders(db: Session = Depends(get_db)):
    folders = db.query(CaptureFolder).order_by(CaptureFolder.name.asc()).all()
    return CaptureFolderListResponse(
        folders=[_serialize_folder(folder) for folder in folders],
        total_count=len(folders),
    )


@app.post("/api/folders", response_model=CaptureFolderResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_require_service_token)])
def create_folder(request: CaptureFolderCreateRequest, db: Session = Depends(get_db)):
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Folder name is required")

    existing = db.query(CaptureFolder).filter(CaptureFolder.name == name).first()
    if existing:
        return _serialize_folder(existing)

    folder = CaptureFolder(name=name)
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return _serialize_folder(folder)


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
    return CaptureCreateResponse(
        success=True,
        captured=True,
        item_id=item.id,
        status=item.status,
        item=_serialize_item(item),
    )


@app.get("/api/items", response_model=CaptureListResponse, dependencies=[Depends(_require_service_token)])
def list_items(
    status_filter: str = Query(default="pending", alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    _release_stale_processing_items(db)

    query = db.query(CaptureItem)
    if status_filter == "waiting":
        query = query.filter(CaptureItem.status.in_(("pending", "processing")))
    elif status_filter != "all":
        query = query.filter(CaptureItem.status == status_filter)

    total_count = query.count()
    items = query.order_by(CaptureItem.created_at.asc()).limit(limit).all()
    return CaptureListResponse(
        items=[_serialize_item(item) for item in items],
        total_count=total_count,
        status_counts=_build_status_counts(db),
    )


@app.get("/api/items/{item_id}", response_model=CaptureItemResponse, dependencies=[Depends(_require_service_token)])
def get_item(item_id: str, db: Session = Depends(get_db)):
    _release_stale_processing_items(db)
    item = db.query(CaptureItem).filter(CaptureItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Capture item not found")
    return _serialize_item(item)


@app.post("/api/items/{item_id}/claim", response_model=CaptureClaimResponse, dependencies=[Depends(_require_service_token)])
def claim_item(item_id: str, request: CaptureClaimRequest, db: Session = Depends(get_db)):
    _release_stale_processing_items(db)
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
