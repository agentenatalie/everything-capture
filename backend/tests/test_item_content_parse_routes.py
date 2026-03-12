import datetime
import os
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database import Base  # noqa: E402
from models import Item  # noqa: E402
import routers.items as items_router  # noqa: E402


class ItemContentParseRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.TestSession = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

        with self.TestSession() as db:
            db.add(
                Item(
                    id="item-parse-route",
                    user_id="local-default-user",
                    workspace_id="local-default-workspace",
                    title="待解析内容",
                    source_url="https://example.com",
                    canonical_text="正文",
                    platform="generic",
                    status="ready",
                )
            )
            db.commit()

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_parse_route_persists_structured_parse_fields(self) -> None:
        with self.TestSession() as db:
            with patch.object(items_router, "get_current_user_id", return_value="local-default-user"):
                with patch.object(
                    items_router,
                    "parse_item_content_for_item",
                    side_effect=lambda item: (
                        setattr(item, "extracted_text", "[ocr_text]\n解析完成"),
                        setattr(item, "ocr_text", "解析完成"),
                        setattr(item, "frame_texts_json", "[]"),
                        setattr(item, "urls_json", '["https://example.com"]'),
                        setattr(item, "qr_links_json", "[]"),
                        setattr(item, "parse_status", "completed"),
                        setattr(item, "parse_error", None),
                        setattr(item, "parsed_at", datetime.datetime(2026, 3, 11, 20, 0, 0)),
                    ),
                ):
                    response = items_router.parse_item_content_endpoint("item-parse-route", db=db)

        self.assertEqual(response.parse_status, "completed")
        self.assertEqual(response.extracted_text, "[ocr_text]\n解析完成")
        self.assertEqual(response.urls, ["https://example.com"])

    def test_note_route_updates_extracted_text(self) -> None:
        request = items_router.ItemNoteUpdateRequest(extracted_text="手动修改后的解析笔记")

        with self.TestSession() as db:
            with patch.object(items_router, "get_current_user_id", return_value="local-default-user"):
                response = items_router.update_item_note("item-parse-route", request, db=db)

        self.assertEqual(response.extracted_text, "手动修改后的解析笔记")
        self.assertEqual(response.parse_status, "completed")


if __name__ == "__main__":
    unittest.main()
