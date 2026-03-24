import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from paths import MEDIA_DIR, PROJECT_ROOT, ensure_data_dirs, migrate_legacy_data

# ---------------------------------------------------------------------------
# Bootstrap external data directory and migrate legacy data (before DB init)
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
ensure_data_dirs()
migrate_legacy_data()

from database import engine, Base, ensure_runtime_schema, init_search_index
from routers import ai, connect, folders, ingest, items, phone_webapp, settings

# Create SQLite database tables
Base.metadata.create_all(bind=engine)
ensure_runtime_schema()
init_search_index()

LOCAL_DEV_CORS_REGEX = (
    r"https?://("
    r"localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|\[::1\]|"
    r"10(?:\.\d{1,3}){3}|"
    r"192\.168(?:\.\d{1,3}){2}|"
    r"172\.(?:1[6-9]|2\d|3[0-1])(?:\.\d{1,3}){2}"
    r")(?::\d+)?$"
)


def _configured_cors_origins() -> list[str]:
    raw_values = [
        os.getenv("EVERYTHING_CAPTURE_FRONTEND_ORIGIN"),
        os.getenv("FRONTEND_ORIGIN"),
        os.getenv("EVERYTHING_CAPTURE_ALLOWED_ORIGINS"),
        os.getenv("FRONTEND_ORIGINS"),
    ]
    origins: list[str] = []
    for raw_value in raw_values:
        if not raw_value:
            continue
        origins.extend(
            origin.strip().rstrip("/")
            for origin in raw_value.split(",")
            if origin.strip()
        )
    return list(dict.fromkeys(origins))


app = FastAPI(title="Everything Capture API", version="1.0.0")

# GZip compress responses >= 500 bytes (big canonical_html payloads benefit a lot)
app.add_middleware(GZipMiddleware, minimum_size=500)

# Add CORS middleware for frontend-backend separation
app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_cors_origins(),
    allow_origin_regex=LOCAL_DEV_CORS_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "X-Visible-Count", "X-Returned-Count"],
)

app.include_router(ingest.router)
app.include_router(phone_webapp.router)
app.include_router(items.router)
app.include_router(connect.router)
app.include_router(folders.router)
app.include_router(settings.router)
app.include_router(ai.router)


@app.on_event("startup")
def startup_recover_processing_items() -> None:
    items.schedule_processing_item_parsing_recovery()


# Mount external media directory — keeps frontend URLs unchanged (/static/media/...)
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/static/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")

# Serve the static frontend from the same origin as the API.
app.mount("/", StaticFiles(directory=str(PROJECT_ROOT / "frontend"), html=True), name="frontend")
