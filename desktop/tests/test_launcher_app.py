import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


DESKTOP_DIR = Path(__file__).resolve().parents[1]
LAUNCHER_DIR = DESKTOP_DIR / "launcher"
LAUNCHER_APP_PATH = LAUNCHER_DIR / "app.py"


def load_launcher_app_module():
    if str(LAUNCHER_DIR) not in sys.path:
        sys.path.insert(0, str(LAUNCHER_DIR))

    module_name = "desktop_launcher_app_test"
    spec = importlib.util.spec_from_file_location(module_name, LAUNCHER_APP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load desktop launcher app module")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


launcher_app = load_launcher_app_module()


class LauncherAppTests(unittest.TestCase):
    def test_build_backend_env_uses_runtime_and_data_paths(self) -> None:
        runtime_root = Path("/tmp/runtime-root")
        repo_root = Path("/tmp/repo-root")
        data_dir = Path("/tmp/data-root")
        logs_dir = Path("/tmp/logs-root")

        with (
            patch.object(launcher_app, "_runtime_root", return_value=runtime_root),
            patch.object(launcher_app, "_repo_root", return_value=repo_root),
            patch.object(launcher_app, "_data_dir", return_value=data_dir),
            patch.object(launcher_app, "_logs_dir", return_value=logs_dir),
        ):
            env = launcher_app._build_backend_env(8123)

        self.assertEqual(env["EC_APP_MODE"], "desktop")
        self.assertEqual(env["EC_BACKEND_PORT"], "8123")
        self.assertEqual(env["DATA_DIR"], str(data_dir))
        self.assertEqual(env["EC_LOGS_DIR"], str(logs_dir))
        self.assertEqual(env["EC_RESOURCES_DIR"], str(runtime_root))
        self.assertEqual(env["EC_FRONTEND_DIR"], str(runtime_root / "frontend"))
        self.assertEqual(env["EC_RUNTIME_BIN_DIR"], str(runtime_root / "desktop_runtime" / "bin"))
        self.assertEqual(env["EC_BACKEND_DIR"], str(repo_root / "backend"))

    def test_error_page_path_prefers_bundled_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir)
            bundled_error_page = runtime_root / "desktop" / "launcher" / "error_page.html"
            bundled_error_page.parent.mkdir(parents=True, exist_ok=True)
            bundled_error_page.write_text("bundled", encoding="utf-8")

            with patch.object(launcher_app, "_runtime_root", return_value=runtime_root):
                self.assertEqual(launcher_app._error_page_path(), bundled_error_page)


if __name__ == "__main__":
    unittest.main()
