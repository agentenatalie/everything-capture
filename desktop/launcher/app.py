"""Everything Capture — macOS desktop launcher.

This software is licensed under Elastic License 2.0; see the LICENSE file.
Unauthorized use for hosted or managed services is strictly prohibited.
For commercial or SaaS licensing, contact:
https://github.com/agentenatalie
"""
from __future__ import annotations

import atexit
import html
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from backend_boot import run_backend_server

APP_NAME = "Everything Capture"
BACKEND_ARG = "--desktop-backend"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = int(os.getenv("EC_BACKEND_PORT", "8000"))
STARTUP_TIMEOUT_SECONDS = float(os.getenv("EC_DESKTOP_STARTUP_TIMEOUT", "30"))
HEALTHZ_POLL_INTERVAL_SECONDS = 0.25


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent)).resolve()
    return _repo_root()


def _data_dir() -> Path:
    configured = (os.getenv("DATA_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Library" / "Application Support" / APP_NAME).resolve()


def _logs_dir() -> Path:
    configured = (os.getenv("EC_LOGS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Library" / "Logs" / APP_NAME).resolve()


def _launcher_log_path() -> Path:
    return _logs_dir() / "launcher.log"


def _backend_log_path() -> Path:
    return _logs_dir() / "backend.log"


def _error_page_path() -> Path:
    runtime_root = _runtime_root()
    bundled_error_page = runtime_root / "desktop" / "launcher" / "error_page.html"
    if bundled_error_page.is_file():
        return bundled_error_page
    return Path(__file__).with_name("error_page.html")


def _write_launcher_log(message: str) -> None:
    log_path = _launcher_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def _build_backend_env(port: int) -> dict[str, str]:
    runtime_root = _runtime_root()
    repo_root = _repo_root()
    env = os.environ.copy()
    env["EC_APP_MODE"] = "desktop"
    env["EC_BACKEND_HOST"] = BACKEND_HOST
    env["EC_BACKEND_PORT"] = str(port)
    env["RUN_RELOAD"] = "0"
    env["DATA_DIR"] = str(_data_dir())
    env["EC_LOGS_DIR"] = str(_logs_dir())
    env["EC_RESOURCES_DIR"] = str(runtime_root)
    env["EC_FRONTEND_DIR"] = str(runtime_root / "frontend")
    env["EC_RUNTIME_BIN_DIR"] = str(runtime_root / "desktop_runtime" / "bin")
    env["EC_BACKEND_DIR"] = str(repo_root / "backend")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _backend_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, BACKEND_ARG]
    return [sys.executable, str(Path(__file__).resolve()), BACKEND_ARG]


def _start_backend_process(port: int) -> subprocess.Popen[bytes]:
    backend_log = _backend_log_path()
    backend_log.parent.mkdir(parents=True, exist_ok=True)
    backend_log.touch(exist_ok=True)

    _write_launcher_log(f"Starting backend on {BACKEND_HOST}:{port}")
    with backend_log.open("ab") as handle:
        process = subprocess.Popen(
            _backend_command(),
            env=_build_backend_env(port),
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return process


def _wait_for_backend(process: subprocess.Popen[bytes], port: int) -> tuple[bool, str]:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    healthz_url = f"http://{BACKEND_HOST}:{port}/healthz"

    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False, f"Backend exited early with code {process.returncode}."

        try:
            with urllib.request.urlopen(healthz_url, timeout=1) as response:
                if response.status == 200:
                    return True, "ready"
        except (urllib.error.URLError, TimeoutError):
            time.sleep(HEALTHZ_POLL_INTERVAL_SECONDS)

    return False, f"Timed out waiting for {healthz_url}."


def _terminate_backend_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return

    _write_launcher_log("Stopping backend process")

    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass


def _render_error_html(detail: str, log_path: Path) -> str:
    template_path = _error_page_path()
    template = template_path.read_text(encoding="utf-8")
    return (
        template
        .replace("__DETAIL__", html.escape(detail))
        .replace("__LOG_PATH__", html.escape(str(log_path)))
    )


def _show_error_window(detail: str) -> None:
    import webview

    window = webview.create_window(
        APP_NAME,
        html=_render_error_html(detail, _backend_log_path()),
        width=760,
        height=560,
        min_size=(640, 480),
    )
    webview.start()


def _show_main_window(port: int, process: subprocess.Popen[bytes]) -> None:
    import webview

    atexit.register(_terminate_backend_process, process)
    webview.create_window(
        APP_NAME,
        url=f"http://{BACKEND_HOST}:{port}",
        width=1360,
        height=900,
        min_size=(1024, 720),
    )
    try:
        webview.start()
    finally:
        _terminate_backend_process(process)


def _run_desktop_launcher() -> int:
    _data_dir().mkdir(parents=True, exist_ok=True)
    _logs_dir().mkdir(parents=True, exist_ok=True)

    backend_process = _start_backend_process(BACKEND_PORT)
    ready, detail = _wait_for_backend(backend_process, BACKEND_PORT)

    if not ready:
        _terminate_backend_process(backend_process)
        _show_error_window(detail)
        return 1

    _show_main_window(BACKEND_PORT, backend_process)
    return 0


def main() -> int:
    if BACKEND_ARG in sys.argv:
        run_backend_server()
        return 0
    return _run_desktop_launcher()


if __name__ == "__main__":
    raise SystemExit(main())
