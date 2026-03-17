from __future__ import annotations

import os
from typing import Optional

from sqlalchemy.orm import Session

from models import AppConfig
from security import decrypt_secret, encrypt_secret, has_secret_value

GOOGLE_CLIENT_ID_ENV = "GOOGLE_OAUTH_CLIENT_ID"
GOOGLE_CLIENT_SECRET_ENV = "GOOGLE_OAUTH_CLIENT_SECRET"
GOOGLE_REDIRECT_URI_ENV = "GOOGLE_OAUTH_REDIRECT_URI"

USE_FTS5_SEARCH = os.getenv("USE_FTS5_SEARCH", "true").lower() == "true"


def clean_optional_string(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    return text or None


def get_app_config(db: Session) -> AppConfig | None:
    return db.query(AppConfig).order_by(AppConfig.id.asc()).first()


def ensure_app_config(db: Session) -> AppConfig:
    app_config = get_app_config(db)
    if app_config:
        return app_config
    app_config = AppConfig()
    db.add(app_config)
    return app_config


def resolve_google_oauth_config(db: Session) -> dict[str, Optional[str] | bool]:
    app_config = get_app_config(db)
    env_client_id = clean_optional_string(os.getenv(GOOGLE_CLIENT_ID_ENV))
    env_client_secret = clean_optional_string(os.getenv(GOOGLE_CLIENT_SECRET_ENV))
    env_redirect_uri = clean_optional_string(os.getenv(GOOGLE_REDIRECT_URI_ENV))

    stored_client_id = clean_optional_string(app_config.google_oauth_client_id if app_config else None)
    stored_client_secret = decrypt_secret(app_config.google_oauth_client_secret) if app_config else None
    stored_redirect_uri = clean_optional_string(app_config.google_oauth_redirect_uri if app_config else None)

    managed_by = "env" if any([env_client_id, env_client_secret, env_redirect_uri]) else "settings"
    client_id = env_client_id or stored_client_id
    client_secret = env_client_secret or stored_client_secret
    redirect_uri = env_redirect_uri or stored_redirect_uri

    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "secret_saved": bool(client_secret),
        "ready": bool(client_id and client_secret),
        "managed_by": managed_by,
    }


def build_google_oauth_settings_payload(db: Session) -> dict[str, Optional[str] | bool]:
    app_config = get_app_config(db)
    runtime_config = resolve_google_oauth_config(db)
    return {
        "google_oauth_client_id": runtime_config["client_id"],
        "google_oauth_client_secret": None,
        "google_oauth_client_secret_saved": bool(
            runtime_config["secret_saved"]
            or (app_config and has_secret_value(app_config.google_oauth_client_secret))
        ),
        "google_oauth_redirect_uri": runtime_config["redirect_uri"],
        "google_oauth_ready": bool(runtime_config["ready"]),
        "google_oauth_missing_fields": [
            field
            for field, value in (
                ("google_oauth_client_id", runtime_config["client_id"]),
                ("google_oauth_client_secret", runtime_config["client_secret"]),
            )
            if not value
        ],
        "google_oauth_managed_by": str(runtime_config["managed_by"]),
    }


def update_google_oauth_settings(
    db: Session,
    *,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> AppConfig:
    app_config = ensure_app_config(db)
    if client_id is not None:
        app_config.google_oauth_client_id = clean_optional_string(client_id)
    if client_secret is not None:
        app_config.google_oauth_client_secret = encrypt_secret(client_secret)
    if redirect_uri is not None:
        app_config.google_oauth_redirect_uri = clean_optional_string(redirect_uri)
    return app_config
