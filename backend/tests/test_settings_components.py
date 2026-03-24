import importlib
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)


def create_component_manifest(temp_root: Path, *, version: str = "1.0.0") -> Path:
    package_root = temp_root / f"local-transcription-{version}" / "python"
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "mlx_whisper.py").write_text(
        "def transcribe(*args, **kwargs):\n"
        "    return {'text': 'api-test', 'segments': []}\n",
        encoding="utf-8",
    )

    archive_path = temp_root / f"local-transcription-{version}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in (temp_root / f"local-transcription-{version}").rglob("*"):
            archive.write(path, path.relative_to(temp_root))

    import hashlib

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    manifest_path = temp_root / "components-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "components": [
                    {
                        "id": "local-transcription",
                        "title": "Local Transcription",
                        "description": "Install local transcription runtime.",
                        "version": version,
                        "download_url": archive_path.as_uri(),
                        "sha256": digest,
                        "size_bytes": archive_path.stat().st_size,
                        "requires_restart": False,
                        "entry_python_paths": ["python"],
                        "entry_bin_paths": [],
                        "platforms": ["macos-arm64", "darwin", "linux"],
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def create_bundled_component_manifest(temp_root: Path, *, version: str = "1.0.0") -> tuple[Path, Path]:
    bundled_root = temp_root / "desktop-runtime-components" / "local-transcription" / version
    python_dir = bundled_root / "python"
    python_dir.mkdir(parents=True, exist_ok=True)
    (python_dir / "mlx_whisper.py").write_text(
        "def transcribe(*args, **kwargs):\n"
        "    return {'text': 'bundled-api-test', 'segments': []}\n",
        encoding="utf-8",
    )

    manifest_path = temp_root / "bundled-components-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "components": [
                    {
                        "id": "local-transcription",
                        "title": "Local Transcription",
                        "description": "Bundled local transcription runtime.",
                        "version": version,
                        "download_url": "",
                        "sha256": "",
                        "size_bytes": 0,
                        "requires_restart": False,
                        "entry_python_paths": ["python"],
                        "entry_bin_paths": [],
                        "platforms": ["macos-arm64", "darwin", "linux"],
                        "bundled": True,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path, bundled_root.parents[1]


@contextmanager
def load_main_with_component_manifest():
    module_names_to_clear = sorted(
        [
            name
            for name in list(sys.modules)
            if name in {
                "main",
                "paths",
                "database",
                "frontend_bridge",
                "models",
                "tenant",
                "security",
                "app_settings",
            }
            or name.startswith("routers")
            or name.startswith("services")
        ]
    )
    original_modules = {name: sys.modules.get(name) for name in module_names_to_clear}
    for name in module_names_to_clear:
        sys.modules.pop(name, None)

    loaded_module_names: list[str] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        data_dir = temp_root / "data"
        manifest_path = create_component_manifest(temp_root)
        env = {
            "DATA_DIR": str(data_dir),
            "EC_COMPONENTS_MANIFEST_PATH": str(manifest_path),
        }
        with patch_env(env):
            main_module = importlib.import_module("main")
            loaded_module_names = [
                name
                for name in list(sys.modules)
                if name in {
                    "main",
                    "paths",
                    "database",
                    "frontend_bridge",
                    "models",
                    "tenant",
                    "security",
                    "app_settings",
                }
                or name.startswith("routers")
                or name.startswith("services")
            ]
            try:
                yield main_module, data_dir
            finally:
                for name in loaded_module_names:
                    sys.modules.pop(name, None)
                for name, module in original_modules.items():
                    if module is not None:
                        sys.modules[name] = module
                sys.modules.pop("mlx_whisper", None)


@contextmanager
def load_main_with_bundled_component_manifest():
    module_names_to_clear = sorted(
        [
            name
            for name in list(sys.modules)
            if name in {
                "main",
                "paths",
                "database",
                "frontend_bridge",
                "models",
                "tenant",
                "security",
                "app_settings",
            }
            or name.startswith("routers")
            or name.startswith("services")
        ]
    )
    original_modules = {name: sys.modules.get(name) for name in module_names_to_clear}
    for name in module_names_to_clear:
        sys.modules.pop(name, None)

    loaded_module_names: list[str] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        data_dir = temp_root / "data"
        manifest_path, bundled_components_dir = create_bundled_component_manifest(temp_root)
        env = {
            "DATA_DIR": str(data_dir),
            "EC_COMPONENTS_MANIFEST_PATH": str(manifest_path),
            "EC_BUNDLED_COMPONENTS_DIR": str(bundled_components_dir),
        }
        with patch_env(env):
            main_module = importlib.import_module("main")
            loaded_module_names = [
                name
                for name in list(sys.modules)
                if name in {
                    "main",
                    "paths",
                    "database",
                    "frontend_bridge",
                    "models",
                    "tenant",
                    "security",
                    "app_settings",
                }
                or name.startswith("routers")
                or name.startswith("services")
            ]
            try:
                yield main_module, data_dir
            finally:
                for name in loaded_module_names:
                    sys.modules.pop(name, None)
                for name, module in original_modules.items():
                    if module is not None:
                        sys.modules[name] = module
                sys.modules.pop("mlx_whisper", None)


@contextmanager
def patch_env(values: dict[str, str]):
    original = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            os.environ[key] = value
        yield
    finally:
        for key, original_value in original.items():
            if original_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original_value


class SettingsComponentsApiTests(unittest.TestCase):
    def test_component_catalog_and_install_task_endpoints(self) -> None:
        with load_main_with_component_manifest() as (main_module, data_dir):
            with TestClient(main_module.app) as client:
                catalog_response = client.get("/api/settings/components")
                self.assertEqual(catalog_response.status_code, 200)
                catalog_payload = catalog_response.json()
                self.assertEqual(catalog_payload["components"][0]["status"], "not_installed")

                install_response = client.post("/api/settings/components/local-transcription/install")
                self.assertEqual(install_response.status_code, 202)
                task_payload = install_response.json()
                self.assertEqual(task_payload["component_id"], "local-transcription")

                deadline = time.monotonic() + 5
                final_task_payload = task_payload
                while time.monotonic() < deadline:
                    task_response = client.get(f"/api/settings/components/tasks/{task_payload['id']}")
                    self.assertEqual(task_response.status_code, 200)
                    final_task_payload = task_response.json()
                    if final_task_payload["status"] in {"completed", "failed"}:
                        break
                    time.sleep(0.05)

                self.assertEqual(final_task_payload["status"], "completed")

                refreshed_catalog = client.get("/api/settings/components")
                self.assertEqual(refreshed_catalog.status_code, 200)
                refreshed_payload = refreshed_catalog.json()
                self.assertEqual(refreshed_payload["components"][0]["status"], "installed")
                self.assertEqual(refreshed_payload["components"][0]["installed_version"], "1.0.0")

                state_path = data_dir / "components" / "installed.json"
                self.assertTrue(state_path.exists())

    def test_bundled_component_catalog_reports_installed_without_writing_state(self) -> None:
        with load_main_with_bundled_component_manifest() as (main_module, data_dir):
            with TestClient(main_module.app) as client:
                catalog_response = client.get("/api/settings/components")
                self.assertEqual(catalog_response.status_code, 200)
                component = catalog_response.json()["components"][0]
                self.assertTrue(component["bundled"])
                self.assertEqual(component["status"], "bundled")
                self.assertEqual(component["installed_version"], "1.0.0")

                install_response = client.post("/api/settings/components/local-transcription/install")
                self.assertEqual(install_response.status_code, 202)
                task_payload = install_response.json()
                self.assertEqual(task_payload["status"], "completed")
                self.assertEqual(task_payload["installed_version"], "1.0.0")

                state_path = data_dir / "components" / "installed.json"
                self.assertFalse(state_path.exists())


if __name__ == "__main__":
    unittest.main()
