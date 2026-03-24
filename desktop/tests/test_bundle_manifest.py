import importlib.util
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path


DESKTOP_DIR = Path(__file__).resolve().parents[1]
SPEC_DIR = DESKTOP_DIR / "spec"
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


bundle_manifest = load_module("desktop_bundle_manifest_test", SPEC_DIR / "bundle_manifest.py")
verify_app_bundle = load_module("desktop_verify_app_bundle_test", SCRIPTS_DIR / "verify_app_bundle.py")


class BundleManifestTests(unittest.TestCase):
    def test_required_source_entries_exist_in_repo(self) -> None:
        project_root = DESKTOP_DIR.parent
        required_entries = bundle_manifest.required_source_entries(project_root, DESKTOP_DIR)

        missing_entries = [entry.source for entry in required_entries if entry.required and not entry.source.exists()]
        self.assertEqual(missing_entries, [])

    def test_verify_app_bundle_accepts_expected_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = Path(temp_dir) / "Everything Capture.app"
            bundle_root = app_path / "Contents" / "MacOS"
            bundle_root.mkdir(parents=True, exist_ok=True)

            plist_path = app_path / "Contents" / "Info.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "CFBundleExecutable": "EverythingCapture",
                        "CFBundleShortVersionString": "1.2.3",
                    }
                )
            )

            executable_path = bundle_root / "EverythingCapture"
            executable_path.write_text("#!/bin/sh\n", encoding="utf-8")
            for entry in bundle_manifest.bundle_data_entries(DESKTOP_DIR.parent, DESKTOP_DIR) + bundle_manifest.runtime_bundle_entries(DESKTOP_DIR):
                target_path = bundle_root / Path(entry.bundle_path)
                if entry.source.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text("placeholder", encoding="utf-8")

            verify_app_bundle.verify_app_bundle(app_path, version="1.2.3")

    def test_verify_app_bundle_reports_missing_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            app_path = Path(temp_dir) / "Everything Capture.app"
            bundle_root = app_path / "Contents" / "MacOS"
            bundle_root.mkdir(parents=True, exist_ok=True)

            plist_path = app_path / "Contents" / "Info.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_bytes(
                plistlib.dumps(
                    {
                        "CFBundleExecutable": "EverythingCapture",
                        "CFBundleShortVersionString": "2.0.0",
                    }
                )
            )

            (bundle_root / "EverythingCapture").write_text("#!/bin/sh\n", encoding="utf-8")
            for entry in bundle_manifest.bundle_data_entries(DESKTOP_DIR.parent, DESKTOP_DIR) + bundle_manifest.runtime_bundle_entries(DESKTOP_DIR):
                if entry.bundle_path == "desktop_runtime/bin/ffmpeg":
                    continue
                target_path = bundle_root / Path(entry.bundle_path)
                if entry.source.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                else:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text("placeholder", encoding="utf-8")

            with self.assertRaises(verify_app_bundle.BundleVerificationError) as context:
                verify_app_bundle.verify_app_bundle(app_path, version="2.0.0")

            self.assertIn("desktop_runtime/bin/ffmpeg", str(context.exception))


if __name__ == "__main__":
    unittest.main()
