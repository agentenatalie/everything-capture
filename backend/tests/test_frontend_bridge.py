import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from frontend_bridge import build_frontend_url, resolve_frontend_origin  # noqa: E402


class FrontendBridgeTests(unittest.TestCase):
    def test_resolve_frontend_origin_uses_request_origin(self) -> None:
        request = SimpleNamespace(
            headers={"host": "192.168.1.99:8000"},
            url=SimpleNamespace(scheme="http", hostname="192.168.1.99", port=8000),
        )

        self.assertEqual(resolve_frontend_origin(request), "http://192.168.1.99:8000")

    def test_resolve_frontend_origin_prefers_explicit_origin_env(self) -> None:
        request = SimpleNamespace(
            headers={"host": "127.0.0.1:8000"},
            url=SimpleNamespace(scheme="http", hostname="127.0.0.1", port=8000),
        )

        with patch.dict(
            os.environ,
            {"EVERYTHING_CAPTURE_FRONTEND_ORIGIN": "https://capture.example.com"},
            clear=False,
        ):
            self.assertEqual(resolve_frontend_origin(request), "https://capture.example.com")

    def test_build_frontend_url_preserves_query_string(self) -> None:
        request = SimpleNamespace(
            headers={"host": "localhost:8000"},
            url=SimpleNamespace(scheme="http", hostname="localhost", port=8000),
        )

        self.assertEqual(
            build_frontend_url(request, query_string="notion_auth=success&from=oauth"),
            "http://localhost:8000/?notion_auth=success&from=oauth",
        )

    def test_resolve_frontend_origin_does_not_force_port_when_request_has_none(self) -> None:
        request = SimpleNamespace(
            headers={"host": "capture.example.com"},
            url=SimpleNamespace(scheme="https", hostname="capture.example.com", port=None),
        )

        self.assertEqual(resolve_frontend_origin(request), "https://capture.example.com")


if __name__ == "__main__":
    unittest.main()
