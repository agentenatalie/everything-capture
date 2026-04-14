from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
APP_MODE = (os.getenv("EC_APP_MODE") or "").strip().lower()
IS_DESKTOP_MODE = APP_MODE == "desktop"
APP_NAME = (os.getenv("EC_APP_NAME") or "Everything Capture").strip() or "Everything Capture"


def _default_resources_root() -> Path:
    configured = (os.getenv("EC_RESOURCES_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return PROJECT_ROOT


def _default_data_root() -> Path:
    configured = (os.getenv("DATA_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    if IS_DESKTOP_MODE:
        return (Path.home() / "Library" / "Application Support" / APP_NAME).resolve()

    return (PROJECT_ROOT.parent / "everything-capture-data").resolve()


RESOURCES_ROOT = _default_resources_root()
FRONTEND_DIR = Path(
    os.getenv("EC_FRONTEND_DIR")
    or str(RESOURCES_ROOT / "frontend")
).expanduser().resolve()
RUNTIME_BIN_DIR = Path(
    os.getenv("EC_RUNTIME_BIN_DIR")
    or str(RESOURCES_ROOT / "desktop_runtime" / "bin")
).expanduser().resolve()
BUNDLED_COMPONENTS_DIR = Path(
    os.getenv("EC_BUNDLED_COMPONENTS_DIR")
    or str(RESOURCES_ROOT / "desktop_runtime" / "components")
).expanduser().resolve()

# ---------------------------------------------------------------------------
# External data directory (code/data separation)
# ---------------------------------------------------------------------------
# Default: ../everything-capture-data  (sibling of the project directory)
# Override via DATA_DIR environment variable.
DATA_ROOT = _default_data_root()

DB_PATH = Path(os.getenv("SQLITE_PATH") or str(DATA_ROOT / "app.db"))
MEDIA_DIR = Path(os.getenv("MEDIA_DIR") or str(DATA_ROOT / "media"))
EXPORTS_DIR = Path(os.getenv("EXPORTS_DIR") or str(DATA_ROOT / "exports"))
LOCAL_STATE_DIR = Path(os.getenv("EC_LOCAL_STATE_DIR") or str(DATA_ROOT / ".local")).resolve()
COMPONENTS_DIR = Path(os.getenv("EC_COMPONENTS_DIR") or str(DATA_ROOT / "components")).resolve()
TEMP_DIR = Path(os.getenv("EC_TEMP_DIR") or str(DATA_ROOT / ".tmp")).resolve()
COMPONENTS_STATE_PATH = Path(
    os.getenv("EC_COMPONENTS_STATE_PATH")
    or str(COMPONENTS_DIR / "installed.json")
).expanduser().resolve()
COMPONENTS_TEMP_DIR = Path(
    os.getenv("EC_COMPONENTS_TEMP_DIR")
    or str(TEMP_DIR / "components")
).expanduser().resolve()
COMPONENTS_MANIFEST_PATH = Path(
    os.getenv("EC_COMPONENTS_MANIFEST_PATH")
    or str(RESOURCES_ROOT / "desktop" / "spec" / "components-manifest.json")
).expanduser().resolve()
LOGS_DIR = Path(
    os.getenv("EC_LOGS_DIR")
    or str((Path.home() / "Library" / "Logs" / APP_NAME) if IS_DESKTOP_MODE else (DATA_ROOT / "logs"))
).expanduser().resolve()
MEDIA_STORAGE_BACKEND = (os.getenv("EC_MEDIA_STORAGE_BACKEND") or "local").strip().lower() or "local"
MEDIA_OFFLOAD_TYPES = frozenset(
    part.strip().lower()
    for part in (os.getenv("EC_MEDIA_OFFLOAD_TYPES") or "video").split(",")
    if part.strip()
)
MEDIA_S3_BUCKET = (os.getenv("EC_MEDIA_S3_BUCKET") or "").strip()
MEDIA_S3_ENDPOINT = (os.getenv("EC_MEDIA_S3_ENDPOINT") or "").strip()
MEDIA_S3_REGION = (os.getenv("EC_MEDIA_S3_REGION") or "auto").strip() or "auto"
MEDIA_S3_ACCESS_KEY_ID = (os.getenv("EC_MEDIA_S3_ACCESS_KEY_ID") or "").strip()
MEDIA_S3_SECRET_ACCESS_KEY = (os.getenv("EC_MEDIA_S3_SECRET_ACCESS_KEY") or "").strip()
MEDIA_SIGNED_URL_TTL_SECONDS = max(60, int(os.getenv("EC_MEDIA_SIGNED_URL_TTL_SECONDS", "900")))

# Backward-compatible alias: existing code does `STATIC_DIR / local_path` where
# local_path = "media/users/{uid}/{item_id}/file.jpg".  Since DATA_ROOT contains
# the "media/" sub-directory, STATIC_DIR = DATA_ROOT makes the resolution correct.
STATIC_DIR = DATA_ROOT

# ---------------------------------------------------------------------------
# Legacy paths (used for one-time migration)
# ---------------------------------------------------------------------------
_OLD_DB_PATH = BACKEND_DIR / "items.db"
_OLD_MEDIA_DIR = BACKEND_DIR / "static" / "media"
_OLD_LOCAL_STATE_DIR = BACKEND_DIR / ".local"


def ensure_data_dirs() -> None:
    """Create the external data directory tree if it doesn't exist."""
    for d in (
        DATA_ROOT,
        MEDIA_DIR,
        EXPORTS_DIR,
        LOCAL_STATE_DIR,
        COMPONENTS_DIR,
        TEMP_DIR,
        COMPONENTS_TEMP_DIR,
        LOGS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data() -> None:
    """Migrate data from old in-project locations to the external data directory.

    - Copies (not moves) files so the old data is preserved as a safety net.
    - Skips migration if the destination already has data.
    """
    _migrate_local_state()
    _migrate_database()
    _migrate_media()


def _migrate_local_state() -> None:
    if not _OLD_LOCAL_STATE_DIR.exists():
        return
    master_key_src = _OLD_LOCAL_STATE_DIR / "master.key"
    master_key_dst = LOCAL_STATE_DIR / "master.key"
    if master_key_src.exists() and not master_key_dst.exists():
        LOCAL_STATE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(master_key_src), str(master_key_dst))
        os.chmod(str(master_key_dst), 0o600)
        logger.info("Migrated master.key -> %s", master_key_dst)


def _migrate_database() -> None:
    if _OLD_DB_PATH.exists() and not DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(_OLD_DB_PATH), str(DB_PATH))
        # Also copy WAL/SHM if present
        for suffix in ("-wal", "-shm"):
            wal = _OLD_DB_PATH.with_name(_OLD_DB_PATH.name + suffix)
            if wal.exists():
                shutil.copy2(str(wal), str(DB_PATH.with_name(DB_PATH.name + suffix)))
        logger.info("Migrated database -> %s", DB_PATH)


def _migrate_media() -> None:
    if not _OLD_MEDIA_DIR.exists():
        return
    # Only migrate if the new media dir is empty (no "users" sub-dir yet)
    if (MEDIA_DIR / "users").exists():
        return
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    for child in _OLD_MEDIA_DIR.iterdir():
        dst = MEDIA_DIR / child.name
        if dst.exists():
            continue
        if child.is_dir():
            shutil.copytree(str(child), str(dst))
        else:
            shutil.copy2(str(child), str(dst))
    logger.info("Migrated media -> %s", MEDIA_DIR)
