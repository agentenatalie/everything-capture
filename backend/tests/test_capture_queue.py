import os
import unittest
from unittest.mock import patch

from services import capture_queue


class CaptureQueueConfigTests(unittest.TestCase):
    def test_get_capture_service_base_url_uses_local_file_values(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CAPTURE_SERVICE_URL", None)
            with patch.object(
                capture_queue,
                "_load_capture_service_file_values",
                return_value={"CAPTURE_SERVICE_URL": "https://capture.example.com"},
            ):
                self.assertEqual(
                    capture_queue.get_capture_service_base_url(),
                    "https://capture.example.com",
                )

    def test_capture_service_headers_include_file_token(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CAPTURE_SERVICE_TOKEN", None)
            with patch.object(
                capture_queue,
                "_load_capture_service_file_values",
                return_value={"CAPTURE_SERVICE_TOKEN": "secret-token"},
            ):
                self.assertEqual(
                    capture_queue._capture_service_headers()["Authorization"],
                    "Bearer secret-token",
                )


if __name__ == "__main__":
    unittest.main()
