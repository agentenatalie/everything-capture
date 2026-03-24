import importlib
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi.testclient import TestClient


BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND_DIR)


@contextmanager
def load_main_with_temp_data_dir():
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

    with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {"DATA_DIR": temp_dir}, clear=False):
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
            yield main_module
        finally:
            for name in loaded_module_names:
                sys.modules.pop(name, None)
            for name, module in original_modules.items():
                if module is not None:
                    sys.modules[name] = module


class MainSinglePortTests(unittest.TestCase):
    def test_root_serves_frontend_html(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            with TestClient(main_module.app) as client:
                response = client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Everything Capture - 收录看板", response.text)
        self.assertIn('id="commandOverlay"', response.text)

    def test_frontend_assets_are_served_from_same_origin(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            with TestClient(main_module.app) as client:
                response = client.get("/css/index.css")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/css", response.headers.get("content-type", ""))
        self.assertIn(".board-shell", response.text)

    def test_api_routes_still_win_over_frontend_mount(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            with TestClient(main_module.app) as client:
                response = client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("ai_model_options", payload)
        self.assertIn("ai_base_url", payload)

    def test_static_media_route_is_not_shadowed_by_frontend_mount(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            with TestClient(main_module.app) as client:
                response = client.get("/static/media/does-not-exist.png")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
