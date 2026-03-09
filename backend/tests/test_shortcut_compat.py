import os
import sys
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from auth import reset_request_user_id, set_request_user_id  # noqa: E402
from database import Base  # noqa: E402
from models import Item, User  # noqa: E402
from routers.ingest import _resolve_extract_url, _store_shared_text_capture  # noqa: E402
from schemas import ExtractRequest  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
