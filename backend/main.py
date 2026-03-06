from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base, ensure_runtime_schema, init_search_index
from routers import ingest, items, connect, settings
import os
from paths import STATIC_DIR

# Create SQLite database tables
Base.metadata.create_all(bind=engine)
ensure_runtime_schema()
init_search_index()

app = FastAPI(title="Everything Grabber API", version="1.0.0")

app.include_router(ingest.router)
app.include_router(items.router)
app.include_router(connect.router)
app.include_router(settings.router)

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")
