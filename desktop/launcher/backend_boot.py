from __future__ import annotations

import os
import sys
from pathlib import Path


def _bootstrap_import_paths() -> None:
    backend_dir = (
        os.getenv("EC_BACKEND_DIR")
        or str(Path(__file__).resolve().parents[2] / "backend")
    ).strip()
    project_root = str(Path(backend_dir).resolve().parent)

    for path in (backend_dir, project_root):
        if path and path not in sys.path:
            sys.path.insert(0, path)


def run_backend_server() -> None:
    _bootstrap_import_paths()

    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("EC_BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("EC_BACKEND_PORT", "8000")),
        reload=False,
        log_level=os.getenv("EC_BACKEND_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    run_backend_server()
