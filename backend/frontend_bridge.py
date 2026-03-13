from __future__ import annotations

import os
from urllib.parse import urlencode, urlsplit

from fastapi import Request

FRONTEND_ORIGIN_ENV_VARS = (
    "EVERYTHING_CAPTURE_FRONTEND_ORIGIN",
    "FRONTEND_ORIGIN",
)
FRONTEND_PORT_ENV = "FRONTEND_PORT"
DEFAULT_FRONTEND_PORT = "8010"


def _clean_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _configured_frontend_origin() -> str | None:
    for env_name in FRONTEND_ORIGIN_ENV_VARS:
        value = _clean_optional_string(os.getenv(env_name))
        if value:
            return value.rstrip("/")
    return None


def _format_host(hostname: str) -> str:
    return f"[{hostname}]" if ":" in hostname else hostname


def resolve_frontend_origin(request: Request | None = None) -> str:
    configured = _configured_frontend_origin()
    if configured:
        return configured

    scheme = "http"
    hostname = "127.0.0.1"
    if request is not None:
        forwarded_proto = _clean_optional_string(request.headers.get("x-forwarded-proto"))
        if forwarded_proto:
            scheme = forwarded_proto.split(",", 1)[0].strip() or scheme
        elif getattr(request.url, "scheme", None):
            scheme = request.url.scheme

        host_header = _clean_optional_string(request.headers.get("x-forwarded-host")) or _clean_optional_string(
            request.headers.get("host")
        )
        if host_header:
            parsed = urlsplit(f"{scheme}://{host_header.split(',', 1)[0].strip()}")
            if parsed.hostname:
                hostname = parsed.hostname
        elif getattr(request.url, "hostname", None):
            hostname = request.url.hostname

    frontend_port = _clean_optional_string(os.getenv(FRONTEND_PORT_ENV)) or DEFAULT_FRONTEND_PORT
    return f"{scheme}://{_format_host(hostname)}:{frontend_port}"


def build_frontend_url(
    request: Request | None = None,
    *,
    path: str = "/",
    query_params: dict[str, str] | None = None,
    query_string: str | None = None,
) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    base = f"{resolve_frontend_origin(request)}{normalized_path}"
    if query_string is not None:
        normalized_query = query_string.lstrip("?")
    elif query_params:
        normalized_query = urlencode(query_params, doseq=True)
    else:
        normalized_query = ""
    return f"{base}?{normalized_query}" if normalized_query else base
