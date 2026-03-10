import importlib
import os
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient


class CaptureServiceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["CAPTURE_SERVICE_DB_PATH"] = os.path.join(self.temp_dir.name, "capture-test.db")

        for module_name in [
            "capture_service.api",
            "capture_service.database",
            "capture_service.models",
            "capture_service.schemas",
        ]:
            sys.modules.pop(module_name, None)

        self.api = importlib.import_module("capture_service.api")
        self.client = TestClient(self.api.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("CAPTURE_SERVICE_DB_PATH", None)

    def test_capture_queue_claim_and_complete_flow(self) -> None:
        create_response = self.client.post(
            "/api/capture",
            json={
                "text": "hello from phone",
                "url": "https://example.com/article",
                "source": "phone-webapp",
                "folder_names": ["Inbox"],
            },
        )
        self.assertEqual(create_response.status_code, 201)
        created_item = create_response.json()["item"]
        self.assertEqual(created_item["status"], "pending")
        self.assertEqual(created_item["folder_names"], ["Inbox"])

        list_response = self.client.get("/api/items", params={"status": "pending"})
        self.assertEqual(list_response.status_code, 200)
        listed_items = list_response.json()["items"]
        self.assertEqual(len(listed_items), 1)
        self.assertEqual(listed_items[0]["id"], created_item["id"])

        claim_response = self.client.post(
            f"/api/items/{created_item['id']}/claim",
            json={"worker_id": "worker-1"},
        )
        self.assertEqual(claim_response.status_code, 200)
        claimed_item = claim_response.json()["item"]
        self.assertEqual(claimed_item["status"], "processing")
        self.assertTrue(claimed_item["lease_token"])

        complete_response = self.client.post(
            f"/api/items/{created_item['id']}/complete",
            json={
                "lease_token": claimed_item["lease_token"],
                "local_item_id": "local-item-123",
                "result_json": "{\"local_status\":\"ready\"}",
            },
        )
        self.assertEqual(complete_response.status_code, 200)
        self.assertEqual(complete_response.json()["status"], "processed")
        self.assertEqual(complete_response.json()["local_item_id"], "local-item-123")

    def test_capture_queue_fail_flow(self) -> None:
        create_response = self.client.post(
            "/api/capture",
            json={
                "text": "failing capture",
                "source": "api",
            },
        )
        item_id = create_response.json()["item"]["id"]

        claim_response = self.client.post(
            f"/api/items/{item_id}/claim",
            json={"worker_id": "worker-2"},
        )
        lease_token = claim_response.json()["item"]["lease_token"]

        fail_response = self.client.post(
            f"/api/items/{item_id}/fail",
            json={"lease_token": lease_token, "error_reason": "download failed"},
        )
        self.assertEqual(fail_response.status_code, 200)
        self.assertEqual(fail_response.json()["status"], "failed")
        self.assertEqual(fail_response.json()["error_reason"], "download failed")


if __name__ == "__main__":
    unittest.main()
