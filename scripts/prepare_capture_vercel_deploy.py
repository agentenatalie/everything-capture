from __future__ import annotations

import argparse
import json
import os
import sqlite3
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CAPTURE_SOURCE_DIR = PROJECT_ROOT / "capture_service"
BACKEND_STATIC_DIR = PROJECT_ROOT / "backend" / "static"

# Use the external data directory (same resolution as backend/paths.py)
_DATA_ROOT = Path(
    os.getenv("DATA_DIR")
    or str(PROJECT_ROOT.parent / "everything-capture-data")
).resolve()
BACKEND_DB_PATH = Path(os.getenv("SQLITE_PATH") or str(_DATA_ROOT / "app.db"))

DEPLOY_REQUIREMENTS = """fastapi==0.135.1
sqlalchemy==2.0.47
pydantic==2.12.5
uvicorn==0.41.0
httpx==0.28.1
psycopg[binary]==3.2.12
"""

VERCEL_JSON = """{
  "version": 2,
  "builds": [
    {
      "src": "api/index.py",
      "use": "@vercel/python"
    }
  ],
  "routes": [
    {
      "src": "/(.*)",
      "dest": "api/index.py"
    }
  ]
}
"""

API_INDEX = """import os

if not ((os.environ.get("CAPTURE_SERVICE_DATABASE_URL") or "").strip() or (os.environ.get("DATABASE_URL") or "").strip()):
    os.environ.setdefault("CAPTURE_SERVICE_DB_PATH", "/tmp/capture.db")

from capture_service.api import app
"""

README = """# Vercel Capture Deploy Package

This folder is generated from `/capture_service`.

Notes:
- It deploys only the capture layer.
- If neither `CAPTURE_SERVICE_DATABASE_URL` nor `DATABASE_URL` is set, it defaults `CAPTURE_SERVICE_DB_PATH` to `/tmp/capture.db` on Vercel so preview deploys can boot.
- `/tmp` is not durable storage. For real usage, set `CAPTURE_SERVICE_DATABASE_URL` or `DATABASE_URL` to a durable database before production.
"""


def copy_capture_service(destination_root: Path) -> None:
    target_package_dir = destination_root / "capture_service"
    target_package_dir.mkdir(parents=True, exist_ok=True)

    for source_path in CAPTURE_SOURCE_DIR.iterdir():
        if source_path.name in {"__pycache__", "tests", "README.md"}:
            continue
        destination_path = target_package_dir / source_path.name
        if source_path.is_dir():
            shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
        else:
            shutil.copy2(source_path, destination_path)


def write_support_files(destination_root: Path) -> None:
    (destination_root / "api").mkdir(parents=True, exist_ok=True)
    (destination_root / "api" / "index.py").write_text(API_INDEX, encoding="utf-8")
    (destination_root / "requirements.txt").write_text(DEPLOY_REQUIREMENTS, encoding="utf-8")
    (destination_root / "vercel.json").write_text(VERCEL_JSON, encoding="utf-8")
    (destination_root / "README.md").write_text(README, encoding="utf-8")


def copy_exact_mobile_css(destination_root: Path) -> None:
    target_css_dir = destination_root / "capture_service" / "static"
    target_css_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BACKEND_STATIC_DIR / "css" / "index.css", target_css_dir / "index.css")


def export_folder_seed(destination_root: Path) -> None:
    folder_seed_path = destination_root / "capture_service" / "folder_seed.json"
    if not BACKEND_DB_PATH.exists():
        folder_seed_path.write_text("[]", encoding="utf-8")
        return

    connection = sqlite3.connect(BACKEND_DB_PATH)
    try:
        rows = connection.execute(
            """
            SELECT name, created_at, updated_at
            FROM folders
            ORDER BY updated_at DESC, created_at DESC, name ASC
            """
        ).fetchall()
    finally:
        connection.close()

    payload = [
        {
            "name": row[0],
            "created_at": row[1],
            "updated_at": row[2],
        }
        for row in rows
        if row[0]
    ]
    folder_seed_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a Vercel deployable package for capture_service only.")
    parser.add_argument("output_dir", help="Directory to write the deployable package into.")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copy_capture_service(output_dir)
    write_support_files(output_dir)
    copy_exact_mobile_css(output_dir)
    export_folder_seed(output_dir)

    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
