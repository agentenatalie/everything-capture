import importlib
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

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

        self.database = importlib.import_module("capture_service.database")
        self.api = importlib.import_module("capture_service.api")
        self.client = TestClient(self.api.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()
        os.environ.pop("CAPTURE_SERVICE_DB_PATH", None)

    def test_capture_queue_claim_and_complete_flow(self) -> None:
        root_response = self.client.get("/")
        self.assertEqual(root_response.status_code, 200)
        self.assertIn("Everything Capture", root_response.text)

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
        create_payload = create_response.json()
        self.assertTrue(create_payload["success"])
        self.assertTrue(create_payload["captured"])
        self.assertEqual(create_payload["status"], "pending")
        created_item = create_payload["item"]
        self.assertEqual(create_payload["item_id"], created_item["id"])
        self.assertEqual(created_item["status"], "pending")
        self.assertEqual(created_item["folder_names"], ["Inbox"])

        list_response = self.client.get("/api/items", params={"status": "pending"})
        self.assertEqual(list_response.status_code, 200)
        listed_items = list_response.json()["items"]
        self.assertEqual(len(listed_items), 1)
        self.assertEqual(listed_items[0]["id"], created_item["id"])

        item_response = self.client.get(f"/api/items/{created_item['id']}")
        self.assertEqual(item_response.status_code, 200)
        self.assertEqual(item_response.json()["status"], "pending")

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
        create_payload = create_response.json()
        self.assertTrue(create_payload["captured"])
        item_id = create_payload["item_id"]

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

    def test_waiting_list_requeues_stale_processing_items_and_returns_counts(self) -> None:
        create_response = self.client.post(
            "/api/capture",
            json={
                "text": "waiting capture",
                "source": "phone-webapp",
                "source_app": "capture-webapp",
                "folder_names": ["Inbox"],
            },
        )
        item_id = create_response.json()["item_id"]

        claim_response = self.client.post(
            f"/api/items/{item_id}/claim",
            json={"worker_id": "worker-stale"},
        )
        self.assertEqual(claim_response.status_code, 200)
        self.assertEqual(claim_response.json()["item"]["status"], "processing")

        with self.database.SessionLocal() as db:
            item = db.query(self.api.CaptureItem).filter(self.api.CaptureItem.id == item_id).first()
            item.leased_at = datetime.utcnow() - timedelta(days=1)
            db.add(item)
            db.commit()

        waiting_response = self.client.get("/api/items", params={"status": "waiting", "limit": 20})
        self.assertEqual(waiting_response.status_code, 200)
        payload = waiting_response.json()
        self.assertEqual(payload["total_count"], 1)
        self.assertEqual(payload["status_counts"]["pending"], 1)
        self.assertEqual(payload["status_counts"]["processing"], 0)
        self.assertEqual(payload["items"][0]["status"], "pending")

        item_response = self.client.get(f"/api/items/{item_id}")
        self.assertEqual(item_response.status_code, 200)
        self.assertEqual(item_response.json()["status"], "pending")

    def test_worker_status_reflects_recent_heartbeat(self) -> None:
        initial_status = self.client.get("/api/worker-status")
        self.assertEqual(initial_status.status_code, 200)
        self.assertFalse(initial_status.json()["connected"])

        heartbeat_response = self.client.post(
            "/api/worker-heartbeat",
            json={
                "worker_id": "worker-online",
                "hostname": "macbook",
                "state": "connected",
                "processed_count": 2,
            },
        )
        self.assertEqual(heartbeat_response.status_code, 200)
        self.assertTrue(heartbeat_response.json()["connected"])
        self.assertEqual(heartbeat_response.json()["status_label"], "后端已连接")

        status_response = self.client.get("/api/worker-status")
        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.json()["connected"])
        self.assertEqual(status_response.json()["connected_worker_count"], 1)

    def test_folder_api_lists_and_creates_folders(self) -> None:
        initial = self.client.get("/api/folders")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.json()["total_count"], 0)

        created = self.client.post("/api/folders", json={"name": "Inbox"})
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], "Inbox")

        listed = self.client.get("/api/folders")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["total_count"], 1)
        self.assertEqual(listed.json()["folders"][0]["name"], "Inbox")


if __name__ == "__main__":
    unittest.main()
