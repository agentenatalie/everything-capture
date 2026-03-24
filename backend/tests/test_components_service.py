import hashlib
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
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)


def create_component_archive(temp_root: Path, *, version: str = "1.0.0") -> tuple[Path, Path]:
    package_root = temp_root / f"local-transcription-{version}"
    python_dir = package_root / "python"
    python_dir.mkdir(parents=True, exist_ok=True)
    (python_dir / "mlx_whisper.py").write_text(
        "def transcribe(*args, **kwargs):\n"
        "    return {'text': '测试转录', 'segments': [{'text': '测试转录'}]}\n",
        encoding="utf-8",
    )

    archive_path = temp_root / f"local-transcription-{version}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for path in package_root.rglob("*"):
            archive.write(path, path.relative_to(temp_root))

    sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
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
                        "sha256": sha256,
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
    return archive_path, manifest_path


def create_bundled_component(temp_root: Path, *, version: str = "1.0.0") -> tuple[Path, Path]:
    bundled_root = temp_root / "bundled-components" / "local-transcription" / version
    python_dir = bundled_root / "python"
    python_dir.mkdir(parents=True, exist_ok=True)
    (python_dir / "mlx_whisper.py").write_text(
        "def transcribe(*args, **kwargs):\n"
        "    return {'text': '内置转录', 'segments': [{'text': '内置转录'}]}\n",
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
    return bundled_root, manifest_path


@contextmanager
def configured_components_service():
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        components_dir = temp_root / "components"
        components_temp_dir = temp_root / "tmp-components"
        state_path = components_dir / "installed.json"
        archive_path, manifest_path = create_component_archive(temp_root)
        original_sys_path = list(sys.path)
        original_path_env = os.environ.get("PATH", "")

        import services.components as components_service

        with (
            patch.object(components_service, "COMPONENTS_DIR", components_dir.resolve()),
            patch.object(components_service, "COMPONENTS_STATE_PATH", state_path.resolve()),
            patch.object(components_service, "COMPONENTS_TEMP_DIR", components_temp_dir.resolve()),
            patch.object(components_service, "COMPONENTS_MANIFEST_PATH", manifest_path.resolve()),
            patch.dict(
                os.environ,
                {components_service.COMPONENTS_MANIFEST_URL_ENV: manifest_path.as_uri()},
                clear=False,
            ),
        ):
            components_service.reset_component_runtime_state_for_tests()
            sys.modules.pop("mlx_whisper", None)
            try:
                yield components_service, components_dir, state_path, archive_path
            finally:
                components_service.reset_component_runtime_state_for_tests()
                sys.modules.pop("mlx_whisper", None)
                sys.path[:] = original_sys_path
                os.environ["PATH"] = original_path_env


class ComponentsServiceTests(unittest.TestCase):
    def test_default_manifest_reports_unavailable_component_without_config(self) -> None:
        import services.components as components_service

        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(components_service, "COMPONENTS_DIR", Path(temp_dir) / "components"),
                patch.object(components_service, "COMPONENTS_STATE_PATH", Path(temp_dir) / "components" / "installed.json"),
                patch.object(components_service, "COMPONENTS_TEMP_DIR", Path(temp_dir) / "tmp-components"),
                patch.object(components_service, "COMPONENTS_MANIFEST_PATH", Path(temp_dir) / "missing.json"),
                patch.dict(os.environ, {components_service.COMPONENTS_MANIFEST_URL_ENV: ""}, clear=False),
            ):
                components_service.reset_component_runtime_state_for_tests()
                catalog = components_service.list_components()

        self.assertEqual(catalog["components"][0]["id"], "local-transcription")
        self.assertEqual(catalog["components"][0]["status"], "unavailable")
        self.assertFalse(catalog["components"][0]["available"])

    def test_install_component_updates_state_and_activates_python_paths(self) -> None:
        with configured_components_service() as (components_service, components_dir, state_path, _archive_path):
            catalog = components_service.list_components()
            self.assertEqual(catalog["components"][0]["status"], "not_installed")

            task = components_service.install_component("local-transcription")
            deadline = time.monotonic() + 5
            current_task = task
            while time.monotonic() < deadline:
                current_task = components_service.get_install_task(task["id"])
                if current_task["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.05)

            self.assertEqual(current_task["status"], "completed")
            self.assertTrue(state_path.exists())

            state_payload = json.loads(state_path.read_text(encoding="utf-8"))
            component_state = state_payload["components"]["local-transcription"]
            self.assertEqual(component_state["current_version"], "1.0.0")

            current_link = components_dir / "local-transcription" / "current"
            self.assertTrue(current_link.exists())
            self.assertEqual(current_link.resolve(), (components_dir / "local-transcription" / "1.0.0").resolve())

            activated = components_service.activate_component_runtime("local-transcription")
            self.assertTrue(activated)
            imported_module = importlib.import_module("mlx_whisper")
            self.assertEqual(imported_module.transcribe("demo")["text"], "测试转录")

            refreshed_catalog = components_service.list_components()
            self.assertEqual(refreshed_catalog["components"][0]["status"], "installed")
            self.assertEqual(refreshed_catalog["components"][0]["installed_version"], "1.0.0")

    def test_bundled_component_is_available_without_install_state(self) -> None:
        import services.components as components_service

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            components_dir = temp_root / "components"
            components_temp_dir = temp_root / "tmp-components"
            state_path = components_dir / "installed.json"
            bundled_root, manifest_path = create_bundled_component(temp_root)
            original_sys_path = list(sys.path)

            with (
                patch.object(components_service, "COMPONENTS_DIR", components_dir.resolve()),
                patch.object(components_service, "COMPONENTS_STATE_PATH", state_path.resolve()),
                patch.object(components_service, "COMPONENTS_TEMP_DIR", components_temp_dir.resolve()),
                patch.object(components_service, "COMPONENTS_MANIFEST_PATH", manifest_path.resolve()),
                patch.object(components_service, "BUNDLED_COMPONENTS_DIR", bundled_root.parents[1].resolve()),
                patch.dict(os.environ, {components_service.COMPONENTS_MANIFEST_URL_ENV: ""}, clear=False),
            ):
                components_service.reset_component_runtime_state_for_tests()
                sys.modules.pop("mlx_whisper", None)
                catalog = components_service.list_components()
                component = catalog["components"][0]
                self.assertTrue(component["bundled"])
                self.assertTrue(component["available"])
                self.assertEqual(component["status"], "bundled")
                self.assertEqual(component["installed_version"], "1.0.0")

                task = components_service.install_component("local-transcription")
                self.assertEqual(task["status"], "completed")
                self.assertEqual(task["installed_version"], "1.0.0")
                self.assertFalse(state_path.exists())

                activated = components_service.activate_component_runtime("local-transcription")
                self.assertTrue(activated)
                imported_module = importlib.import_module("mlx_whisper")
                self.assertEqual(imported_module.transcribe("demo")["text"], "内置转录")

                sys.modules.pop("mlx_whisper", None)
                sys.path[:] = original_sys_path


if __name__ == "__main__":
    unittest.main()
