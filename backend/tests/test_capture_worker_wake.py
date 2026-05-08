import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import capture_worker


class CaptureWorkerWakeRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(capture_worker.router)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        os.environ.pop("CAPTURE_WORKER_WAKE_TOKEN", None)

    def test_wake_endpoint_requires_configured_token(self) -> None:
        os.environ.pop("CAPTURE_WORKER_WAKE_TOKEN", None)

        response = self.client.post("/api/capture-worker/wake", json={"item_id": "capture-1"})

        self.assertEqual(response.status_code, 404)

    def test_wake_endpoint_starts_background_worker_with_bearer_token(self) -> None:
        os.environ["CAPTURE_WORKER_WAKE_TOKEN"] = "wake-secret"

        with patch.object(capture_worker, "_start_wake_thread", return_value=True) as start_wake:
            response = self.client.post(
                "/api/capture-worker/wake",
                headers={"Authorization": "Bearer wake-secret"},
                json={"item_id": "capture-1"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["already_running"], False)
        start_wake.assert_called_once_with("capture-1")

    def test_wake_endpoint_rejects_wrong_token(self) -> None:
        os.environ["CAPTURE_WORKER_WAKE_TOKEN"] = "wake-secret"

        with patch.object(capture_worker, "_start_wake_thread") as start_wake:
            response = self.client.post(
                "/api/capture-worker/wake",
                headers={"Authorization": "Bearer wrong"},
                json={"item_id": "capture-1"},
            )

        self.assertEqual(response.status_code, 401)
        start_wake.assert_not_called()


if __name__ == "__main__":
    unittest.main()
