from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sys
import threading
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import (
    BUNDLED_COMPONENTS_DIR,
    COMPONENTS_DIR,
    COMPONENTS_MANIFEST_PATH,
    COMPONENTS_STATE_PATH,
    COMPONENTS_TEMP_DIR,
)

logger = logging.getLogger(__name__)

COMPONENTS_MANIFEST_URL_ENV = "EC_COMPONENTS_MANIFEST_URL"
LOCAL_TRANSCRIPTION_COMPONENT_ID = "local-transcription"

_STATE_LOCK = threading.RLock()
_INSTALL_TASKS: dict[str, dict[str, Any]] = {}
_ACTIVE_TASKS_BY_COMPONENT: dict[str, str] = {}
_ACTIVATED_COMPONENT_VERSIONS: dict[str, str] = {}


class ComponentServiceError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runtime_platform() -> str:
    if sys.platform == "darwin" and os.uname().machine == "arm64":
        return "macos-arm64"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform


def _default_manifest_payload() -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "components": [
            {
                "id": LOCAL_TRANSCRIPTION_COMPONENT_ID,
                "title": "Local Transcription",
                "description": "为视频启用本地音频转录。组件包应提供 mlx-whisper 及其依赖的 Python 目录。",
                "version": "unconfigured",
                "download_url": "",
                "sha256": "",
                "size_bytes": 0,
                "requires_restart": False,
                "entry_python_paths": ["python"],
                "entry_bin_paths": [],
                "platforms": ["macos-arm64"],
                "unavailable_reason": "组件清单尚未配置下载地址。",
            }
        ],
    }


def _default_manifest_source() -> tuple[str, bool]:
    configured_url = (os.getenv(COMPONENTS_MANIFEST_URL_ENV) or "").strip()
    if configured_url:
        return configured_url, True

    if COMPONENTS_MANIFEST_PATH.is_file():
        return COMPONENTS_MANIFEST_PATH.as_uri(), True

    return "builtin://default-components-manifest", False


def _load_manifest_payload() -> tuple[dict[str, Any], str, bool]:
    source, configured = _default_manifest_source()

    if source.startswith("builtin://"):
        return _default_manifest_payload(), source, configured

    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"http", "https", "file"}:
        with urllib.request.urlopen(source, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload, source, configured

    path = Path(source).expanduser().resolve()
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), path.as_uri(), configured

    raise ComponentServiceError(f"Component manifest not found: {source}", status_code=500)


def _supports_platform(component: dict[str, Any]) -> bool:
    platforms = component.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        return True
    return _runtime_platform() in {str(value).strip() for value in platforms if str(value).strip()}


def _normalize_component_entry(raw_component: dict[str, Any]) -> dict[str, Any]:
    component_id = str(raw_component.get("id") or "").strip()
    latest_version = str(raw_component.get("version") or "").strip() or None
    download_url = str(raw_component.get("download_url") or "").strip() or None
    sha256 = str(raw_component.get("sha256") or "").strip() or None
    title = str(raw_component.get("title") or component_id).strip() or component_id
    description = str(raw_component.get("description") or "").strip()
    return {
        "id": component_id,
        "title": title,
        "description": description,
        "version": latest_version,
        "download_url": download_url,
        "sha256": sha256,
        "size_bytes": int(raw_component.get("size_bytes") or 0) or None,
        "requires_restart": bool(raw_component.get("requires_restart")),
        "entry_python_paths": [
            str(path).strip()
            for path in (raw_component.get("entry_python_paths") or [])
            if str(path).strip()
        ],
        "entry_bin_paths": [
            str(path).strip()
            for path in (raw_component.get("entry_bin_paths") or [])
            if str(path).strip()
        ],
        "unavailable_reason": str(raw_component.get("unavailable_reason") or "").strip() or None,
        "platforms": raw_component.get("platforms") or [],
        "bundled": bool(raw_component.get("bundled")),
    }


def _read_installed_state() -> dict[str, Any]:
    if not COMPONENTS_STATE_PATH.is_file():
        return {"components": {}}

    try:
        payload = json.loads(COMPONENTS_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read component state file %s: %s", COMPONENTS_STATE_PATH, exc)
        return {"components": {}}

    components = payload.get("components")
    if not isinstance(components, dict):
        return {"components": {}}
    return {"components": components}


def _write_installed_state(payload: dict[str, Any]) -> None:
    COMPONENTS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = COMPONENTS_STATE_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp_path, COMPONENTS_STATE_PATH)


def _component_parent_dir(component_id: str) -> Path:
    return COMPONENTS_DIR / component_id


def _component_version_dir(component_id: str, version: str) -> Path:
    return _component_parent_dir(component_id) / version


def _component_current_link(component_id: str) -> Path:
    return _component_parent_dir(component_id) / "current"


def _bundled_component_root(component_id: str, version: str | None) -> Path | None:
    if not version:
        return None
    candidate_names: list[str] = []
    for candidate_name in (version, version.replace(".", "__dot__")):
        if candidate_name and candidate_name not in candidate_names:
            candidate_names.append(candidate_name)

    for candidate_name in candidate_names:
        candidate = BUNDLED_COMPONENTS_DIR / component_id / candidate_name
        if candidate.exists():
            return candidate
    return None


def _is_bundled_component_root(component_root: Path) -> bool:
    try:
        component_root.resolve().relative_to(BUNDLED_COMPONENTS_DIR.resolve())
        return True
    except ValueError:
        return False


def _resolve_component_root(component_id: str, version: str | None = None) -> Path | None:
    parent_dir = _component_parent_dir(component_id)
    current_link = _component_current_link(component_id)

    if version:
        candidate = _component_version_dir(component_id, version)
        if candidate.exists():
            return candidate
        return _bundled_component_root(component_id, version)

    if current_link.exists():
        try:
            resolved = current_link.resolve(strict=True)
            if resolved.exists():
                return resolved
        except OSError:
            pass

    state = _read_installed_state()
    component_state = state.get("components", {}).get(component_id) or {}
    current_version = str(component_state.get("current_version") or "").strip()
    if not current_version:
        try:
            component, _source, _configured = _find_component_entry(component_id)
        except ComponentServiceError:
            return None
        if component.get("bundled"):
            return _bundled_component_root(component_id, component.get("version"))
        return None
    candidate = parent_dir / current_version
    if candidate.exists():
        return candidate
    return _bundled_component_root(component_id, current_version)


def _installed_or_bundled_version(component: dict[str, Any], component_state: dict[str, Any]) -> str | None:
    installed_version = str(component_state.get("current_version") or "").strip() or None
    if installed_version:
        return installed_version

    if component.get("bundled"):
        bundled_version = str(component.get("version") or "").strip() or None
        if bundled_version and _bundled_component_root(component["id"], bundled_version):
            return bundled_version

    return None


def _update_current_pointer(component_id: str, version: str) -> None:
    parent_dir = _component_parent_dir(component_id)
    parent_dir.mkdir(parents=True, exist_ok=True)
    current_link = _component_current_link(component_id)
    if current_link.is_symlink() or current_link.is_file():
        current_link.unlink()
    elif current_link.exists():
        shutil.rmtree(current_link)

    try:
        current_link.symlink_to(Path(version), target_is_directory=True)
    except OSError as exc:
        logger.warning("Failed to update component symlink for %s: %s", component_id, exc)


def _get_task_snapshot(task_id: str) -> dict[str, Any] | None:
    with _STATE_LOCK:
        task = _INSTALL_TASKS.get(task_id)
        return dict(task) if task else None


def _update_task(task_id: str, **changes: Any) -> dict[str, Any]:
    with _STATE_LOCK:
        if task_id not in _INSTALL_TASKS:
            raise KeyError(task_id)
        _INSTALL_TASKS[task_id].update(changes)
        _INSTALL_TASKS[task_id]["updated_at"] = _utcnow_iso()
        return dict(_INSTALL_TASKS[task_id])


def _find_component_entry(component_id: str) -> tuple[dict[str, Any], str, bool]:
    payload, source, configured = _load_manifest_payload()
    for raw_component in payload.get("components") or []:
        component = _normalize_component_entry(raw_component)
        if component["id"] == component_id and _supports_platform(component):
            return component, source, configured
    raise ComponentServiceError(f"Unknown component: {component_id}", status_code=404)


def get_install_task(task_id: str) -> dict[str, Any]:
    task = _get_task_snapshot(task_id)
    if not task:
        raise ComponentServiceError(f"Unknown install task: {task_id}", status_code=404)
    return task


def list_components() -> dict[str, Any]:
    payload, source, configured = _load_manifest_payload()
    state = _read_installed_state()
    state_components = state.get("components", {})

    components: list[dict[str, Any]] = []
    with _STATE_LOCK:
        task_snapshots = {
            component_id: dict(_INSTALL_TASKS[task_id])
            for component_id, task_id in _ACTIVE_TASKS_BY_COMPONENT.items()
            if task_id in _INSTALL_TASKS
        }

    for raw_component in payload.get("components") or []:
        component = _normalize_component_entry(raw_component)
        if not component["id"] or not _supports_platform(component):
            continue

        component_state = state_components.get(component["id"]) or {}
        installed_version = _installed_or_bundled_version(component, component_state)
        active_task = task_snapshots.get(component["id"])
        is_bundled = bool(
            component.get("bundled")
            and component.get("version")
            and _bundled_component_root(component["id"], component["version"])
        )
        available = bool(is_bundled or (component["download_url"] and component["version"]))
        status = "not_installed"
        if is_bundled:
            status = "bundled"
        elif not available:
            status = "unavailable"
        elif active_task and active_task.get("status") in {"pending", "running"}:
            status = "installing"
        elif installed_version and component["version"] and installed_version != component["version"]:
            status = "update_available"
        elif installed_version:
            status = "installed"

        components.append(
            {
                "id": component["id"],
                "title": component["title"],
                "description": component["description"],
                "available": available,
                "status": status,
                "latest_version": component["version"],
                "installed_version": installed_version,
                "download_url": component["download_url"],
                "download_size_bytes": component["size_bytes"],
                "requires_restart": component["requires_restart"],
                "unavailable_reason": component["unavailable_reason"],
                "bundled": is_bundled,
                "task": active_task,
            }
        )

    return {
        "platform": _runtime_platform(),
        "manifest_source": source,
        "manifest_configured": configured,
        "components": components,
    }


def _download_archive(download_url: str, destination: Path, *, task_id: str) -> None:
    _update_task(task_id, stage="downloading", message="正在下载组件包", progress=0.15, status="running")
    with urllib.request.urlopen(download_url, timeout=60) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)


def _sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_extracted_root(extract_dir: Path) -> Path:
    children = [child for child in extract_dir.iterdir() if child.name != "__MACOSX"]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def _validate_component_layout(component_root: Path, component: dict[str, Any]) -> None:
    missing_paths: list[str] = []
    for relative_path in component.get("entry_python_paths") or []:
        if not (component_root / relative_path).exists():
            missing_paths.append(relative_path)
    for relative_path in component.get("entry_bin_paths") or []:
        if not (component_root / relative_path).exists():
            missing_paths.append(relative_path)
    if missing_paths:
        raise ComponentServiceError(
            f"Component archive is missing required paths: {', '.join(sorted(missing_paths))}",
            status_code=400,
        )


def _record_installed_component(component: dict[str, Any]) -> None:
    component_id = component["id"]
    version = component["version"]
    assert component_id and version

    with _STATE_LOCK:
        state = _read_installed_state()
        state_components = state.setdefault("components", {})
        component_state = state_components.setdefault(component_id, {"versions": {}})
        versions = component_state.setdefault("versions", {})
        versions[version] = {
            "path": f"{component_id}/{version}",
            "source_url": component["download_url"],
            "sha256": component["sha256"],
            "size_bytes": component["size_bytes"],
            "installed_at": _utcnow_iso(),
            "entry_python_paths": component.get("entry_python_paths") or [],
            "entry_bin_paths": component.get("entry_bin_paths") or [],
            "requires_restart": bool(component.get("requires_restart")),
        }
        component_state["current_version"] = version
        _write_installed_state(state)

    _update_current_pointer(component_id, version)


def _install_component_task(task_id: str, component: dict[str, Any]) -> None:
    component_id = component["id"]
    version = component["version"]
    working_dir = COMPONENTS_TEMP_DIR / task_id
    archive_path = working_dir / "component.zip"
    extract_dir = working_dir / "extract"

    try:
        if not component.get("download_url") or not version:
            raise ComponentServiceError(
                component.get("unavailable_reason") or f"{component_id} is not downloadable",
                status_code=400,
            )

        working_dir.mkdir(parents=True, exist_ok=True)

        _download_archive(component["download_url"], archive_path, task_id=task_id)

        expected_sha256 = component.get("sha256")
        if expected_sha256:
            _update_task(task_id, stage="verifying", message="正在校验组件包", progress=0.4, status="running")
            actual_sha256 = _sha256sum(archive_path)
            if actual_sha256.lower() != str(expected_sha256).lower():
                raise ComponentServiceError(
                    f"SHA256 mismatch for {component_id}: expected {expected_sha256}, got {actual_sha256}",
                    status_code=400,
                )

        _update_task(task_id, stage="extracting", message="正在解压组件包", progress=0.65, status="running")
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)

        extracted_root = _resolve_extracted_root(extract_dir)
        _validate_component_layout(extracted_root, component)

        component_parent_dir = _component_parent_dir(component_id)
        component_parent_dir.mkdir(parents=True, exist_ok=True)
        final_dir = _component_version_dir(component_id, version)
        if not final_dir.exists():
            staging_target = working_dir / "staging"
            if staging_target.exists():
                shutil.rmtree(staging_target)
            shutil.move(str(extracted_root), str(staging_target))
            os.replace(staging_target, final_dir)

        _update_task(task_id, stage="activating", message="正在激活组件", progress=0.88, status="running")
        _record_installed_component(component)

        _update_task(
            task_id,
            status="completed",
            stage="completed",
            progress=1.0,
            message="组件安装完成",
            error=None,
            installed_version=version,
        )
    except ComponentServiceError as exc:
        logger.warning("Component install failed for %s: %s", component_id, exc.detail)
        _update_task(
            task_id,
            status="failed",
            stage="failed",
            progress=1.0,
            message="组件安装失败",
            error=exc.detail,
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Unexpected component install failure for %s", component_id)
        _update_task(
            task_id,
            status="failed",
            stage="failed",
            progress=1.0,
            message="组件安装失败",
            error=str(exc),
        )
    finally:
        shutil.rmtree(working_dir, ignore_errors=True)
        with _STATE_LOCK:
            if _ACTIVE_TASKS_BY_COMPONENT.get(component_id) == task_id:
                _ACTIVE_TASKS_BY_COMPONENT.pop(component_id, None)


def install_component(component_id: str) -> dict[str, Any]:
    component, _source, _configured = _find_component_entry(component_id)
    if component.get("bundled"):
        bundled_version = str(component.get("version") or "").strip() or None
        if bundled_version and _bundled_component_root(component_id, bundled_version):
            completed_at = _utcnow_iso()
            return {
                "id": f"bundled-{component_id}",
                "component_id": component_id,
                "status": "completed",
                "stage": "completed",
                "message": "组件已随应用内置",
                "error": None,
                "progress": 1.0,
                "latest_version": bundled_version,
                "installed_version": bundled_version,
                "requires_restart": False,
                "created_at": completed_at,
                "updated_at": completed_at,
            }

    with _STATE_LOCK:
        existing_task_id = _ACTIVE_TASKS_BY_COMPONENT.get(component_id)
        if existing_task_id and existing_task_id in _INSTALL_TASKS:
            return dict(_INSTALL_TASKS[existing_task_id])

        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "component_id": component_id,
            "status": "pending",
            "stage": "queued",
            "message": "组件安装已加入队列",
            "error": None,
            "progress": 0.0,
            "latest_version": component.get("version"),
            "installed_version": None,
            "requires_restart": bool(component.get("requires_restart")),
            "created_at": _utcnow_iso(),
            "updated_at": _utcnow_iso(),
        }
        _INSTALL_TASKS[task_id] = task
        _ACTIVE_TASKS_BY_COMPONENT[component_id] = task_id

    worker = threading.Thread(
        target=_install_component_task,
        args=(task_id, component),
        daemon=True,
        name=f"component-install-{component_id}",
    )
    worker.start()
    return dict(task)


def activate_component_runtime(component_id: str) -> bool:
    with _STATE_LOCK:
        state = _read_installed_state()
        component_state = state.get("components", {}).get(component_id) or {}
        current_version = str(component_state.get("current_version") or "").strip()

        version_record = (component_state.get("versions") or {}).get(current_version) or {}

    if not current_version:
        try:
            component, _source, _configured = _find_component_entry(component_id)
        except ComponentServiceError:
            return False
        if not component.get("bundled"):
            return False
        current_version = str(component.get("version") or "").strip()
        if not current_version:
            return False
        version_record = {
            "entry_python_paths": component.get("entry_python_paths") or [],
            "entry_bin_paths": component.get("entry_bin_paths") or [],
        }

    component_root = _resolve_component_root(component_id, current_version)
    if component_root is None:
        return False

    if _ACTIVATED_COMPONENT_VERSIONS.get(component_id) == current_version:
        return True

    if _is_bundled_component_root(component_root):
        sys.dont_write_bytecode = True
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    python_paths = version_record.get("entry_python_paths") or []
    for relative_path in python_paths:
        absolute_path = (component_root / relative_path).resolve()
        if absolute_path.exists():
            path_str = str(absolute_path)
            if path_str not in sys.path:
                sys.path.insert(0, path_str)

    bin_paths = version_record.get("entry_bin_paths") or []
    if bin_paths:
        current_path_entries = os.environ.get("PATH", "").split(os.pathsep)
        for relative_path in bin_paths:
            absolute_path = (component_root / relative_path).resolve()
            if absolute_path.exists():
                path_str = str(absolute_path)
                if path_str not in current_path_entries:
                    current_path_entries.insert(0, path_str)
        os.environ["PATH"] = os.pathsep.join(entry for entry in current_path_entries if entry)

    _ACTIVATED_COMPONENT_VERSIONS[component_id] = current_version
    return True


def reset_component_runtime_state_for_tests() -> None:
    with _STATE_LOCK:
        _INSTALL_TASKS.clear()
        _ACTIVE_TASKS_BY_COMPONENT.clear()
        _ACTIVATED_COMPONENT_VERSIONS.clear()
