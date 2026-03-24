import importlib
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)


@contextmanager
def load_paths_module(*, env: dict[str, str] | None = None, home_dir: Path | None = None):
    original_module = sys.modules.pop("paths", None)
    with tempfile.TemporaryDirectory() as temp_dir:
        patched_home = home_dir or (Path(temp_dir) / "home")
        patched_home.mkdir(parents=True, exist_ok=True)
        with patch.dict(os.environ, env or {}, clear=True), patch("pathlib.Path.home", return_value=patched_home):
            module = importlib.import_module("paths")
            try:
                yield module, patched_home
            finally:
                sys.modules.pop("paths", None)
                if original_module is not None:
                    sys.modules["paths"] = original_module


class PathsRuntimeTests(unittest.TestCase):
    def test_desktop_mode_uses_application_support_layout(self) -> None:
        with load_paths_module(env={"EC_APP_MODE": "desktop"}) as (paths_module, patched_home):
            expected_data_root = patched_home / "Library" / "Application Support" / "Everything Capture"
            expected_logs_dir = patched_home / "Library" / "Logs" / "Everything Capture"

            self.assertEqual(paths_module.DATA_ROOT, expected_data_root.resolve())
            self.assertEqual(paths_module.COMPONENTS_DIR, (expected_data_root / "components").resolve())
            self.assertEqual(paths_module.COMPONENTS_STATE_PATH, (expected_data_root / "components" / "installed.json").resolve())
            self.assertEqual(paths_module.TEMP_DIR, (expected_data_root / ".tmp").resolve())
            self.assertEqual(paths_module.COMPONENTS_TEMP_DIR, (expected_data_root / ".tmp" / "components").resolve())
            self.assertEqual(
                paths_module.BUNDLED_COMPONENTS_DIR,
                (paths_module.RESOURCES_ROOT / "desktop_runtime" / "components").resolve(),
            )
            self.assertEqual(paths_module.LOGS_DIR, expected_logs_dir.resolve())

    def test_explicit_runtime_paths_override_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            frontend_dir = temp_root / "desktop-frontend"
            runtime_bin_dir = temp_root / "runtime-bin"
            data_dir = temp_root / "data"

            env = {
                "EC_FRONTEND_DIR": str(frontend_dir),
                "EC_RUNTIME_BIN_DIR": str(runtime_bin_dir),
                "DATA_DIR": str(data_dir),
            }

            with load_paths_module(env=env) as (paths_module, _):
                self.assertEqual(paths_module.FRONTEND_DIR, frontend_dir.resolve())
                self.assertEqual(paths_module.RUNTIME_BIN_DIR, runtime_bin_dir.resolve())
                self.assertEqual(paths_module.DATA_ROOT, data_dir.resolve())

                paths_module.ensure_data_dirs()

                self.assertTrue(paths_module.COMPONENTS_DIR.exists())
                self.assertTrue(paths_module.COMPONENTS_TEMP_DIR.exists())
                self.assertTrue(paths_module.TEMP_DIR.exists())
                self.assertTrue(paths_module.LOGS_DIR.exists())


if __name__ == "__main__":
    unittest.main()
