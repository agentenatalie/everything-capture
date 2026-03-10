import json
import os
from typing import Any

import httpx


def get_capture_service_base_url() -> str | None:
    value = (os.environ.get("CAPTURE_SERVICE_URL") or "").strip().rstrip("/")
    return value or None


def capture_service_enabled() -> bool:
    return bool(get_capture_service_base_url())


def _capture_service_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = (os.environ.get("CAPTURE_SERVICE_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def queue_capture(payload: dict[str, Any], timeout: float = 15.0) -> dict[str, Any]:
    base_url = get_capture_service_base_url()
    if not base_url:
        raise RuntimeError("CAPTURE_SERVICE_URL is not configured")

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/api/capture",
            headers=_capture_service_headers(),
            content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        response.raise_for_status()
        return response.json()


def list_capture_items(status: str = "pending", limit: int = 20, timeout: float = 15.0) -> list[dict[str, Any]]:
    base_url = get_capture_service_base_url()
    if not base_url:
        return []

    with httpx.Client(timeout=timeout) as client:
        response = client.get(
            f"{base_url}/api/items",
            headers=_capture_service_headers(),
            params={"status": status, "limit": limit},
        )
        response.raise_for_status()
        payload = response.json()
    return list(payload.get("items") or [])


def claim_capture_item(item_id: str, worker_id: str, timeout: float = 15.0) -> dict[str, Any]:
    base_url = get_capture_service_base_url()
    if not base_url:
        raise RuntimeError("CAPTURE_SERVICE_URL is not configured")

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/api/items/{item_id}/claim",
            headers=_capture_service_headers(),
            json={"worker_id": worker_id},
        )
        response.raise_for_status()
        return response.json()


def complete_capture_item(
    item_id: str,
    lease_token: str,
    *,
    local_item_id: str | None = None,
    result_json: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    base_url = get_capture_service_base_url()
    if not base_url:
        raise RuntimeError("CAPTURE_SERVICE_URL is not configured")

    payload = {
        "lease_token": lease_token,
        "local_item_id": local_item_id,
        "result_json": result_json,
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/api/items/{item_id}/complete",
            headers=_capture_service_headers(),
            json=payload,
        )
        response.raise_for_status()
        return response.json()


def fail_capture_item(item_id: str, lease_token: str, error_reason: str, timeout: float = 15.0) -> dict[str, Any]:
    base_url = get_capture_service_base_url()
    if not base_url:
        raise RuntimeError("CAPTURE_SERVICE_URL is not configured")

    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/api/items/{item_id}/fail",
            headers=_capture_service_headers(),
            json={"lease_token": lease_token, "error_reason": error_reason},
        )
        response.raise_for_status()
        return response.json()
