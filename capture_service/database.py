import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


CAPTURE_SERVICE_DIR = Path(__file__).resolve().parent
DATABASE_URL_ENV_KEYS = (
    "CAPTURE_SERVICE_DATABASE_URL",
    "DATABASE_URL",
)


def _normalize_database_url(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("postgres://"):
        return f"postgresql+psycopg://{normalized[len('postgres://'):]}"
    if normalized.startswith("postgresql://") and "+" not in normalized.split("://", 1)[0]:
        return f"postgresql+psycopg://{normalized[len('postgresql://'):]}"
    return normalized


def _build_database_url() -> str:
    for env_key in DATABASE_URL_ENV_KEYS:
        env_value = (os.environ.get(env_key) or "").strip()
        if env_value:
            return _normalize_database_url(env_value)

    db_path = Path(os.environ.get("CAPTURE_SERVICE_DB_PATH") or (CAPTURE_SERVICE_DIR / "capture.db")).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


DATABASE_URL = _build_database_url()


def get_storage_info() -> dict[str, object]:
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = DATABASE_URL.removeprefix("sqlite:///")
        return {
            "backend": "sqlite",
            "durable": not db_path.startswith("/tmp/"),
            "location": db_path,
        }

    backend = DATABASE_URL.split("://", 1)[0].split("+", 1)[0]
    return {
        "backend": backend,
        "durable": True,
        "location": "external",
    }


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
