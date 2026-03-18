import os
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Settings  # noqa: E402
from security import decrypt_secret, encrypt_secret  # noqa: E402
from routers.connect import (  # noqa: E402
    ObsidianTestRequest,
    _normalize_obsidian_folder_path,
    _resolve_request_value,
)
from routers.settings import _build_settings_response  # noqa: E402


class SettingsSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_secret_encryption_round_trip(self) -> None:
        encrypted = encrypt_secret("secret-token")

        self.assertIsNotNone(encrypted)
        self.assertNotEqual(encrypted, "secret-token")
        self.assertEqual(decrypt_secret(encrypted), "secret-token")

    def test_build_settings_response_hides_saved_secrets(self) -> None:
        settings = Settings(
            notion_api_token=encrypt_secret("secret-token"),
            notion_database_id="12345678-1234-1234-1234-1234567890ab",
            notion_client_id="client-id",
            notion_client_secret=encrypt_secret("client-secret"),
            notion_redirect_uri="http://localhost:8000/api/connect/notion/oauth/callback",
            obsidian_rest_api_url="https://127.0.0.1:27124",
            obsidian_api_key=encrypt_secret("obsidian-secret"),
            obsidian_folder_path="EverythingCapture/Inbox",
            auto_sync_target="both",
        )
        with self.Session() as db:
            response = _build_settings_response(settings, db)

        self.assertIsNone(response.notion_api_token)
        self.assertTrue(response.notion_api_token_saved)
        self.assertIsNone(response.notion_client_secret)
        self.assertTrue(response.notion_client_secret_saved)
        self.assertIsNone(response.obsidian_api_key)
        self.assertTrue(response.obsidian_api_key_saved)
        self.assertTrue(response.notion_ready)
        self.assertTrue(response.obsidian_ready)

    def test_build_settings_response_reports_missing_secret_fields(self) -> None:
        settings = Settings(
            notion_database_id="12345678-1234-1234-1234-1234567890ab",
            obsidian_rest_api_url="https://127.0.0.1:27124",
        )
        with self.Session() as db:
            response = _build_settings_response(settings, db)

        self.assertFalse(response.notion_ready)
        self.assertIn("notion_api_token", response.notion_missing_fields)
        self.assertFalse(response.obsidian_ready)
        self.assertIn("obsidian_api_key", response.obsidian_missing_fields)

    def test_obsidian_test_request_uses_saved_key_when_secret_is_omitted(self) -> None:
        request = ObsidianTestRequest(
            obsidian_rest_api_url=" https://127.0.0.1:27124 ",
            obsidian_folder_path="",
        )

        resolved_url = _resolve_request_value(
            request,
            "obsidian_rest_api_url",
            "http://localhost:27124",
        )
        resolved_key = _resolve_request_value(
            request,
            "obsidian_api_key",
            " saved-key ",
        )
        resolved_folder = _normalize_obsidian_folder_path(
            _resolve_request_value(
                request,
                "obsidian_folder_path",
                "EverythingCapture/Inbox",
                normalizer=lambda value: value.strip() if isinstance(value, str) else value,
            )
        )

        self.assertEqual(resolved_url, "https://127.0.0.1:27124")
        self.assertEqual(resolved_key, "saved-key")
        self.assertIsNone(resolved_folder)


if __name__ == "__main__":
    unittest.main()
