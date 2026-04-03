import os
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Folder, Item, ItemFolderLink, User  # noqa: E402
from routers.items import get_items_graph  # noqa: E402
from tenant import DEFAULT_USER_EMAIL, DEFAULT_USER_ID, DEFAULT_USER_NAME  # noqa: E402


class ItemGraphFolderFilterTests(unittest.TestCase):
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

    def test_graph_main_folder_filter_includes_descendant_subfolder_items(self) -> None:
        with self.Session() as db:
            parent = Folder(user_id=DEFAULT_USER_ID, name="Projects", sort_order=0)
            db.add(parent)
            db.commit()
            db.refresh(parent)

            child = Folder(user_id=DEFAULT_USER_ID, name="Alpha", parent_id=parent.id, sort_order=0)
            unrelated = Folder(user_id=DEFAULT_USER_ID, name="Elsewhere", sort_order=1)
            db.add_all([child, unrelated])
            db.commit()
            db.refresh(child)
            db.refresh(unrelated)

            parent_item = Item(
                user_id=DEFAULT_USER_ID,
                source_url="https://example.com/parent",
                title="Parent item",
                canonical_text="shared content graph test",
                canonical_html="<p>shared content graph test</p>",
                platform="web",
                status="ready",
                folder_id=parent.id,
            )
            child_item = Item(
                user_id=DEFAULT_USER_ID,
                source_url="https://example.com/child",
                title="Child item",
                canonical_text="shared content graph test",
                canonical_html="<p>shared content graph test</p>",
                platform="web",
                status="ready",
                folder_id=child.id,
            )
            unrelated_item = Item(
                user_id=DEFAULT_USER_ID,
                source_url="https://example.com/unrelated",
                title="Unrelated item",
                canonical_text="shared content graph test",
                canonical_html="<p>shared content graph test</p>",
                platform="web",
                status="ready",
                folder_id=unrelated.id,
            )
            db.add_all([parent_item, child_item, unrelated_item])
            db.commit()
            db.refresh(parent_item)
            db.refresh(child_item)
            db.refresh(unrelated_item)

            db.add_all(
                [
                    ItemFolderLink(item_id=parent_item.id, folder_id=parent.id),
                    ItemFolderLink(item_id=child_item.id, folder_id=child.id),
                    ItemFolderLink(item_id=unrelated_item.id, folder_id=unrelated.id),
                ]
            )
            db.commit()

            response = get_items_graph(folder_id=parent.id, db=db)
            node_ids = {node.id for node in response.nodes}
            parent_item_id = parent_item.id
            child_item_id = child_item.id
            unrelated_item_id = unrelated_item.id

        self.assertIn(parent_item_id, node_ids)
        self.assertIn(child_item_id, node_ids)
        self.assertNotIn(unrelated_item_id, node_ids)


if __name__ == "__main__":
    unittest.main()
