import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Folder, Item  # noqa: E402
import processing_worker  # noqa: E402


class ProcessingWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.TestSession = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_process_capture_item_creates_local_item_and_folders(self) -> None:
        capture_item = {
            "id": "capture-123",
            "raw_text": "一段要进入本地知识库的文本",
            "raw_url": None,
            "title": "队列文本",
            "source": "phone-webapp",
            "created_at": "2026-03-09T10:00:00Z",
            "folder_names": ["Inbox", "Read Later"],
        }

        with patch.object(processing_worker, "SessionLocal", self.TestSession):
            with patch("routers.ingest.background_auto_sync", lambda *args, **kwargs: None):
                local_item_id, local_status, background_tasks = asyncio.run(processing_worker.process_capture_item(capture_item))
                background_tasks.run_all()

        self.assertEqual(local_status, "ready")

        with self.TestSession() as db:
            item = db.query(Item).filter(Item.id == local_item_id).first()
            self.assertIsNotNone(item)
            self.assertEqual(item.title, "队列文本")
            self.assertEqual(item.canonical_text, "一段要进入本地知识库的文本")

            debug_payload = json.loads(item.debug_json)
            self.assertEqual(debug_payload["capture_service_item_id"], "capture-123")

            folders = db.query(Folder).order_by(Folder.name.asc()).all()
            self.assertEqual([folder.name for folder in folders], ["Inbox", "Read Later"])
            self.assertEqual(sorted(link.folder.name for link in item.folder_links), ["Inbox", "Read Later"])


if __name__ == "__main__":
    unittest.main()
