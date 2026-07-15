import datetime
import json
import os
import sys
import types
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

    def test_store_parse_result_keeps_wechat_gallery_ocr_out_of_article_blocks(self) -> None:
        summary = "这是一篇值得保存的内容"
        ocr_text = "AI 时代的内容创作与工作方式\n\n代码变便宜了，注意力变贵了。" * 12
        gallery_blocks = [
            {"type": "image", "url": "https://mmbiz.qpic.cn/slide-1.jpg"},
            {"type": "image", "url": "https://mmbiz.qpic.cn/slide-2.jpg"},
            {"type": "text", "content": summary},
        ]
        parse_result = types.SimpleNamespace(
            extracted_text=f"[ocr_text]\n{ocr_text}",
            ocr_text=ocr_text,
            frame_texts=[],
            urls=[],
            qr_links=[],
            parse_status="completed",
            parse_error=None,
            parsed_at=datetime.datetime(2026, 7, 15, 12, 0, 0),
        )

        detached_item = Item(
            id="wechat-gallery-detached",
            title="微信滑动图文",
            source_url="https://mp.weixin.qq.com/s/example-gallery",
            canonical_text=summary,
            content_blocks_json=json.dumps(gallery_blocks, ensure_ascii=False),
            platform="wechat",
        )
        persisted_item = Item(
            id="wechat-gallery-persisted",
            content_blocks_json=json.dumps(gallery_blocks, ensure_ascii=False),
            platform="wechat",
        )

        items_router._store_item_parse_result(detached_item, parse_result)
        items_router._copy_item_parse_fields(detached_item, persisted_item)

        self.assertEqual(json.loads(detached_item.content_blocks_json), gallery_blocks)
        self.assertEqual(json.loads(persisted_item.content_blocks_json), gallery_blocks)

    def test_store_parse_result_removes_legacy_generated_ocr_article_block(self) -> None:
        gallery_blocks = [
            {"type": "image", "url": "https://mmbiz.qpic.cn/slide-1.jpg"},
            {"type": "image", "url": "https://mmbiz.qpic.cn/slide-2.jpg"},
            {"type": "text", "content": "原始导语"},
        ]
        parse_result = types.SimpleNamespace(
            extracted_text="[ocr_text]\n清理后的识别结果",
            ocr_text="清理后的识别结果",
            frame_texts=[],
            urls=[],
            qr_links=[],
            parse_status="completed",
            parse_error=None,
            parsed_at=datetime.datetime(2026, 7, 15, 12, 0, 0),
        )
        item = Item(
            id="wechat-gallery-with-legacy-ocr",
            content_blocks_json=json.dumps(
                [*gallery_blocks, {"type": "text", "content": "旧乱码", "source": "ocr"}],
                ensure_ascii=False,
            ),
            platform="wechat",
        )

        items_router._store_item_parse_result(item, parse_result)

        self.assertEqual(json.loads(item.content_blocks_json), gallery_blocks)

    def test_store_parse_result_does_not_promote_ocr_for_regular_wechat_article(self) -> None:
        regular_blocks = [
            {"type": "text", "content": "普通公众号正文第一段"},
            {"type": "image", "url": "https://mmbiz.qpic.cn/inline.jpg"},
            {"type": "text", "content": "普通公众号正文第二段"},
        ]
        parse_result = types.SimpleNamespace(
            extracted_text="[ocr_text]\n配图上的少量文字" * 20,
            ocr_text="配图上的少量文字" * 20,
            frame_texts=[],
            urls=[],
            qr_links=[],
            parse_status="completed",
            parse_error=None,
            parsed_at=datetime.datetime(2026, 7, 15, 12, 0, 0),
        )
        item = Item(
            id="wechat-regular",
            title="普通公众号文章",
            canonical_text="普通公众号正文第一段\n\n普通公众号正文第二段",
            content_blocks_json=json.dumps(regular_blocks, ensure_ascii=False),
            platform="wechat",
        )

        items_router._store_item_parse_result(item, parse_result)

        self.assertEqual(json.loads(item.content_blocks_json), regular_blocks)

    def test_note_route_updates_extracted_text(self) -> None:
        request = items_router.ItemNoteUpdateRequest(extracted_text="手动修改后的解析笔记")

        with self.TestSession() as db:
            with patch.object(items_router, "get_current_user_id", return_value="local-default-user"):
                response = items_router.update_item_note("item-parse-route", request, db=db)

        self.assertEqual(response.extracted_text, "手动修改后的解析笔记")
        self.assertEqual(response.parse_status, "completed")

    def test_content_route_updates_title_and_detected_title_marker(self) -> None:
        request = items_router.ItemContentUpdateRequest(title="新的标题")

        with self.TestSession() as db:
            item = db.query(Item).filter(Item.id == "item-parse-route").one()
            item.extracted_text = "[detected_title]\n旧标题\n[ocr_text]\n原始正文"
            db.commit()

            with patch.object(items_router, "get_current_user_id", return_value="local-default-user"):
                response = items_router.update_item_content("item-parse-route", request, db=db)

        self.assertEqual(response.title, "新的标题")
        self.assertIn("[detected_title]\n新的标题", response.extracted_text or "")
        self.assertIn("[ocr_text]\n原始正文", response.extracted_text or "")

    def test_page_note_routes_create_list_and_update(self) -> None:
        create_request = items_router.ItemPageNoteCreateRequest(
            title="",
            content="第一段 AI 对话结论",
            ai_message_index=1,
        )

        with self.TestSession() as db:
            with patch.object(items_router, "get_current_user_id", return_value="local-default-user"):
                created = items_router.create_item_page_note("item-parse-route", create_request, db=db)
                listed = items_router.list_item_page_notes("item-parse-route", db=db)
                updated = items_router.update_item_page_note(
                    "item-parse-route",
                    created.id,
                    items_router.ItemPageNoteUpdateRequest(
                        title="整理后的页面笔记",
                        content="更新后的内容",
                    ),
                    db=db,
                )

        self.assertEqual(created.ai_message_index, 1)
        self.assertEqual(len(listed.notes), 1)
        self.assertTrue(created.title)
        self.assertEqual(updated.title, "整理后的页面笔记")
        self.assertEqual(updated.content, "更新后的内容")

    def test_page_note_update_derives_blank_title_from_latest_content(self) -> None:
        create_request = items_router.ItemPageNoteCreateRequest(
            title="初始标题",
            content="旧内容",
        )

        with self.TestSession() as db:
            with patch.object(items_router, "get_current_user_id", return_value="local-default-user"):
                created = items_router.create_item_page_note("item-parse-route", create_request, db=db)
                updated = items_router.update_item_page_note(
                    "item-parse-route",
                    created.id,
                    items_router.ItemPageNoteUpdateRequest(
                        title="",
                        content="新的页面笔记内容应该成为标题来源",
                    ),
                    db=db,
                )

        self.assertEqual(updated.content, "新的页面笔记内容应该成为标题来源")
        self.assertTrue(updated.title.startswith("新的页面笔记内容"))

    def test_recover_processing_item_parsing_replays_stuck_jobs(self) -> None:
        with self.TestSession() as db:
            item = db.query(Item).filter(Item.id == "item-parse-route").one()
            item.parse_status = "processing"
            item.parse_started_at = datetime.datetime.utcnow() - datetime.timedelta(hours=1)
            db.commit()

        calls: list[tuple[str, str]] = []
        with patch.object(items_router, "SessionLocal", self.TestSession):
            with patch.object(
                items_router,
                "background_parse_item_content",
                side_effect=lambda item_id, user_id: calls.append((item_id, user_id)),
            ):
                recovered = items_router.recover_processing_item_parsing(limit=5)

        self.assertEqual(recovered, 1)
        self.assertEqual(calls, [("item-parse-route", "local-default-user")])

    def test_recover_processing_item_parsing_skips_recent_jobs(self) -> None:
        with self.TestSession() as db:
            item = db.query(Item).filter(Item.id == "item-parse-route").one()
            item.parse_status = "processing"
            item.parse_started_at = datetime.datetime.utcnow()
            db.commit()

        calls: list[tuple[str, str]] = []
        with patch.object(items_router, "SessionLocal", self.TestSession):
            with patch.object(
                items_router,
                "background_parse_item_content",
                side_effect=lambda item_id, user_id: calls.append((item_id, user_id)),
            ):
                recovered = items_router.recover_processing_item_parsing(
                    limit=5,
                    stale_after=datetime.timedelta(minutes=30),
                )

        self.assertEqual(recovered, 0)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
