import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Item, Settings  # noqa: E402
from routers.connect import (  # noqa: E402
    SyncStatusRefreshRequest,
    _SYNC_STATUS_CACHE,
    _build_obsidian_note_path,
    _current_obsidian_note_content,
    _find_obsidian_notes_by_item_ids,
    refresh_sync_status,
)
from security import encrypt_secret  # noqa: E402
from tenant import DEFAULT_USER_ID  # noqa: E402


class RefreshSyncStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        _SYNC_STATUS_CACHE.clear()

    def tearDown(self) -> None:
        _SYNC_STATUS_CACHE.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def make_item(self, item_id: str, **overrides) -> Item:
        payload = {
            "id": item_id,
            "user_id": DEFAULT_USER_ID,
            "workspace_id": "local-default-workspace",
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

    def test_refresh_sync_status_bypasses_stale_cache_and_recovers_current_vault_note(self) -> None:
        with self.Session() as db:
            item = self.make_item("note-item")
            db.add(item)
            db.add(
                Settings(
                    user_id=DEFAULT_USER_ID,
                    obsidian_rest_api_url="https://127.0.0.1:27124",
                    obsidian_api_key=encrypt_secret("obsidian-secret"),
                    obsidian_folder_path="Sources.base",
                )
            )
            db.commit()

            note_path = _build_obsidian_note_path(item, "Sources.base")
            _SYNC_STATUS_CACHE["|".join([item.id, "", ""])] = {
                "checked_at": 9999999999,
                "notion_page_id": None,
                "obsidian_path": None,
            }

            with patch("routers.connect.get_current_user_id", return_value=DEFAULT_USER_ID), patch(
                "routers.connect._obsidian_note_exists",
                new=AsyncMock(
                    return_value=(
                        "exists",
                        f"---\nitem_id: {item.id}\nsource: {item.source_url}\n---\n",
                    )
                ),
            ):
                result = asyncio.run(
                    refresh_sync_status(
                        SyncStatusRefreshRequest(item_ids=[item.id]),
                        db=db,
                    )
                )

            self.assertEqual(result["items"][0]["obsidian_path"], note_path)
            db.refresh(item)
            self.assertEqual(item.obsidian_path, note_path)

    def test_refresh_sync_status_rebinds_stale_saved_path_to_current_note_path(self) -> None:
        with self.Session() as db:
            item = self.make_item("migrated-item", obsidian_path="OldVault/migrated-item.md")
            db.add(item)
            db.add(
                Settings(
                    user_id=DEFAULT_USER_ID,
                    obsidian_rest_api_url="https://127.0.0.1:27124",
                    obsidian_api_key=encrypt_secret("obsidian-secret"),
                    obsidian_folder_path="Sources.base",
                )
            )
            db.commit()

            note_path = _build_obsidian_note_path(item, "Sources.base")

            with patch("routers.connect.get_current_user_id", return_value=DEFAULT_USER_ID), patch(
                "routers.connect._obsidian_note_exists",
                new=AsyncMock(
                    side_effect=[
                        ("missing", None),
                        ("exists", f"---\nitem_id: {item.id}\nsource: {item.source_url}\n---\n"),
                    ]
                ),
            ):
                result = asyncio.run(
                    refresh_sync_status(
                        SyncStatusRefreshRequest(item_ids=[item.id]),
                        db=db,
                    )
                )

            self.assertEqual(result["items"][0]["obsidian_path"], note_path)
            db.refresh(item)
            self.assertEqual(item.obsidian_path, note_path)

    def test_refresh_sync_status_marks_matching_obsidian_note_as_ready_and_persists_hash(self) -> None:
        with self.Session() as db:
            item = self.make_item("ready-item", obsidian_path="Sources.base/ready-item.md")
            db.add(item)
            db.add(
                Settings(
                    user_id=DEFAULT_USER_ID,
                    obsidian_rest_api_url="https://127.0.0.1:27124",
                    obsidian_api_key=encrypt_secret("obsidian-secret"),
                    obsidian_folder_path="Sources.base",
                )
            )
            db.commit()

            current_note_content = _current_obsidian_note_content(item)

            with patch("routers.connect.get_current_user_id", return_value=DEFAULT_USER_ID), patch(
                "routers.connect._obsidian_note_exists",
                new=AsyncMock(return_value=("exists", current_note_content)),
            ):
                result = asyncio.run(
                    refresh_sync_status(
                        SyncStatusRefreshRequest(item_ids=[item.id]),
                        db=db,
                    )
                )

            self.assertEqual(result["items"][0]["obsidian_sync_state"], "ready")
            db.refresh(item)
            self.assertIsNotNone(item.obsidian_last_synced_hash)
            self.assertIsNotNone(item.obsidian_last_synced_at)

    def test_refresh_sync_status_marks_drifted_obsidian_note_as_partial(self) -> None:
        with self.Session() as db:
            item = self.make_item(
                "partial-item",
                obsidian_path="Sources.base/partial-item.md",
                obsidian_last_synced_hash="previous-hash",
            )
            db.add(item)
            db.add(
                Settings(
                    user_id=DEFAULT_USER_ID,
                    obsidian_rest_api_url="https://127.0.0.1:27124",
                    obsidian_api_key=encrypt_secret("obsidian-secret"),
                    obsidian_folder_path="Sources.base",
                )
            )
            db.commit()

            remote_note_content = (
                f"---\nitem_id: {item.id}\nsource: {item.source_url}\nplatform: {item.platform}\n---\n旧内容\n"
            )

            with patch("routers.connect.get_current_user_id", return_value=DEFAULT_USER_ID), patch(
                "routers.connect._obsidian_note_exists",
                new=AsyncMock(return_value=("exists", remote_note_content)),
            ):
                result = asyncio.run(
                    refresh_sync_status(
                        SyncStatusRefreshRequest(item_ids=[item.id]),
                        db=db,
                    )
                )

            self.assertEqual(result["items"][0]["obsidian_sync_state"], "partial")
            db.refresh(item)
            self.assertEqual(item.obsidian_last_synced_hash, "")
            self.assertIsNone(item.obsidian_last_synced_at)

    def test_find_obsidian_notes_by_item_ids_scans_nested_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            vault_root = os.path.join(tmpdir, "vault")
            target_dir = os.path.join(vault_root, "Sources.base", "AI", "Agents")
            os.makedirs(target_dir, exist_ok=True)
            note_path = os.path.join(target_dir, "nested-note.md")
            with open(note_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "---\n"
                    "item_id: nested-item-id\n"
                    "source: https://example.com/nested\n"
                    "---\n"
                )

            with patch("routers.connect._open_obsidian_vault_roots", return_value=[Path(vault_root)]):
                matches = _find_obsidian_notes_by_item_ids("Sources.base", {"nested-item-id"})

        self.assertEqual(matches["nested-item-id"], "Sources.base/AI/Agents/nested-note.md")


if __name__ == "__main__":
    unittest.main()
