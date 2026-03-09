from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from paths import LOCAL_STATE_DIR

MASTER_KEY_ENV_VAR = "EVERYTHING_GRABBER_MASTER_KEY"
SECRET_PREFIX = "enc::"

_MASTER_KEY_CACHE: bytes | None = None


def _master_key_path() -> Path:
    return LOCAL_STATE_DIR / "master.key"


def _load_or_create_master_key() -> bytes:
    global _MASTER_KEY_CACHE
    if _MASTER_KEY_CACHE is not None:
        return _MASTER_KEY_CACHE

    env_value = (os.getenv(MASTER_KEY_ENV_VAR) or "").strip()
    if env_value:
        _MASTER_KEY_CACHE = env_value.encode("utf-8")
        return _MASTER_KEY_CACHE

    LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
    key_path = _master_key_path()
    if key_path.exists():
        _MASTER_KEY_CACHE = key_path.read_text(encoding="utf-8").strip().encode("utf-8")
        return _MASTER_KEY_CACHE

    generated = Fernet.generate_key()
    key_path.write_text(generated.decode("utf-8"), encoding="utf-8")
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    _MASTER_KEY_CACHE = generated
    return _MASTER_KEY_CACHE


def _cipher() -> Fernet:
    return Fernet(_load_or_create_master_key())


def encrypt_secret(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.startswith(SECRET_PREFIX):
        return text
    token = _cipher().encrypt(text.encode("utf-8")).decode("utf-8")
    return f"{SECRET_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if not text.startswith(SECRET_PREFIX):
        return text
    token = text[len(SECRET_PREFIX):]
    try:
        return _cipher().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt stored secret") from exc


def has_secret_value(value: str | None) -> bool:
    return decrypt_secret(value) is not None
