from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from auth import clear_session_cookie, extract_session_token, get_or_create_default_local_user, is_shortcut_bearer_token, reset_request_user_id, resolve_auth_session, set_request_user_id, touch_auth_session
from database import engine, Base, SessionLocal, ensure_runtime_schema, init_search_index
from routers import auth, connect, folders, ingest, items, phone_webapp, settings
import os
from paths import STATIC_DIR

# Create SQLite database tables
Base.metadata.create_all(bind=engine)
ensure_runtime_schema()
init_search_index()

app = FastAPI(title="Everything Grabber API", version="1.0.0")

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

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")
