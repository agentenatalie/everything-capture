import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


CAPTURE_SERVICE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("CAPTURE_SERVICE_DB_PATH") or (CAPTURE_SERVICE_DIR / "capture.db"))

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
