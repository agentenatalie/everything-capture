import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from auth import clear_session_cookie, extract_session_token, get_or_create_default_local_user, is_shortcut_bearer_token, reset_request_user_id, resolve_auth_session, set_request_user_id, touch_auth_session
from database import engine, Base, SessionLocal, ensure_runtime_schema, init_search_index
from frontend_bridge import build_frontend_url
from routers import ai, auth, connect, folders, ingest, items, phone_webapp, settings
from paths import MEDIA_DIR

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

# Add CORS middleware for frontend-backend separation
app.add_middleware(
    CORSMiddleware,
    allow_origins=_configured_cors_origins(),
    allow_origin_regex=LOCAL_DEV_CORS_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def auth_session_middleware(request: Request, call_next):
    db = SessionLocal()
    context_token = set_request_user_id(None)
    request.state.auth_user = None
    request.state.auth_session = None
    try:
        raw_token = extract_session_token(request)
        auth_session, auth_user = resolve_auth_session(db, raw_token)
        if not auth_user and is_shortcut_bearer_token(raw_token):
            auth_user = get_or_create_default_local_user(db)
        should_clear_cookie = bool(raw_token and not auth_user)
        reset_request_user_id(context_token)
        context_token = set_request_user_id(auth_user.id if auth_user else None)
        if auth_user:
            request.state.auth_user = auth_user
            request.state.auth_session = auth_session
            touch_auth_session(auth_session)

        response = await call_next(request)
        if should_clear_cookie:
            clear_session_cookie(response)
        db.commit()
        return response
    finally:
        reset_request_user_id(context_token)
        db.close()

app.include_router(auth.router)
app.include_router(ingest.router)
app.include_router(phone_webapp.router)
app.include_router(items.router)
app.include_router(connect.router)
app.include_router(folders.router)
app.include_router(settings.router)
app.include_router(ai.router)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root(request: Request):
    return RedirectResponse(url=build_frontend_url(request, query_string=request.url.query))


# Mount media directory for uploaded files (still served by backend)
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/static/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
