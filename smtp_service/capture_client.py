"""POST captures to the capture_service /api/capture endpoint.

This software is licensed under Elastic License 2.0; see the LICENSE file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx


class CaptureClientError(Exception):
    """Base error for capture POST failures."""


class CaptureRetryableError(CaptureClientError):
    """5xx / network / timeout — caller should ask sender to retry."""


class CaptureRejectedError(CaptureClientError):
    """4xx — payload was rejected; retrying will not help."""


def _load_env_file_values() -> dict[str, str]:
    candidate_paths = [
        Path(__file__).resolve().parents[1] / "backend" / ".local" / "capture_service.env",
        Path(__file__).resolve().parents[1] / ".local" / "capture_service.env",
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


def read_setting(name: str) -> str:
    env_value = (os.environ.get(name) or "").strip()
    if env_value:
        return env_value
    return (_load_env_file_values().get(name) or "").strip()


def _base_url() -> str:
    url = read_setting("CAPTURE_SERVICE_URL").rstrip("/")
    if not url:
        raise CaptureClientError("CAPTURE_SERVICE_URL is not configured")
    return url


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = read_setting("CAPTURE_SERVICE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def post_capture(
    *,
    url: str,
    title: str | None = None,
    source_app: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "url": url,
        "source": "email",
    }
    if title:
        payload["title"] = title
    if source_app:
        payload["source_app"] = source_app

    base = _base_url()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{base}/api/capture",
                headers=_headers(),
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
    except httpx.RequestError as exc:
        raise CaptureRetryableError(f"network error: {exc}") from exc

    if 500 <= response.status_code < 600:
        raise CaptureRetryableError(f"capture_service returned {response.status_code}: {response.text[:200]}")
    if 400 <= response.status_code < 500:
        raise CaptureRejectedError(f"capture_service rejected {response.status_code}: {response.text[:200]}")
    return response.json()
