import argparse
import asyncio
import json
import logging
import socket
import time
from datetime import datetime
from types import SimpleNamespace

from database import SessionLocal
from models import Folder, Item
from routers.ingest import execute_extract_request
from routers.items import sync_item_folder_assignments
from schemas import ExtractRequest
from services.capture_queue import (
    capture_service_enabled,
    claim_capture_item,
    complete_capture_item,
    fail_capture_item,
    list_capture_items,
)
from tenant import DEFAULT_USER_ID, DEFAULT_WORKSPACE_ID


logger = logging.getLogger("processing_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

WORKER_REQUEST = SimpleNamespace(
    headers={"user-agent": "EverythingGrabberProcessingWorker/1.0"},
    cookies={},
)


class ImmediateBackgroundTasks:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.calls.append((func, args, kwargs))

    def run_all(self) -> None:
        for func, args, kwargs in self.calls:
            func(*args, **kwargs)


def _normalize_folder_names(folder_names: list[str] | None) -> list[str]:
    normalized: list[str] = []
    for name in folder_names or []:
        value = str(name or "").strip()
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def build_capture_item_finalizer(capture_item: dict, db, user_id: str):
    folder_names = _normalize_folder_names(capture_item.get("folder_names"))

    def finalize_item(item: Item) -> None:
        metadata = {
            "capture_service_item_id": capture_item.get("id"),
            "capture_source": capture_item.get("source"),
            "capture_created_at": capture_item.get("created_at"),
        }
        item.debug_json = json.dumps(metadata, ensure_ascii=False)

        if not folder_names:
            return

        existing_folders = (
            db.query(Folder)
            .filter(Folder.user_id == user_id, Folder.name.in_(folder_names))
            .all()
        )
        folders_by_name = {folder.name: folder for folder in existing_folders}
        ordered_folders: list[Folder] = []
        now = datetime.utcnow()

        for folder_name in folder_names:
            folder = folders_by_name.get(folder_name)
            if not folder:
                folder = Folder(
                    user_id=user_id,
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    name=folder_name,
                    updated_at=now,
                )
                db.add(folder)
                db.flush()
                folders_by_name[folder_name] = folder
            folder.updated_at = now
            ordered_folders.append(folder)

        sync_item_folder_assignments(item, ordered_folders)

    return finalize_item


async def process_capture_item(capture_item: dict) -> tuple[str, str, ImmediateBackgroundTasks]:
    background_tasks = ImmediateBackgroundTasks()
    request = ExtractRequest(
        url=capture_item.get("raw_url"),
        source_url=capture_item.get("raw_url"),
        text=capture_item.get("raw_text"),
        title=capture_item.get("title"),
    )

    with SessionLocal() as db:
        response, item = await execute_extract_request(
            request,
            WORKER_REQUEST,
            background_tasks,
            db,
            DEFAULT_USER_ID,
            item_finalizer=build_capture_item_finalizer(capture_item, db, DEFAULT_USER_ID),
        )
        db.refresh(item)
        return item.id, response.status, background_tasks


def process_once(limit: int, worker_id: str) -> int:
    pending_items = list_capture_items(status="pending", limit=limit)
    processed_count = 0

    for pending_item in pending_items:
        claim_result = claim_capture_item(pending_item["id"], worker_id)
        if not claim_result.get("success"):
            continue

        claimed_item = claim_result.get("item") or {}
        lease_token = claimed_item.get("lease_token")
        if not lease_token:
            logger.warning("Capture item %s claimed without lease token", pending_item["id"])
            continue

        try:
            local_item_id, result_status, background_tasks = asyncio.run(process_capture_item(claimed_item))
            background_tasks.run_all()
            complete_capture_item(
                pending_item["id"],
                lease_token,
                local_item_id=local_item_id,
                result_json=json.dumps({"local_status": result_status}, ensure_ascii=False),
            )
            processed_count += 1
        except Exception as exc:
            logger.exception("Failed to process capture item %s", pending_item["id"])
            fail_capture_item(pending_item["id"], lease_token, str(exc))

    return processed_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Process pending capture-service items locally.")
    parser.add_argument("--once", action="store_true", help="Process one batch and exit.")
    parser.add_argument("--interval", type=float, default=15.0, help="Polling interval in seconds.")
    parser.add_argument("--limit", type=int, default=10, help="Max pending items per batch.")
    args = parser.parse_args()

    if not capture_service_enabled():
        logger.error("CAPTURE_SERVICE_URL is not configured")
        return 1

    worker_id = f"{socket.gethostname()}-{int(time.time())}"
    logger.info("Starting processing worker %s", worker_id)

    if args.once:
        try:
            processed = process_once(args.limit, worker_id)
        except Exception:
            logger.exception("Processing worker batch failed")
            return 1
        logger.info("Processed %d capture items", processed)
        return 0

    while True:
        try:
            processed = process_once(args.limit, worker_id)
            if processed:
                logger.info("Processed %d capture items", processed)
        except Exception:
            logger.exception("Processing worker loop failed; retrying after backoff")
        time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
