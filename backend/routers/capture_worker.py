import logging
import os
import socket
import threading
import time

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["capture-worker"])

_wake_lock = threading.Lock()
_wake_running = False


class CaptureWorkerWakeRequest(BaseModel):
    item_id: str | None = None
    reason: str | None = None


class CaptureWorkerWakeResponse(BaseModel):
    success: bool = True
    accepted: bool = True
    already_running: bool = False


def _configured_wake_token() -> str:
    return (os.environ.get("CAPTURE_WORKER_WAKE_TOKEN") or "").strip()


def _require_wake_token(authorization: str | None, x_capture_wake_token: str | None) -> None:
    configured = _configured_wake_token()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Capture worker wake endpoint is not configured",
        )

    bearer_prefix = "Bearer "
    incoming_authorization = (authorization or "").strip()
    incoming_header = (x_capture_wake_token or "").strip()
    incoming_token = incoming_header
    if incoming_authorization.startswith(bearer_prefix):
        incoming_token = incoming_authorization[len(bearer_prefix):].strip()

    if incoming_token != configured:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid wake token")


def _run_wake_processing(item_id: str | None) -> None:
    global _wake_running
    worker_id = f"wake-{socket.gethostname()}-{int(time.time())}"
    processed = 0
    try:
        import processing_worker

        logger.info("Capture worker wake started for item_id=%s", item_id or "")
        processed = processing_worker.process_once(limit=10, worker_id=worker_id)
        processing_worker.send_worker_heartbeat(
            worker_id,
            socket.gethostname(),
            state="connected",
            processed_count=processed,
        )
        logger.info("Capture worker wake finished; processed=%d", processed)
    except Exception:
        logger.exception("Capture worker wake processing failed")
        try:
            import processing_worker

            processing_worker.send_worker_heartbeat(
                worker_id,
                socket.gethostname(),
                state="error",
                processed_count=processed,
                last_error="capture worker wake failed",
            )
        except Exception:
            logger.debug("Failed to report wake processing failure", exc_info=True)
    finally:
        with _wake_lock:
            _wake_running = False


def _start_wake_thread(item_id: str | None) -> bool:
    global _wake_running
    with _wake_lock:
        if _wake_running:
            return False
        _wake_running = True

    thread = threading.Thread(
        target=_run_wake_processing,
        args=(item_id,),
        name="capture-worker-wake",
        daemon=True,
    )
    thread.start()
    return True


@router.post("/capture-worker/wake", response_model=CaptureWorkerWakeResponse)
def wake_capture_worker(
    request: CaptureWorkerWakeRequest,
    authorization: str | None = Header(default=None),
    x_capture_wake_token: str | None = Header(default=None),
) -> CaptureWorkerWakeResponse:
    _require_wake_token(authorization, x_capture_wake_token)
    started = _start_wake_thread(request.item_id)
    return CaptureWorkerWakeResponse(accepted=True, already_running=not started)
