import datetime
import os
import sys
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Folder, Item, ItemFolderLink, User  # noqa: E402
from routers.folders import create_folder, get_folders, move_folder, reorder_folders  # noqa: E402
from schemas import FolderCreateRequest, FolderMoveRequest, FolderReorderRequest  # noqa: E402
from tenant import DEFAULT_USER_EMAIL, DEFAULT_USER_ID, DEFAULT_USER_NAME  # noqa: E402


class FolderHierarchyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

        with self.Session() as db:
            db.add(
                User(
                    id=DEFAULT_USER_ID,
                    email=DEFAULT_USER_EMAIL,
                    display_name=DEFAULT_USER_NAME,
                    is_default=True,
                )
            )
            db.commit()

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_move_folder_sets_parent_for_subfolder(self) -> None:
        with self.Session() as db:
            parent = Folder(user_id=DEFAULT_USER_ID, name="Projects", sort_order=0)
            child = Folder(user_id=DEFAULT_USER_ID, name="Inbox", sort_order=1)
            db.add_all([parent, child])
            db.commit()
            db.refresh(parent)
            db.refresh(child)

            response = move_folder(child.id, FolderMoveRequest(parent_id=parent.id), db)

            db.refresh(child)
            self.assertEqual(response.parent_id, parent.id)
            self.assertEqual(child.parent_id, parent.id)

    def test_move_folder_allows_nested_target_parent(self) -> None:
        with self.Session() as db:
            grandparent = Folder(user_id=DEFAULT_USER_ID, name="Workspace", sort_order=0)
            moving = Folder(user_id=DEFAULT_USER_ID, name="Inbox", sort_order=1)
            db.add_all([grandparent, moving])
            db.commit()
            db.refresh(grandparent)
            nested_parent = Folder(user_id=DEFAULT_USER_ID, name="Projects", parent_id=grandparent.id, sort_order=0)
            db.add(nested_parent)
            db.commit()
            db.refresh(nested_parent)
            db.refresh(moving)

            response = move_folder(moving.id, FolderMoveRequest(parent_id=nested_parent.id), db)

            db.refresh(moving)
            self.assertEqual(response.parent_id, nested_parent.id)
            self.assertEqual(moving.parent_id, nested_parent.id)

    def test_reorder_folders_scopes_to_requested_parent(self) -> None:
        with self.Session() as db:
            parent = Folder(user_id=DEFAULT_USER_ID, name="Projects", sort_order=0)
            root_folder = Folder(user_id=DEFAULT_USER_ID, name="Loose", sort_order=1)
            db.add_all([parent, root_folder])
            db.commit()
            db.refresh(parent)
            child_a = Folder(user_id=DEFAULT_USER_ID, name="Alpha", parent_id=parent.id, sort_order=0)
            child_b = Folder(user_id=DEFAULT_USER_ID, name="Beta", parent_id=parent.id, sort_order=1)
            db.add_all([child_a, child_b])
            db.commit()
            db.refresh(child_a)
            db.refresh(child_b)
            db.refresh(root_folder)

            reorder_folders(
                FolderReorderRequest(parent_id=parent.id, folder_ids=[child_b.id, child_a.id]),
                db,
            )

            db.refresh(child_a)
            db.refresh(child_b)
            db.refresh(root_folder)
            self.assertEqual(child_b.sort_order, 0)
            self.assertEqual(child_a.sort_order, 1)
            self.assertEqual(root_folder.sort_order, 1)

    def test_create_folder_allows_nested_parent(self) -> None:
        with self.Session() as db:
            grandparent = Folder(user_id=DEFAULT_USER_ID, name="Workspace", sort_order=0)
            db.add(grandparent)
            db.commit()
            db.refresh(grandparent)

            parent = Folder(user_id=DEFAULT_USER_ID, name="Projects", parent_id=grandparent.id, sort_order=0)
            db.add(parent)
            db.commit()
            db.refresh(parent)

            response = create_folder(FolderCreateRequest(name="Leaf", parent_id=parent.id), db)

            self.assertEqual(response.parent_id, parent.id)

    def test_move_folder_rejects_duplicate_name_in_target_parent(self) -> None:
        with self.Session() as db:
            parent = Folder(user_id=DEFAULT_USER_ID, name="Projects", sort_order=0)
            moving = Folder(user_id=DEFAULT_USER_ID, name="Inbox", sort_order=1)
            db.add_all([parent, moving])
            db.commit()
            db.refresh(parent)
            db.refresh(moving)
            existing_child = Folder(user_id=DEFAULT_USER_ID, name="Inbox", parent_id=parent.id, sort_order=0)
            db.add(existing_child)
            db.commit()

            with self.assertRaises(HTTPException) as context:
                move_folder(moving.id, FolderMoveRequest(parent_id=parent.id), db)

            self.assertEqual(context.exception.status_code, 409)

    def test_get_folders_aggregates_unique_subtree_item_count(self) -> None:
        with self.Session() as db:
            parent = Folder(user_id=DEFAULT_USER_ID, name="Projects", sort_order=0)
            db.add(parent)
            db.commit()
            db.refresh(parent)
            child = Folder(user_id=DEFAULT_USER_ID, name="Alpha", parent_id=parent.id, sort_order=0)
            db.add(child)
            db.commit()
            db.refresh(child)

            item_parent = Item(
                user_id=DEFAULT_USER_ID,
                source_url="https://example.com/parent",
                title="Parent only",
                canonical_text="body",
                platform="web",
                status="ready",
                folder_id=parent.id,
            )
            item_child = Item(
                user_id=DEFAULT_USER_ID,
                source_url="https://example.com/child",
                title="Child only",
                canonical_text="body",
                platform="web",
                status="ready",
                folder_id=child.id,
            )
            item_both = Item(
                user_id=DEFAULT_USER_ID,
                source_url="https://example.com/both",
                title="Both",
                canonical_text="body",
                platform="web",
                status="ready",
                folder_id=parent.id,
            )
            db.add_all([item_parent, item_child, item_both])
            db.commit()
            db.refresh(item_parent)
            db.refresh(item_child)
            db.refresh(item_both)

            db.add_all([
                ItemFolderLink(item_id=item_parent.id, folder_id=parent.id),
                ItemFolderLink(item_id=item_child.id, folder_id=child.id),
                ItemFolderLink(item_id=item_both.id, folder_id=parent.id),
                ItemFolderLink(item_id=item_both.id, folder_id=child.id),
            ])
            db.commit()

            response = get_folders(db)
            folders_by_id = {folder.id: folder for folder in response.folders}

            self.assertEqual(folders_by_id[parent.id].item_count, 3)
            self.assertEqual(folders_by_id[child.id].item_count, 2)

    def test_get_folders_returns_favorite_and_unread_counts(self) -> None:
        with self.Session() as db:
            db.add_all(
                [
                    Item(
                        user_id=DEFAULT_USER_ID,
                        source_url="https://example.com/favorite-unread",
                        title="Favorite unread",
                        canonical_text="body",
                        platform="web",
                        status="ready",
                        is_favorite=True,
                        last_viewed_at=None,
                    ),
                    Item(
                        user_id=DEFAULT_USER_ID,
                        source_url="https://example.com/favorite-read",
                        title="Favorite read",
                        canonical_text="body",
                        platform="web",
                        status="ready",
                        is_favorite=True,
                        last_viewed_at=datetime.datetime(2026, 4, 6, 9, 0, 0),
                    ),
                    Item(
                        user_id=DEFAULT_USER_ID,
                        source_url="https://example.com/read-only",
                        title="Read only",
                        canonical_text="body",
                        platform="web",
                        status="ready",
                        is_favorite=False,
                        last_viewed_at=datetime.datetime(2026, 4, 6, 10, 0, 0),
                    ),
                ]
            )
            db.commit()

            response = get_folders(db)

        self.assertEqual(response.favorite_count, 2)
        self.assertEqual(response.unread_count, 1)


if __name__ == "__main__":
    unittest.main()
