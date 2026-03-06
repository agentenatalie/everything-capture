from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from database import engine, Base
from routers import ingest, items, connect, settings
import os

# Create SQLite database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Everything Grabber API", version="1.0.0")

app.include_router(ingest.router)
app.include_router(items.router)
app.include_router(connect.router)
app.include_router(settings.router)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")
