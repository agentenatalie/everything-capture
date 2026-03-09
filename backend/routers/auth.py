import base64
import os
import smtplib
import urllib.parse
from datetime import datetime, timedelta
from email.message import EmailMessage

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app_settings import resolve_google_oauth_config
from auth import (
    AUTH_CODE_TTL_MINUTES,
    AUTH_GOOGLE_STATE_COOKIE,
    attach_session_cookie,
    clear_session_cookie,
    generate_code_salt,
    generate_verification_code,
    hash_verification_code,
    issue_auth_session,
    mask_email,
    mask_phone,
    normalize_email,
    normalize_phone_e164,
)
from database import get_db
from models import AuthSession, AuthVerificationCode, User
from schemas import (
    AuthProvidersResponse,
    AuthSessionResponse,
    AuthUserResponse,
    CodeDeliveryResponse,
    EmailCodeRequest,
    EmailCodeVerifyRequest,
    PhoneCodeRequest,
    PhoneCodeVerifyRequest,
)
from tenant import DEFAULT_USER_EMAIL, DEFAULT_USER_ID

router = APIRouter(
    prefix="/api/auth",
    tags=["auth"],
)

SMTP_HOST_ENV = "AUTH_SMTP_HOST"
SMTP_PORT_ENV = "AUTH_SMTP_PORT"
SMTP_USERNAME_ENV = "AUTH_SMTP_USERNAME"
SMTP_PASSWORD_ENV = "AUTH_SMTP_PASSWORD"
SMTP_FROM_ENV = "AUTH_SMTP_FROM_EMAIL"
TWILIO_ACCOUNT_SID_ENV = "AUTH_TWILIO_ACCOUNT_SID"
TWILIO_AUTH_TOKEN_ENV = "AUTH_TWILIO_AUTH_TOKEN"
TWILIO_FROM_ENV = "AUTH_TWILIO_FROM_NUMBER"
DEV_CODE_DELIVERY_ENV = "AUTH_DEV_CODE_DELIVERY"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _serialize_user(user: User | None) -> AuthUserResponse | None:
    if not user:
        return None
    return AuthUserResponse(
        id=user.id,
        email=user.email,
        phone_e164=user.phone_e164,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
    )


def _dev_code_delivery_enabled() -> bool:
    return os.getenv(DEV_CODE_DELIVERY_ENV, "1").strip() != "0"


def _google_redirect_uri(request: Request, google_config: dict | None = None) -> str:
    configured = ((google_config or {}).get("redirect_uri") or "").strip()
    if configured:
        return configured
    return str(request.url_for("google_auth_callback"))


def _providers_payload(request: Request | None = None, db: Session | None = None) -> AuthProvidersResponse:
    google_config = resolve_google_oauth_config(db) if db is not None else {}
    google_enabled = bool(
        (google_config.get("client_id") or "").strip()
        and (google_config.get("client_secret") or "").strip()
        and (request is None or _google_redirect_uri(request, google_config))
    )
    smtp_enabled = bool(
        (os.getenv(SMTP_HOST_ENV) or "").strip()
        and (os.getenv(SMTP_FROM_ENV) or "").strip()
    )
    twilio_enabled = bool(
        (os.getenv(TWILIO_ACCOUNT_SID_ENV) or "").strip()
        and (os.getenv(TWILIO_AUTH_TOKEN_ENV) or "").strip()
        and (os.getenv(TWILIO_FROM_ENV) or "").strip()
    )
    dev_enabled = _dev_code_delivery_enabled()
    return AuthProvidersResponse(
        google_enabled=google_enabled,
        email_enabled=smtp_enabled or dev_enabled,
        phone_enabled=twilio_enabled or dev_enabled,
        email_delivery_mode="smtp" if smtp_enabled else ("dev" if dev_enabled else "disabled"),
        phone_delivery_mode="twilio" if twilio_enabled else ("dev" if dev_enabled else "disabled"),
    )


def _claimable_default_user(db: Session) -> User | None:
    return (
        db.query(User)
        .filter(User.id == DEFAULT_USER_ID, User.is_default.is_(True))
        .first()
    )


def _create_or_claim_user(
    db: Session,
    *,
    email: str | None = None,
    phone_e164: str | None = None,
    google_sub: str | None = None,
    display_name: str | None = None,
    avatar_url: str | None = None,
) -> User:
    now = _utcnow()
    user = None

    if google_sub:
        user = db.query(User).filter(User.google_sub == google_sub).first()
    if not user and email:
        user = db.query(User).filter(func.lower(User.email) == email.lower()).first()
    if not user and phone_e164:
        user = db.query(User).filter(User.phone_e164 == phone_e164).first()

    if not user:
        default_user = _claimable_default_user(db)
        if default_user:
            user = default_user
            user.is_default = False
        else:
            fallback_name = display_name or (email.split("@")[0] if email else (phone_e164 or "User"))
            user = User(
                email=email or f"user-{base64.urlsafe_b64encode(os.urandom(6)).decode('utf-8').rstrip('=')}@placeholder.local",
                display_name=fallback_name[:120],
                is_default=False,
            )
            db.add(user)
            db.flush()

    if email:
        user.email = email
        user.email_verified_at = now
    if phone_e164:
        user.phone_e164 = phone_e164
        user.phone_verified_at = now
    if google_sub:
        user.google_sub = google_sub
        if email and not user.email_verified_at:
            user.email_verified_at = now
    if display_name:
        user.display_name = display_name[:120]
    elif not user.display_name:
        user.display_name = (email.split("@")[0] if email else phone_e164 or "User")[:120]
    if avatar_url:
        user.avatar_url = avatar_url[:500]

    if user.email == DEFAULT_USER_EMAIL and email:
        user.email = email

    user.updated_at = now
    user.last_login_at = now
    if not user.id:
        db.flush()
    return user


def _build_auth_session_response(user: User | None, request: Request, db: Session) -> AuthSessionResponse:
    providers = _providers_payload(request, db)
    return AuthSessionResponse(
        authenticated=user is not None,
        user=_serialize_user(user),
        providers=providers,
    )


def _send_email_code(email: str, code: str) -> str:
    smtp_host = (os.getenv(SMTP_HOST_ENV) or "").strip()
    smtp_from = (os.getenv(SMTP_FROM_ENV) or "").strip()
    if not smtp_host or not smtp_from:
        if _dev_code_delivery_enabled():
            return "dev"
        raise HTTPException(status_code=503, detail="Email delivery is not configured")

    smtp_port = int((os.getenv(SMTP_PORT_ENV) or "587").strip())
    smtp_username = (os.getenv(SMTP_USERNAME_ENV) or "").strip()
    smtp_password = (os.getenv(SMTP_PASSWORD_ENV) or "").strip()
    use_ssl = smtp_port == 465

    message = EmailMessage()
    message["Subject"] = "Your Everything Grabber login code"
    message["From"] = smtp_from
    message["To"] = email
    message.set_content(
        f"Your login code is {code}. It expires in {AUTH_CODE_TTL_MINUTES} minutes.\n"
    )

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as smtp:
                if smtp_username and smtp_password:
                    smtp.login(smtp_username, smtp_password)
                smtp.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                if smtp_username and smtp_password:
                    smtp.login(smtp_username, smtp_password)
                smtp.send_message(message)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Email delivery failed: {exc}") from exc

    return "smtp"


async def _send_phone_code(phone_e164: str, code: str) -> str:
    sid = (os.getenv(TWILIO_ACCOUNT_SID_ENV) or "").strip()
    auth_token = (os.getenv(TWILIO_AUTH_TOKEN_ENV) or "").strip()
    from_number = (os.getenv(TWILIO_FROM_ENV) or "").strip()
    if not sid or not auth_token or not from_number:
        if _dev_code_delivery_enabled():
            return "dev"
        raise HTTPException(status_code=503, detail="SMS delivery is not configured")

    async with httpx.AsyncClient(auth=(sid, auth_token), timeout=15.0) as client:
        response = await client.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={
                "To": phone_e164,
                "From": from_number,
                "Body": f"Your Everything Grabber login code is {code}. It expires in {AUTH_CODE_TTL_MINUTES} minutes.",
            },
        )
    if response.status_code >= 300:
        raise HTTPException(status_code=502, detail=f"SMS delivery failed: {response.text}")
    return "twilio"


def _store_verification_code(
    db: Session,
    *,
    channel: str,
    target: str,
    user_id: str | None = None,
) -> str:
    now = _utcnow()
    db.query(AuthVerificationCode).filter(
        AuthVerificationCode.channel == channel,
        AuthVerificationCode.target == target,
        AuthVerificationCode.consumed_at.is_(None),
    ).update({"consumed_at": now})

    code = generate_verification_code()
    salt = generate_code_salt()
    verification_code = AuthVerificationCode(
        user_id=user_id,
        channel=channel,
        target=target,
        code_salt=salt,
        code_hash=hash_verification_code(code, salt),
        purpose="login",
        expires_at=now + timedelta(minutes=AUTH_CODE_TTL_MINUTES),
    )
    db.add(verification_code)
    db.commit()
    return code


def _consume_verification_code(db: Session, *, channel: str, target: str, code: str) -> None:
    record = (
        db.query(AuthVerificationCode)
        .filter(
            AuthVerificationCode.channel == channel,
            AuthVerificationCode.target == target,
            AuthVerificationCode.purpose == "login",
            AuthVerificationCode.consumed_at.is_(None),
        )
        .order_by(AuthVerificationCode.created_at.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=400, detail="No active verification code")

    now = _utcnow()
    if record.expires_at <= now:
        record.consumed_at = now
        db.commit()
        raise HTTPException(status_code=400, detail="Verification code expired")

    if record.attempt_count >= 5:
        record.consumed_at = now
        db.commit()
        raise HTTPException(status_code=429, detail="Too many verification attempts")

    expected_hash = hash_verification_code(code.strip(), record.code_salt)
    if expected_hash != record.code_hash:
        record.attempt_count += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid verification code")

    record.consumed_at = now
    db.commit()


@router.get("/providers", response_model=AuthProvidersResponse)
def get_auth_providers(request: Request, db: Session = Depends(get_db)):
    return _providers_payload(request, db)


@router.get("/session", response_model=AuthSessionResponse)
def get_auth_session(request: Request, db: Session = Depends(get_db)):
    user = getattr(request.state, "auth_user", None)
    return _build_auth_session_response(user, request, db)


@router.post("/email/request-code", response_model=CodeDeliveryResponse)
def request_email_code(request_body: EmailCodeRequest, db: Session = Depends(get_db)):
    email = normalize_email(request_body.email)
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    code = _store_verification_code(db, channel="email", target=email)
    delivery_mode = _send_email_code(email, code)
    return CodeDeliveryResponse(
        status="sent",
        delivery_mode=delivery_mode,
        target_masked=mask_email(email),
        dev_code=code if delivery_mode == "dev" else None,
    )


@router.post("/email/verify-code", response_model=AuthSessionResponse)
def verify_email_code(request: Request, request_body: EmailCodeVerifyRequest, db: Session = Depends(get_db)):
    email = normalize_email(request_body.email)
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    _consume_verification_code(db, channel="email", target=email, code=request_body.code)
    user = _create_or_claim_user(
        db,
        email=email,
        display_name=(request_body.display_name or email.split("@")[0]).strip(),
    )
    auth_session, raw_token = issue_auth_session(db, user, "email_code", request)
    db.commit()
    db.refresh(user)

    response = JSONResponse(content=_build_auth_session_response(user, request, db).model_dump())
    attach_session_cookie(response, raw_token, auth_session.expires_at)
    return response


@router.post("/phone/request-code", response_model=CodeDeliveryResponse)
async def request_phone_code(request_body: PhoneCodeRequest, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(request_body.phone)
    if not phone_e164:
        raise HTTPException(status_code=400, detail="Phone number is required")

    code = _store_verification_code(db, channel="phone", target=phone_e164)
    delivery_mode = await _send_phone_code(phone_e164, code)
    return CodeDeliveryResponse(
        status="sent",
        delivery_mode=delivery_mode,
        target_masked=mask_phone(phone_e164),
        dev_code=code if delivery_mode == "dev" else None,
    )


@router.post("/phone/verify-code", response_model=AuthSessionResponse)
def verify_phone_code(request: Request, request_body: PhoneCodeVerifyRequest, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(request_body.phone)
    if not phone_e164:
        raise HTTPException(status_code=400, detail="Phone number is required")

    _consume_verification_code(db, channel="phone", target=phone_e164, code=request_body.code)
    user = _create_or_claim_user(
        db,
        phone_e164=phone_e164,
        display_name=(request_body.display_name or phone_e164).strip(),
    )
    auth_session, raw_token = issue_auth_session(db, user, "phone_code", request)
    db.commit()
    db.refresh(user)

    response = JSONResponse(content=_build_auth_session_response(user, request, db).model_dump())
    attach_session_cookie(response, raw_token, auth_session.expires_at)
    return response


@router.get("/google/start")
def start_google_auth(request: Request, db: Session = Depends(get_db)):
    google_config = resolve_google_oauth_config(db)
    providers = _providers_payload(request, db)
    if not providers.google_enabled:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured")

    state = base64.urlsafe_b64encode(os.urandom(24)).decode("utf-8").rstrip("=")
    redirect_uri = _google_redirect_uri(request, google_config)
    query = urllib.parse.urlencode(
        {
            "client_id": (google_config.get("client_id") or "").strip(),
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
            "state": state,
        }
    )
    response = RedirectResponse(url=f"https://accounts.google.com/o/oauth2/v2/auth?{query}")
    secure = os.getenv("AUTH_COOKIE_SECURE", "0").strip() == "1"
    response.set_cookie(
        AUTH_GOOGLE_STATE_COOKIE,
        state,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=600,
        path="/",
    )
    return response


@router.get("/google/callback", name="google_auth_callback")
async def google_auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None, db: Session = Depends(get_db)):
    if error:
        return RedirectResponse(url=f"/?auth=failed&provider=google&error={urllib.parse.quote(error)}")
    expected_state = request.cookies.get(AUTH_GOOGLE_STATE_COOKIE)
    if not code or not state or not expected_state or state != expected_state:
        return RedirectResponse(url="/?auth=failed&provider=google&error=invalid_state")

    google_config = resolve_google_oauth_config(db)
    client_id = (google_config.get("client_id") or "").strip()
    client_secret = (google_config.get("client_secret") or "").strip()
    redirect_uri = _google_redirect_uri(request, google_config)
    if not client_id or not client_secret:
        return RedirectResponse(url="/?auth=failed&provider=google&error=missing_config")

    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code >= 300:
            return RedirectResponse(url="/?auth=failed&provider=google&error=token_exchange_failed")

        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            return RedirectResponse(url="/?auth=failed&provider=google&error=missing_access_token")

        userinfo_response = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if userinfo_response.status_code >= 300:
            return RedirectResponse(url="/?auth=failed&provider=google&error=userinfo_failed")

    profile = userinfo_response.json()
    google_sub = (profile.get("sub") or "").strip()
    email = normalize_email(profile.get("email"))
    display_name = (profile.get("name") or (email.split("@")[0] if email else "Google User")).strip()
    avatar_url = (profile.get("picture") or "").strip() or None
    if not google_sub or not email:
        return RedirectResponse(url="/?auth=failed&provider=google&error=incomplete_profile")

    user = _create_or_claim_user(
        db,
        email=email,
        google_sub=google_sub,
        display_name=display_name,
        avatar_url=avatar_url,
    )
    auth_session, raw_token = issue_auth_session(db, user, "google_oauth", request)
    db.commit()

    response = RedirectResponse(url="/?auth=success&provider=google")
    attach_session_cookie(response, raw_token, auth_session.expires_at)
    response.delete_cookie(AUTH_GOOGLE_STATE_COOKIE, path="/", samesite="lax")
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    auth_session = getattr(request.state, "auth_session", None)
    auth_session_id = getattr(auth_session, "id", None)
    if auth_session_id:
        session_record = db.query(AuthSession).filter(AuthSession.id == auth_session_id).first()
        if session_record:
            now = _utcnow()
            session_record.revoked_at = now
            session_record.updated_at = now
            db.commit()
    response = JSONResponse({"status": "ok"})
    clear_session_cookie(response)
    return response
