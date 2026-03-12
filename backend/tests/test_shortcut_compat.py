import os
import sys
import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth import reset_request_user_id, set_request_user_id  # noqa: E402
from database import Base  # noqa: E402
from models import Folder, Item, User  # noqa: E402
from routers.ingest import _resolve_extract_url, _store_shared_text_capture, execute_extract_request, ingest_page  # noqa: E402
from routers.phone_webapp import build_phone_extract_item_finalizer  # noqa: E402
from schemas import ClientInfo, ExtractRequest, IngestRequest, PhoneExtractRequest  # noqa: E402
from services.extractor import ExtractResult  # noqa: E402
from tenant import DEFAULT_USER_EMAIL, DEFAULT_USER_ID, DEFAULT_USER_NAME  # noqa: E402


class _BackgroundTasksStub:
    def __init__(self) -> None:
        self.calls = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.calls.append((func, args, kwargs))


class ShortcutCompatibilityTests(unittest.TestCase):
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

    def test_resolve_extract_url_accepts_shortcut_text_payload(self) -> None:
        request = ExtractRequest(
            text="这是我从 Safari 分享出来的内容 https://example.com/article?id=1&utm=test"
        )

        self.assertEqual(
            _resolve_extract_url(request),
            "https://example.com/article?id=1&utm=test",
        )

    def test_store_shared_text_capture_saves_text_when_no_url_exists(self) -> None:
        background_tasks = _BackgroundTasksStub()
        request = ExtractRequest(
            text="一段没有链接的分享文本\n\n第二段内容",
            title="快捷指令文本",
        )

        request_token = set_request_user_id(DEFAULT_USER_ID)
        try:
            with self.Session() as db:
                response = _store_shared_text_capture(
                    request,
                    db,
                    DEFAULT_USER_ID,
                    background_tasks,
                )

                self.assertEqual(response.status, "ready")
                self.assertEqual(response.platform, "web")
                self.assertEqual(response.title, "快捷指令文本")
                self.assertEqual(len(background_tasks.calls), 1)

                item = db.query(Item).filter(Item.id == response.item_id).first()
                self.assertIsNotNone(item)
                self.assertEqual(item.canonical_text, "一段没有链接的分享文本\n\n第二段内容")
                self.assertEqual(item.title, "快捷指令文本")
                self.assertIn("<p>", item.canonical_html)
        finally:
            reset_request_user_id(request_token)

    def test_phone_extract_assigns_requested_folder(self) -> None:
        background_tasks = _BackgroundTasksStub()

        with self.Session() as db:
            folder = Folder(user_id=DEFAULT_USER_ID, name="Inbox")
            db.add(folder)
            db.commit()
            db.refresh(folder)
            folder_id = folder.id

        request = PhoneExtractRequest(
            text="一段准备归档到文件夹的文本",
            title="归档文本",
            folder_id=folder_id,
        )

        request_token = set_request_user_id(DEFAULT_USER_ID)
        try:
            with self.Session() as db:
                response, _ = asyncio.run(
                    execute_extract_request(
                        request,
                        None,
                        background_tasks,
                        db,
                        DEFAULT_USER_ID,
                        item_finalizer=build_phone_extract_item_finalizer(request, db, DEFAULT_USER_ID),
                    )
                )

                item = db.query(Item).filter(Item.id == response.item_id).first()
                self.assertIsNotNone(item)
                self.assertEqual(item.folder_id, folder_id)
                self.assertEqual([link.folder_id for link in item.folder_links], [folder_id])
        finally:
            reset_request_user_id(request_token)

    def test_ingest_page_persists_supplied_html_formatting(self) -> None:
        background_tasks = _BackgroundTasksStub()
        request = IngestRequest(
            source_url="https://example.com/article",
            final_url="https://example.com/article",
            title="带排版的文章",
            canonical_text="Start bold link",
            canonical_html='<article><p>Start <strong>bold</strong> and <a href="https://example.com/ref">link</a>.</p><script>alert(1)</script></article>',
            client=ClientInfo(platform="ios"),
        )

        request_token = set_request_user_id(DEFAULT_USER_ID)
        try:
            with self.Session() as db:
                response = ingest_page(request, background_tasks, db)
                item = db.query(Item).filter(Item.id == response.item_id).first()
                self.assertIsNotNone(item)
                self.assertIn("<strong>bold</strong>", item.canonical_html)
                self.assertIn('href="https://example.com/ref"', item.canonical_html)
                self.assertNotIn("<script>", item.canonical_html)
        finally:
            reset_request_user_id(request_token)

    def test_execute_extract_request_marks_parse_processing_and_schedules_postprocess_after_media_download(self) -> None:
        background_tasks = _BackgroundTasksStub()
        request = ExtractRequest(url="https://example.com/article")
        http_request = SimpleNamespace(headers={"user-agent": "Mozilla/5.0"}, cookies={})
        extract_result = ExtractResult(
            title="带视频的文章",
            text="正文内容足够长，可以入库。",
            platform="web",
            final_url="https://example.com/article",
            media_urls=[
                {"type": "video", "url": "https://cdn.example.com/video.mp4", "order": 0},
                {"type": "cover", "url": "https://cdn.example.com/cover.jpg", "order": 1},
            ],
            content_blocks=[{"type": "text", "content": "正文内容足够长，可以入库。"}],
            content_html="<p>正文内容足够长，可以入库。</p>",
        )

        request_token = set_request_user_id(DEFAULT_USER_ID)
        try:
            with self.Session() as db, patch(
                "routers.ingest.extract_content",
                new=AsyncMock(return_value=extract_result),
            ), patch(
                "routers.ingest._should_background_media_processing",
                new=AsyncMock(return_value=False),
            ), patch(
                "routers.ingest._download_and_apply_media_updates",
                new=AsyncMock(return_value=2),
            ):
                response, item = asyncio.run(
                    execute_extract_request(
                        request,
                        http_request,
                        background_tasks,
                        db,
                        DEFAULT_USER_ID,
                    )
                )

                self.assertEqual(response.status, "ready")
                self.assertEqual(response.media_count, 2)
                self.assertEqual(item.parse_status, "processing")
                self.assertEqual(len(background_tasks.calls), 1)
                self.assertEqual(background_tasks.calls[0][0].__name__, "_spawn_capture_postprocess")

                saved_item = db.query(Item).filter(Item.id == response.item_id).first()
                self.assertIsNotNone(saved_item)
                self.assertEqual(saved_item.parse_status, "processing")
        finally:
            reset_request_user_id(request_token)


if __name__ == "__main__":
    unittest.main()
