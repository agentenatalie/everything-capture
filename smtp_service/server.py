"""aiosmtpd Controller wiring — auth, optional STARTTLS.

This software is licensed under Elastic License 2.0; see the LICENSE file.
"""
from __future__ import annotations

import hmac
import logging
import ssl
from dataclasses import dataclass

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword

from .handler import CaptureSMTPHandler

logger = logging.getLogger(__name__)


@dataclass
class SMTPSettings:
    host: str
    port: int
    auth_user: str
    auth_password: str
    tls_cert: str | None
    tls_key: str | None
    require_tls: bool


def _build_authenticator(settings: SMTPSettings):
    expected_user = settings.auth_user.encode()
    expected_pw = settings.auth_password.encode()

    def authenticator(server, session, envelope, mechanism, auth_data):
        if not isinstance(auth_data, LoginPassword):
            return AuthResult(success=False, handled=False)
        user_ok = hmac.compare_digest(auth_data.login, expected_user)
        pw_ok = hmac.compare_digest(auth_data.password, expected_pw)
        if user_ok and pw_ok:
            return AuthResult(success=True)
        peer = getattr(session, "peer", None)
        logger.warning("AUTH failed from %s for user=%r", peer, auth_data.login)
        return AuthResult(success=False, handled=False)

    return authenticator


def _build_tls_context(settings: SMTPSettings) -> ssl.SSLContext | None:
    if not settings.tls_cert or not settings.tls_key:
        return None
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile=settings.tls_cert, keyfile=settings.tls_key)
    return context


def build_controller(settings: SMTPSettings) -> Controller:
    tls_context = _build_tls_context(settings)
    if settings.require_tls and tls_context is None:
        raise RuntimeError(
            "SMTP_SERVICE_REQUIRE_TLS=1 but SMTP_SERVICE_TLS_CERT/KEY are not configured"
        )

    return Controller(
        handler=CaptureSMTPHandler(),
        hostname=settings.host,
        port=settings.port,
        authenticator=_build_authenticator(settings),
        auth_required=True,
        auth_require_tls=settings.require_tls,
        tls_context=tls_context,
    )
