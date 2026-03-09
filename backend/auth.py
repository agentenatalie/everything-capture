from __future__ import annotations

import hashlib
import os
import re
import secrets
from contextvars import ContextVar, Token
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

from models import AuthSession, User

AUTH_SESSION_COOKIE = "everything_grabber_session"
AUTH_GOOGLE_STATE_COOKIE = "everything_grabber_google_state"
AUTH_SESSION_DAYS = 30
AUTH_CODE_TTL_MINUTES = 10

_CURRENT_USER_ID: ContextVar[str | None] = ContextVar("current_user_id", default=None)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def set_request_user_id(user_id: str | None) -> Token:
    return _CURRENT_USER_ID.set(user_id)


def reset_request_user_id(token: Token) -> None:
    _CURRENT_USER_ID.reset(token)


def get_current_user_id() -> str:
    user_id = _CURRENT_USER_ID.get()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


def normalize_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    if not email:
        return None
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    return email


def normalize_phone_e164(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("00"):
        digits = f"+{digits[2:]}"
    if not digits.startswith("+"):
        digits = f"+{digits}"
    normalized = "+" + re.sub(r"\D", "", digits)
    digit_count = len(normalized) - 1
    if digit_count < 8 or digit_count > 15:
        raise HTTPException(status_code=400, detail="Invalid phone number")
    return normalized


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        local_mask = f"{local[:1]}***"
    else:
        local_mask = f"{local[:2]}***"
    return f"{local_mask}@{domain}"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) <= 4:
        return f"***{digits}"
    return f"+***{digits[-4:]}"


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    return secrets.token_urlsafe(48)


def extract_session_token(request: Request) -> str | None:
    cookie_token = request.cookies.get(AUTH_SESSION_COOKIE)
    if cookie_token:
        return cookie_token

    auth_header = (request.headers.get("Authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip() or None

    return None


def issue_auth_session(db: Session, user: User, provider: str, request: Request | None = None) -> tuple[AuthSession, str]:
    raw_token = generate_session_token()
    expires_at = datetime.utcnow() + timedelta(days=AUTH_SESSION_DAYS)
    user_agent = None
    ip_address = None
    if request:
        if getattr(request, "headers", None):
            user_agent = (request.headers.get("user-agent") or "")[:500] or None
        if getattr(request, "client", None):
            ip_address = getattr(request.client, "host", None)
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        provider=provider,
        expires_at=expires_at,
        user_agent=user_agent,
        ip_address=ip_address,
        last_seen_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(auth_session)
    return auth_session, raw_token


def attach_session_cookie(response: Response, raw_token: str, expires_at: datetime) -> None:
    secure = os.getenv("AUTH_COOKIE_SECURE", "0").strip() == "1"
    cookie_expires_at = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    response.set_cookie(
        AUTH_SESSION_COOKIE,
        raw_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        expires=cookie_expires_at,
        max_age=int((expires_at - datetime.utcnow()).total_seconds()),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(AUTH_SESSION_COOKIE, path="/", samesite="lax")


def resolve_auth_session(db: Session, raw_token: str | None) -> tuple[AuthSession | None, User | None]:
    if not raw_token:
        return None, None

    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_session_token(raw_token))
        .first()
    )
    if not session:
        return None, None

    now = datetime.utcnow()
    if session.revoked_at or session.expires_at <= now:
        return None, None
    return session, session.user


def touch_auth_session(session: AuthSession | None) -> None:
    if not session:
        return
    now = datetime.utcnow()
    if not session.last_seen_at or (now - session.last_seen_at) > timedelta(minutes=5):
        session.last_seen_at = now
        session.updated_at = now


def generate_verification_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def generate_code_salt() -> str:
    return secrets.token_hex(16)


def hash_verification_code(code: str, salt: str) -> str:
    payload = f"{salt}:{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
