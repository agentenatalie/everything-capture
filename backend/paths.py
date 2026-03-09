from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
DB_PATH = BACKEND_DIR / "items.db"
STATIC_DIR = BACKEND_DIR / "static"
MEDIA_DIR = STATIC_DIR / "media"
LOCAL_STATE_DIR = BACKEND_DIR / ".local"
