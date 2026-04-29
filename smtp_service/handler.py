"""aiosmtpd message handler — turn each inbound mail into capture POSTs.

This software is licensed under Elastic License 2.0; see the LICENSE file.
"""
from __future__ import annotations

import asyncio
import email
import logging
from email import policy

from .capture_client import (
    CaptureRejectedError,
    CaptureRetryableError,
    post_capture,
)
from .url_extract import extract_bodies, extract_urls

logger = logging.getLogger(__name__)


class CaptureSMTPHandler:
    async def handle_DATA(self, server, session, envelope) -> str:  # noqa: N802 — aiosmtpd hook name
        try:
            msg = email.message_from_bytes(envelope.content, policy=policy.default)
        except Exception as exc:
            logger.exception("failed to parse RFC822 payload: %s", exc)
            return "501 Cannot parse message"

        subject = (str(msg.get("Subject") or "")).strip()
        from_addr = (str(msg.get("From") or "")).strip()
        plain, html = extract_bodies(msg)
        urls = extract_urls(subject=subject, plain=plain, html=html)

        if not urls:
            logger.info("no URL in mail from %s (subject=%r) — skipping", from_addr, subject)
            return "250 Accepted (no URL found)"

        loop = asyncio.get_running_loop()
        accepted = 0
        for url in urls:
            try:
                await loop.run_in_executor(
                    None,
                    lambda u=url: post_capture(url=u, title=subject or None, source_app=from_addr or None),
                )
                accepted += 1
                logger.info("queued capture from %s: %s", from_addr, url)
            except CaptureRetryableError as exc:
                logger.error("retryable error posting %s: %s", url, exc)
                return "451 Temporary failure, please retry"
            except CaptureRejectedError as exc:
                logger.warning("capture_service rejected %s: %s", url, exc)
                continue
            except Exception as exc:
                logger.exception("unexpected error posting %s: %s", url, exc)
                return "451 Temporary failure, please retry"

        return f"250 OK ({accepted} queued)"
