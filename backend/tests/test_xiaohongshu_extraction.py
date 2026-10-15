import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.extractor import (  # noqa: E402
    _parse_xhs_initial_state,
    extract_content,
    extract_xiaohongshu,
)


def note_html(note, **state):
    state["note"] = {"noteDetailMap": {"example": {"note": note}}}
    return "<script>window.__INITIAL_STATE__=" + json.dumps(state) + ";</script>"


class XiaohongshuParsingTests(unittest.TestCase):
    def test_short_image_note_keeps_media(self):
        result = _parse_xhs_initial_state(note_html({
            "title": "随手拍",
            "desc": "",
            "imageList": [{"urlDefault": "//cdn.example.com/photo.jpg"}],
        }))
        self.assertIsNotNone(result)
        self.assertEqual(result["text"], "随手拍")
        self.assertEqual(result["media_urls"][0]["url"], "https://cdn.example.com/photo.jpg")

    def test_video_note_without_caption_keeps_media(self):
        result = _parse_xhs_initial_state(note_html({
            "video": {"media": {"stream": {"h264": [
                {"masterUrl": "https://cdn.example.com/video.mp4"},
            ]}}},
        }))
        self.assertIsNotNone(result)
        self.assertEqual(result["media_urls"][0]["type"], "video")

    def test_undefined_values_do_not_change_note_text(self):
        html = note_html({"title": "JavaScript undefined", "desc": "保留正文中的 undefined"})
        html = html.replace('"note": {', '"unused": undefined, "note": {', 1)
        result = _parse_xhs_initial_state(html)
        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "JavaScript undefined")
        self.assertIn("正文中的 undefined", result["text"])

    def test_null_state_sections_do_not_crash(self):
        html = '<script>window.__INITIAL_STATE__={"note":null,"noteData":null};</script>'
        self.assertIsNone(_parse_xhs_initial_state(html))

    def test_short_text_without_media_is_still_rejected(self):
        self.assertIsNone(_parse_xhs_initial_state(note_html({"title": "短文本"})))


class XiaohongshuRequestTests(unittest.IsolatedAsyncioTestCase):
    def client_for(self, html, url, status=200):
        response = httpx.Response(status, text=html, request=httpx.Request("GET", url))
        client = MagicMock()
        client.get = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)
        return context, client

    async def test_retries_desktop_page_and_preserves_share_query(self):
        url = "https://www.xiaohongshu.com/explore/example?xsec_token=example&xsec_source=pc_share"
        mobile, mobile_client = self.client_for("<html><body>打开小红书</body></html>", url)
        desktop, desktop_client = self.client_for(note_html({
            "title": "图片笔记", "imageList": [{"urlDefault": "https://cdn.example.com/photo.jpg"}],
        }), url)
        with patch("services.extractor._build_client", side_effect=[mobile, desktop]):
            result = await extract_xiaohongshu(url)
        self.assertIsNotNone(result)
        self.assertEqual(result.title, "图片笔记")
        self.assertEqual(result.final_url, url)
        mobile_client.get.assert_awaited_once_with(url)
        desktop_client.get.assert_awaited_once_with(url)

    async def test_retries_desktop_after_mobile_http_failure(self):
        url = "https://www.xiaohongshu.com/explore/example"
        mobile, _ = self.client_for("", url, status=403)
        desktop, _ = self.client_for(note_html({
            "title": "图片笔记", "imageList": [{"urlDefault": "https://cdn.example.com/photo.jpg"}],
        }), url)
        with patch("services.extractor._build_client", side_effect=[mobile, desktop]):
            result = await extract_xiaohongshu(url)
        self.assertIsNotNone(result)

    async def test_login_page_is_not_saved_as_note(self):
        url = "https://www.xiaohongshu.com/explore/example"
        html = "<html><head><title>小红书</title></head><body>登录后查看完整笔记，打开小红书 App 扫码登录，更多精彩内容等你发现。</body></html>"
        contexts = [self.client_for(html, url)[0] for _ in range(2)]
        with patch("services.extractor._build_client", side_effect=contexts):
            with patch("services.extractor.extract_generic", new_callable=AsyncMock) as generic:
                result = await extract_content(url)
        self.assertEqual(result.title, "提取失败")
        self.assertEqual(result.text, "")
        generic.assert_not_awaited()

    async def test_metadata_fallback_keeps_short_note_image(self):
        url = "https://www.xiaohongshu.com/explore/example"
        html = '<html><head><title>小红书</title><meta property="og:title" content="图片笔记"><meta property="og:image" content="https://cdn.example.com/photo.jpg"></head><body>打开小红书</body></html>'
        context, _ = self.client_for(html, url)
        with patch("services.extractor._build_client", return_value=context):
            result = await extract_xiaohongshu(url)
        self.assertIsNotNone(result)
        self.assertEqual(result.media_urls[0]["url"], "https://cdn.example.com/photo.jpg")

    async def test_verification_and_unavailable_pages_are_rejected(self):
        for title in ("安全验证", "当前笔记暂时无法浏览"):
            with self.subTest(title=title):
                url = "https://www.xiaohongshu.com/explore/example"
                html = f"<html><head><title>{title}</title></head><body>{title}，请在小红书 App 内打开以继续查看此笔记。</body></html>"
                contexts = [self.client_for(html, url)[0] for _ in range(2)]
                with patch("services.extractor._build_client", side_effect=contexts):
                    self.assertIsNone(await extract_xiaohongshu(url))
