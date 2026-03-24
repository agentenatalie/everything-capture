import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


DESKTOP_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = DESKTOP_DIR / "scripts"


def load_module(module_name: str, module_path: Path):
    if str(module_path.parent) not in sys.path:
        sys.path.insert(0, str(module_path.parent))

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


package_component = load_module("desktop_package_component_test", SCRIPTS_DIR / "package_component.py")
generate_release_manifest = load_module("desktop_generate_release_manifest_test", SCRIPTS_DIR / "generate_release_manifest.py")


class PackageComponentTests(unittest.TestCase):
    def test_create_component_archive_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_dir = temp_root / "source"
            (source_dir / "python").mkdir(parents=True, exist_ok=True)
            (source_dir / "python" / "demo_module.py").write_text("VALUE = 1\n", encoding="utf-8")

            archive_path = temp_root / "out" / "demo-component-1.2.3-macos-arm64.zip"
            package_component.create_component_archive(
                component_id="demo-component",
                version="1.2.3",
                source_dir=source_dir,
                archive_path=archive_path,
            )

            self.assertTrue(archive_path.exists())
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("demo-component-1.2.3/python/demo_module.py", archive.namelist())

            metadata = package_component.build_component_metadata(
                component_id="demo-component",
                title="Demo Component",
                description="Test payload",
                version="1.2.3",
                archive_path=archive_path,
                download_url="https://cdn.example.com/demo.zip",
                requires_restart=False,
                entry_python_paths=["python"],
                entry_bin_paths=[],
                platforms=["macos-arm64"],
            )

            self.assertEqual(metadata["id"], "demo-component")
            self.assertEqual(metadata["filename"], archive_path.name)
            self.assertEqual(metadata["download_url"], "https://cdn.example.com/demo.zip")
            self.assertGreater(metadata["size_bytes"], 0)
            self.assertTrue(metadata["sha256"])


class ReleaseManifestTests(unittest.TestCase):
    def test_build_release_manifest_payload_includes_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            dmg_path = temp_root / "EverythingCapture-1.0.0-arm64.dmg"
            dmg_path.write_bytes(b"dmg-bytes")

            component = {
                "id": "local-transcription",
                "version": "1.0.0",
                "download_url": "https://cdn.example.com/local-transcription.zip",
                "sha256": "abc123",
                "size_bytes": 42,
            }

            payload = generate_release_manifest.build_release_manifest_payload(
                dmg_path=dmg_path,
                version="1.0.0",
                download_url="https://cdn.example.com/EverythingCapture-1.0.0-arm64.dmg",
                components=[component],
            )

            self.assertEqual(payload["app"]["version"], "1.0.0")
            self.assertEqual(payload["components"][0]["id"], "local-transcription")
            self.assertIn("generated_at", payload)

    def test_build_components_manifest_payload_wraps_component_list(self) -> None:
        payload = generate_release_manifest.build_components_manifest_payload(
            [{"id": "local-transcription", "version": "1.0.0"}]
        )

        self.assertEqual(payload["manifest_version"], 1)
        self.assertEqual(payload["components"][0]["id"], "local-transcription")
        self.assertIn("generated_at", payload)


if __name__ == "__main__":
    unittest.main()
