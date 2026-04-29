"""Entry point: ``python -m smtp_service``.

This software is licensed under Elastic License 2.0; see the LICENSE file.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

from .capture_client import read_setting
from .server import SMTPSettings, build_controller

logger = logging.getLogger("smtp_service")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_settings() -> SMTPSettings:
    host = read_setting("SMTP_SERVICE_HOST") or "0.0.0.0"
    port_raw = read_setting("SMTP_SERVICE_PORT") or "2525"
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise SystemExit(f"SMTP_SERVICE_PORT must be an integer, got {port_raw!r}") from exc

    auth_user = read_setting("SMTP_SERVICE_AUTH_USER")
    auth_password = read_setting("SMTP_SERVICE_AUTH_PASSWORD")
    if not auth_user or not auth_password:
        raise SystemExit(
            "SMTP_SERVICE_AUTH_USER and SMTP_SERVICE_AUTH_PASSWORD are required. "
            "Refusing to start without authentication."
        )

    capture_url = read_setting("CAPTURE_SERVICE_URL")
    if not capture_url:
        raise SystemExit("CAPTURE_SERVICE_URL is not configured")

    return SMTPSettings(
        host=host,
        port=port,
        auth_user=auth_user,
        auth_password=auth_password,
        tls_cert=read_setting("SMTP_SERVICE_TLS_CERT") or None,
        tls_key=read_setting("SMTP_SERVICE_TLS_KEY") or None,
        require_tls=_truthy(read_setting("SMTP_SERVICE_REQUIRE_TLS")),
    )


async def _run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    settings = _load_settings()
    controller = build_controller(settings)
    controller.start()
    logger.info(
        "SMTP capture service listening on %s:%d (TLS=%s, require_tls=%s)",
        settings.host,
        settings.port,
        "yes" if settings.tls_cert else "no",
        settings.require_tls,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        logger.info("stopping SMTP capture service")
        controller.stop()
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
