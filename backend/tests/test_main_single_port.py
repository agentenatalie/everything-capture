import importlib
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
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
    def _create_item_with_media(self, item_id: str, media_id: str, *, storage_backend: str | None = None, storage_key: str | None = None):
        from database import SessionLocal
        from models import Item, Media

        with SessionLocal() as db:
            item = Item(id=item_id, title="Video Item", source_url="https://example.com/video", platform="web", status="ready")
            db.add(item)
            db.flush()
            media = Media(
                id=media_id,
                item_id=item.id,
                type="video",
                original_url="https://cdn.example.com/video.mp4",
                local_path=f"media/users/local-default-user/{item.id}/video_000.mp4",
                storage_backend=storage_backend,
                storage_key=storage_key,
                display_order=0,
            )
            db.add(media)
            db.commit()
        return {
            "id": media_id,
            "local_path": f"media/users/local-default-user/{item_id}/video_000.mp4",
        }

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

    def test_healthz_endpoint_reports_ready(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            with TestClient(main_module.app) as client:
                response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ok"], True)

    def test_static_media_route_is_not_shadowed_by_frontend_mount(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            with TestClient(main_module.app) as client:
                response = client.get("/static/media/does-not-exist.png")

        self.assertEqual(response.status_code, 404)

    def test_media_content_route_serves_local_video_file(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            import paths

            media = self._create_item_with_media("item-local-video", "media-local-video")
            local_file = paths.STATIC_DIR / media["local_path"]
            local_file.parent.mkdir(parents=True, exist_ok=True)
            local_file.write_bytes(b"local-video")

            with TestClient(main_module.app) as client:
                response = client.get(f"/api/media/{media['id']}/content")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"local-video")

    def test_media_content_route_redirects_remote_video(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            media = self._create_item_with_media(
                "item-remote-video",
                "media-remote-video",
                storage_backend="s3",
                storage_key="media/users/local-default-user/item-remote-video/video_000.mp4",
            )

            with patch("routers.items.media_read_redirect_url", return_value="https://example.com/presigned.mp4"):
                with TestClient(main_module.app) as client:
                    response = client.get(f"/api/media/{media['id']}/content", follow_redirects=False)

        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers.get("location"), "https://example.com/presigned.mp4")

    def test_delete_item_route_triggers_remote_media_cleanup(self) -> None:
        with load_main_with_temp_data_dir() as main_module:
            media = self._create_item_with_media(
                "item-delete-video",
                "media-delete-video",
                storage_backend="s3",
                storage_key="media/users/local-default-user/item-delete-video/video_000.mp4",
            )

            with patch("routers.items.delete_remote_media") as delete_remote_media:
                with TestClient(main_module.app) as client:
                    response = client.delete("/api/items/item-delete-video")

        self.assertEqual(response.status_code, 204)
        delete_remote_media.assert_called_once()


if __name__ == "__main__":
    unittest.main()
