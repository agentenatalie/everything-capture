import datetime
import os
import sys
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Folder, Item, ItemFolderLink  # noqa: E402
from routers.items import merge_requested_folder_ids, normalize_requested_folder_ids, serialize_items, sync_item_folder_assignments  # noqa: E402


class ItemFolderTests(unittest.TestCase):
    def test_normalize_requested_folder_ids_preserves_order_and_deduplicates(self) -> None:
        result = normalize_requested_folder_ids("folder-b", ["folder-a", "", "folder-a", "folder-c", "folder-b"])

        self.assertEqual(result, ["folder-a", "folder-c", "folder-b"])

    def test_sync_item_folder_assignments_updates_links_and_primary_folder(self) -> None:
        item = Item(id="item-1")
        folder_a = Folder(id="folder-a", name="Alpha")
        folder_b = Folder(id="folder-b", name="Beta")
        folder_old = Folder(id="folder-old", name="Old")
        item.folder_links = [
            ItemFolderLink(item_id="item-1", folder_id="folder-old", folder=folder_old),
        ]

        sync_item_folder_assignments(item, [folder_a, folder_b])

        self.assertEqual(item.folder_id, "folder-a")
        self.assertEqual([link.folder_id for link in item.folder_links], ["folder-a", "folder-b"])

    def test_merge_requested_folder_ids_prepends_new_folders_without_losing_existing_ones(self) -> None:
        item = Item(id="item-1", folder_id="folder-old")
        folder_old = Folder(id="folder-old", name="Old")
        folder_keep = Folder(id="folder-keep", name="Keep")
        item.folder_links = [
            ItemFolderLink(
                item_id="item-1",
                folder_id="folder-keep",
                folder=folder_keep,
                created_at=datetime.datetime(2026, 3, 9, 12, 2, 0),
            ),
            ItemFolderLink(
                item_id="item-1",
                folder_id="folder-old",
                folder=folder_old,
                created_at=datetime.datetime(2026, 3, 9, 12, 1, 0),
            ),
        ]

        merged = merge_requested_folder_ids(item, ["folder-new", "folder-keep"])

        self.assertEqual(merged, ["folder-new", "folder-keep", "folder-old"])

    def test_serialize_items_exposes_all_folder_names(self) -> None:
        item = Item(
            id="item-1",
            title="Example",
            source_url="https://example.com",
            canonical_text="body",
            platform="web",
            status="ready",
            created_at=datetime.datetime(2026, 3, 9, 12, 0, 0),
        )
        folder_a = Folder(id="folder-a", name="Alpha", created_at=datetime.datetime(2026, 3, 9, 12, 1, 0))
        folder_b = Folder(id="folder-b", name="Beta", created_at=datetime.datetime(2026, 3, 9, 12, 2, 0))
        item.folder_links = [
            ItemFolderLink(
                item_id="item-1",
                folder_id="folder-b",
                folder=folder_b,
                created_at=datetime.datetime(2026, 3, 9, 12, 3, 0),
            ),
            ItemFolderLink(
                item_id="item-1",
                folder_id="folder-a",
                folder=folder_a,
                created_at=datetime.datetime(2026, 3, 9, 12, 2, 0),
            ),
        ]
        item.media = []

        [serialized] = serialize_items([item])

        self.assertEqual(serialized.folder_ids, ["folder-a", "folder-b"])
        self.assertEqual(serialized.folder_names, ["Alpha", "Beta"])
        self.assertEqual(serialized.folder_id, "folder-a")
        self.assertEqual(serialized.folder_name, "Alpha")
        self.assertEqual(serialized.folder_count, 2)

    def test_serialize_items_prioritizes_primary_folder_before_older_links(self) -> None:
        item = Item(
            id="item-1",
            title="Example",
            source_url="https://example.com",
            canonical_text="body",
            platform="web",
            status="ready",
            folder_id="folder-b",
            created_at=datetime.datetime(2026, 3, 9, 12, 0, 0),
        )
        folder_a = Folder(id="folder-a", name="Alpha")
        folder_b = Folder(id="folder-b", name="Beta")
        item.folder_links = [
            ItemFolderLink(
                item_id="item-1",
                folder_id="folder-a",
                folder=folder_a,
                created_at=datetime.datetime(2026, 3, 9, 12, 1, 0),
            ),
            ItemFolderLink(
                item_id="item-1",
                folder_id="folder-b",
                folder=folder_b,
                created_at=datetime.datetime(2026, 3, 9, 12, 2, 0),
            ),
        ]
        item.media = []

        [serialized] = serialize_items([item])

        self.assertEqual(serialized.folder_ids, ["folder-b", "folder-a"])
        self.assertEqual(serialized.folder_names, ["Beta", "Alpha"])
        self.assertEqual(serialized.folder_id, "folder-b")
        self.assertEqual(serialized.folder_name, "Beta")

    def test_serialize_items_exposes_read_and_favorite_state(self) -> None:
        viewed_at = datetime.datetime(2026, 3, 9, 12, 5, 0)
        item = Item(
            id="item-1",
            title="Example",
            source_url="https://example.com",
            canonical_text="body",
            platform="web",
            status="ready",
            created_at=datetime.datetime(2026, 3, 9, 12, 0, 0),
            last_viewed_at=viewed_at,
            is_favorite=True,
        )
        item.folder_links = []
        item.media = []

        [serialized] = serialize_items([item])

        self.assertTrue(serialized.is_read)
        self.assertTrue(serialized.is_favorite)


if __name__ == "__main__":
    unittest.main()
