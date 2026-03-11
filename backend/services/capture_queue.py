import json
import os
from pathlib import Path
from typing import Any

import httpx


def _load_capture_service_file_values() -> dict[str, str]:
    candidate_paths = [
        Path(__file__).resolve().parents[1] / ".local" / "capture_service.env",
        Path(__file__).resolve().parents[2] / ".local" / "capture_service.env",
    ]
    values: dict[str, str] = {}

    for candidate_path in candidate_paths:
        if not candidate_path.exists():
            continue

        try:
            for raw_line in candidate_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:].strip()
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if key:
                    values[key] = value
        except OSError:
            continue

        if values:
            return values

    return values


def _read_capture_service_setting(name: str) -> str:
    env_value = (os.environ.get(name) or "").strip()
    if env_value:
        return env_value
    return (_load_capture_service_file_values().get(name) or "").strip()


def get_capture_service_base_url() -> str | None:
    value = _read_capture_service_setting("CAPTURE_SERVICE_URL").rstrip("/")
    return value or None


def capture_service_enabled() -> bool:
    return bool(get_capture_service_base_url())


def _capture_service_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = _read_capture_service_setting("CAPTURE_SERVICE_TOKEN")
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


def report_capture_worker_heartbeat(
    worker_id: str,
    *,
    hostname: str | None = None,
    state: str = "connected",
    processed_count: int = 0,
    last_error: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    base_url = get_capture_service_base_url()
    if not base_url:
        raise RuntimeError("CAPTURE_SERVICE_URL is not configured")

    payload = {
        "worker_id": worker_id,
        "hostname": hostname,
        "state": state,
        "processed_count": max(int(processed_count or 0), 0),
        "last_error": last_error,
    }
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{base_url}/api/worker-heartbeat",
            headers=_capture_service_headers(),
            json=payload,
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
