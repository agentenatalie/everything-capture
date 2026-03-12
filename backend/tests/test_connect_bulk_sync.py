import asyncio
import os
import sys
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Item  # noqa: E402
from routers.connect import sync_all_to_notion, sync_all_to_obsidian  # noqa: E402
from tenant import DEFAULT_USER_ID  # noqa: E402


class BulkSyncEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def make_item(self, item_id: str, **overrides) -> Item:
        payload = {
            "id": item_id,
            "user_id": DEFAULT_USER_ID,
            "source_url": f"https://example.com/{item_id}",
            "final_url": f"https://example.com/{item_id}",
            "title": f"Item {item_id}",
            "canonical_text": f"Content for {item_id}",
            "canonical_html": f"<p>Content for {item_id}</p>",
            "platform": "generic",
            "status": "ready",
        }
        payload.update(overrides)
        return Item(**payload)

    def test_notion_bulk_sync_skips_items_with_existing_page_ids(self) -> None:
        async def fake_sync(item, db, settings=None):
            item.notion_page_id = f"page-{item.id}"
            db.commit()
            return {"notion_page_id": item.notion_page_id}

        with self.Session() as db:
            db.add_all(
                [
                    self.make_item("already-synced", notion_page_id="page-existing"),
                    self.make_item("pending-1"),
                    self.make_item("pending-2"),
                ]
            )
            db.commit()

            with patch("routers.connect.get_current_user_id", return_value=DEFAULT_USER_ID), patch("routers.connect._sync_item_to_notion", side_effect=fake_sync):
                result = asyncio.run(sync_all_to_notion(db=db))

        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["attempted_count"], 2)
        self.assertEqual(result["synced_count"], 2)
        self.assertEqual(result["failed_count"], 0)

    def test_obsidian_bulk_sync_reports_failures_without_blocking_remaining_items(self) -> None:
        async def fake_sync(item, db, settings=None):
            if item.id == "broken-item":
                raise HTTPException(status_code=500, detail="network down")
            item.obsidian_path = f"Vault/{item.id}.md"
            db.commit()
            return {"obsidian_path": item.obsidian_path}

        with self.Session() as db:
            db.add_all(
                [
                    self.make_item("already-synced", obsidian_path="Vault/already-synced.md"),
                    self.make_item("broken-item"),
                    self.make_item("pending-item"),
                ]
            )
            db.commit()

            with patch("routers.connect.get_current_user_id", return_value=DEFAULT_USER_ID), patch("routers.connect._sync_item_to_obsidian", side_effect=fake_sync):
                result = asyncio.run(sync_all_to_obsidian(db=db))

        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["attempted_count"], 2)
        self.assertEqual(result["synced_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        self.assertEqual(result["errors"][0]["id"], "broken-item")

    def test_obsidian_bulk_sync_retries_transient_network_errors_once(self) -> None:
        attempts = {"retry-item": 0}

        async def fake_sync(item, db, settings=None):
            attempts[item.id] += 1
            if attempts[item.id] == 1:
                raise HTTPException(status_code=500, detail="Network error connecting to Obsidian: timeout")
            item.obsidian_path = f"Vault/{item.id}.md"
            db.commit()
            return {"obsidian_path": item.obsidian_path}

        with self.Session() as db:
            db.add(self.make_item("retry-item"))
            db.commit()

            with patch("routers.connect.get_current_user_id", return_value=DEFAULT_USER_ID), patch("routers.connect._sync_item_to_obsidian", side_effect=fake_sync):
                result = asyncio.run(sync_all_to_obsidian(db=db))

        self.assertEqual(attempts["retry-item"], 2)
        self.assertEqual(result["synced_count"], 1)
        self.assertEqual(result["failed_count"], 0)


if __name__ == "__main__":
    unittest.main()
