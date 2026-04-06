import datetime
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Item, User  # noqa: E402
import routers.items as items_router  # noqa: E402
from schemas import ItemStateUpdateRequest  # noqa: E402
from tenant import DEFAULT_USER_EMAIL, DEFAULT_USER_ID, DEFAULT_USER_NAME  # noqa: E402


class ItemStateTests(unittest.TestCase):
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
            db.add_all(
                [
                    Item(
                        id="favorite-item",
                        user_id=DEFAULT_USER_ID,
                        source_url="https://example.com/favorite",
                        title="Favorite",
                        canonical_text="body",
                        platform="web",
                        status="ready",
                        is_favorite=True,
                    ),
                    Item(
                        id="plain-item",
                        user_id=DEFAULT_USER_ID,
                        source_url="https://example.com/plain",
                        title="Plain",
                        canonical_text="body",
                        platform="web",
                        status="ready",
                        is_favorite=False,
                    ),
                ]
            )
            db.commit()

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_apply_folder_filter_favorites_returns_only_favorited_items(self) -> None:
        with self.Session() as db:
            filtered_ids = [item.id for item in items_router.apply_folder_filter(db.query(Item), folder_scope="favorites").all()]

        self.assertEqual(filtered_ids, ["favorite-item"])

    def test_update_item_state_sets_read_and_favorite_flags(self) -> None:
        request = ItemStateUpdateRequest(is_read=True, is_favorite=True)

        with self.Session() as db:
            with patch.object(items_router, "get_current_user_id", return_value=DEFAULT_USER_ID):
                response = items_router.update_item_state("plain-item", request, db=db)

            db_item = db.query(Item).filter(Item.id == "plain-item").one()

        self.assertTrue(response.is_read)
        self.assertTrue(response.is_favorite)
        self.assertIsNotNone(db_item.last_viewed_at)
        self.assertTrue(db_item.is_favorite)

    def test_update_item_state_can_clear_read_flag(self) -> None:
        with self.Session() as db:
            item = db.query(Item).filter(Item.id == "favorite-item").one()
            item.last_viewed_at = datetime.datetime(2026, 4, 6, 10, 0, 0)
            db.commit()

            with patch.object(items_router, "get_current_user_id", return_value=DEFAULT_USER_ID):
                response = items_router.update_item_state(
                    "favorite-item",
                    ItemStateUpdateRequest(is_read=False),
                    db=db,
                )

            db_item = db.query(Item).filter(Item.id == "favorite-item").one()

        self.assertFalse(response.is_read)
        self.assertIsNone(db_item.last_viewed_at)


if __name__ == "__main__":
    unittest.main()
