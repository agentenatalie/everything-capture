import os
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.extractor import (  # noqa: E402
    _build_douyin_page_media_reference,
    _ensure_douyin_video_candidate,
    _extract_article_blocks,
    _extract_article_html,
    _extract_page_media,
    _parse_douyin_slides_response,
    _parse_xhs_initial_state,
    _parse_douyin_router_data,
    _parse_x_article_result,
    _parse_twitter_oembed_html,
    extract_douyin,
    extract_twitter,
    extract_generic,
)
from services.downloader import download_media_list  # noqa: E402
from services.downloader import download_file  # noqa: E402
from services.downloader import _should_retry_video_via_referer_page  # noqa: E402


class _StaticHtmlHandler(BaseHTTPRequestHandler):
    html = ""

    def do_GET(self):  # noqa: N802
        body = self.html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A003
        return


class _InterruptingBinaryHandler(BaseHTTPRequestHandler):
    payload = (b"0123456789abcdef" * 393216) + b"tail"
    cutoff = 4 * 1024 * 1024

    def do_GET(self):  # noqa: N802
        total = len(self.payload)
        range_header = self.headers.get("Range")

        if range_header and range_header.startswith("bytes="):
            start_str = range_header.split("=", 1)[1].split("-", 1)[0].strip()
            start = int(start_str or "0")
            body = self.payload[start:]
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Range", f"bytes {start}-{total - 1}/{total}")
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            self.wfile.write(body)
            return

        body = self.payload[: self.cutoff]
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(total))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        self.close_connection = True

    def log_message(self, format, *args):  # noqa: A003
        return


class ExtractorMediaTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_xhs_initial_state_uses_desc_first_line_when_title_missing(self) -> None:
        html = """
        <html><body><script>
        window.__INITIAL_STATE__ = {
          "noteData": {
            "data": {
              "noteData": {
                "title": "",
                "desc": "一篇读懂 | OpenClaw“养龙虾”指南：不只是“养”，更要“防”\\n\\n最近，工业和信息化部网络安全威胁和漏洞信息共享平台监测发现，OpenClaw 在默认配置下存在较高安全风险。",
                "imageList": [
                  {
                    "urlDefault": "//sns-webpic-qc.xhscdn.com/example.jpg"
                  }
                ],
                "tagList": [
                  {"name": "热点"}
                ]
              }
            }
          }
        };
        </script></body></html>
        """

        result = _parse_xhs_initial_state(html)

        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "一篇读懂 | OpenClaw“养龙虾”指南：不只是“养”，更要“防”")
        self.assertTrue(result["text"].startswith("一篇读懂 | OpenClaw“养龙虾”指南：不只是“养”，更要“防”"))
        self.assertEqual(result["text"].count("一篇读懂 | OpenClaw“养龙虾”指南：不只是“养”，更要“防”"), 1)
        self.assertIn("最近，工业和信息化部网络安全威胁", result["text"])
        self.assertEqual(
            result["media_urls"],
            [{"type": "image", "url": "https://sns-webpic-qc.xhscdn.com/example.jpg", "order": 0}],
        )

    def test_parse_xhs_initial_state_extracts_video_notes(self) -> None:
        html = """
        <html><body><script>
        window.__INITIAL_STATE__ = {
          "noteData": {
            "data": {
              "noteData": {
                "title": "会动的产品展示页",
                "desc": "用 AI 做 3D 风动效网页",
                "imageList": [
                  {
                    "urlDefault": "//sns-webpic-qc.xhscdn.com/video-cover.jpg"
                  }
                ],
                "video": {
                  "media": {
                    "stream": {
                      "h264": [
                        {
                          "masterUrl": "http://sns-video-alos.xhscdn.com/example.mp4",
                          "avgBitrate": 800000
                        }
                      ]
                    }
                  }
                }
              }
            }
          }
        };
        </script></body></html>
        """

        result = _parse_xhs_initial_state(html)

        self.assertIsNotNone(result)
        self.assertEqual(
            result["media_urls"],
            [
                {"type": "video", "url": "http://sns-video-alos.xhscdn.com/example.mp4", "order": 0},
                {"type": "cover", "url": "https://sns-webpic-qc.xhscdn.com/video-cover.jpg", "order": 0},
            ],
        )

    def test_build_douyin_page_media_reference_returns_video_entry(self) -> None:
        self.assertEqual(
            _build_douyin_page_media_reference("https://v.douyin.com/test123/"),
            [{"type": "video", "url": "https://v.douyin.com/test123/", "order": 0}],
        )

    def test_ensure_douyin_video_candidate_prepends_page_video_when_only_cover_exists(self) -> None:
        self.assertEqual(
            _ensure_douyin_video_candidate(
                [{"type": "cover", "url": "https://cdn.example.com/cover.webp", "order": 0}],
                "https://www.iesdouyin.com/share/video/1234567890/",
            ),
            [
                {"type": "video", "url": "https://www.iesdouyin.com/share/video/1234567890/", "order": 0},
                {"type": "cover", "url": "https://cdn.example.com/cover.webp", "order": 0},
            ],
        )

    def test_parse_douyin_router_data_extracts_media_from_script_assignment(self) -> None:
        html = """
        <html><body><script>
        window._ROUTER_DATA = {
          "loaderData": {
            "video_(id)": {
              "videoInfoRes": {
                "item_list": [{
                  "desc": "石油美元的底层逻辑",
                  "author": {
                    "nickname": "财经观察",
                    "signature": "长期研究金融与舆论"
                  },
                  "text_extra": [
                    {"hashtag_name": "石油美元"},
                    {"hashtag_name": "金融与舆论"}
                  ],
                  "video": {
                    "bit_rate": [
                      {
                        "bit_rate": 480000,
                        "play_addr": {
                          "url_list": ["https://cdn.example.com/low.mp4"]
                        }
                      },
                      {
                        "bit_rate": 1280000,
                        "play_addr_h264": {
                          "url_list": ["https://aweme.snssdk.com/aweme/v1/playwm/?video_id=high"]
                        }
                      }
                    ],
                    "play_addr": {
                      "url_list": ["https://aweme.snssdk.com/aweme/v1/playwm/?video_id=fallback"]
                    },
                    "origin_cover": {
                      "url_list": ["https://cdn.example.com/cover.webp"]
                    }
                  }
                }]
              }
            }
          }
        };
        window.__NEXT_DATA__ = {"unused": true};
        </script></body></html>
        """

        result = _parse_douyin_router_data(html, "石油美元")

        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "石油美元")
        self.assertIn("财经观察", result["text"])
        self.assertIn("#石油美元", result["text"])
        self.assertEqual(
            result["media_urls"],
            [
                {"type": "video", "url": "https://aweme.snssdk.com/aweme/v1/play/?video_id=high", "order": 0},
                {"type": "cover", "url": "https://cdn.example.com/cover.webp", "order": 0},
            ],
        )

    async def test_extract_douyin_keeps_page_video_reference_when_only_desc_exists(self) -> None:
        class _FakeResponse:
            def __init__(self) -> None:
                self.text = """
                <html>
                  <head>
                    <title>长视频案例 - 抖音</title>
                    <meta name="description" content="这是一个只有描述没有直链的视频页面">
                  </head>
                  <body></body>
                </html>
                """
                self.url = "https://www.iesdouyin.com/share/video/1234567890/"

            def raise_for_status(self) -> None:
                return None

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url):
                return _FakeResponse()

        with patch("services.extractor._build_client", return_value=_FakeClient()):
            with patch("services.extractor._extract_douyin_with_ytdlp", return_value=None):
                result = await extract_douyin("https://v.douyin.com/test123/")

        self.assertIsNotNone(result)
        self.assertEqual(result.platform, "douyin")
        self.assertEqual(
            result.media_urls,
            [{"type": "video", "url": "https://www.iesdouyin.com/share/video/1234567890/", "order": 0}],
        )

    async def test_extract_douyin_uses_ytdlp_metadata_when_router_data_has_only_cover(self) -> None:
        class _FakeResponse:
            def __init__(self) -> None:
                self.text = """
                <html>
                  <head><title>长视频案例 - 抖音</title></head>
                  <body>
                    <script>
                      window._ROUTER_DATA = {
                        "loaderData": {
                          "video_(id)": {
                            "videoInfoRes": {
                              "item_list": [{
                                "desc": "这是长视频描述",
                                "video": {
                                  "cover": {
                                    "url_list": ["https://cdn.example.com/cover.webp"]
                                  }
                                }
                              }]
                            }
                          }
                        }
                      };
                    </script>
                  </body>
                </html>
                """
                self.url = "https://www.iesdouyin.com/share/video/1234567890/"

            def raise_for_status(self) -> None:
                return None

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url):
                return _FakeResponse()

        with patch("services.extractor._build_client", return_value=_FakeClient()):
            with patch(
                "services.extractor._extract_douyin_with_ytdlp",
                return_value={
                    "title": "长视频案例",
                    "text": "长视频案例\n\n这是长视频描述",
                    "media_urls": [
                        {"type": "video", "url": "https://www.iesdouyin.com/share/video/1234567890/", "order": 0},
                        {"type": "cover", "url": "https://cdn.example.com/ytdlp-cover.webp", "order": 0},
                    ],
                },
            ):
                result = await extract_douyin("https://v.douyin.com/test123/")

        self.assertIsNotNone(result)
        self.assertEqual(result.platform, "douyin")
        self.assertEqual(result.media_urls[0]["type"], "video")
        self.assertEqual(result.media_urls[0]["url"], "https://www.iesdouyin.com/share/video/1234567890/")

    def test_parse_douyin_slides_response_extracts_images(self) -> None:
        result = _parse_douyin_slides_response(
            {
                "aweme_details": [
                    {
                        "aweme_id": "7615238530122883769",
                        "preview_title": "Gemini互联网世界中绝对冷静地观察者",
                        "desc": "Gemini互联网世界中绝对冷静地观察者",
                        "author": {"nickname": "AI观察员"},
                        "images": [
                            {
                                "url_list": ["https://p3-sign.douyinpic.com/example-1.webp"],
                                "download_url_list": ["https://p3-sign.douyinpic.com/example-1-download.webp"],
                            },
                            {
                                "url_list": ["https://p3-sign.douyinpic.com/example-2.webp"],
                                "download_url_list": ["https://p3-sign.douyinpic.com/example-2-download.webp"],
                            },
                        ],
                    }
                ]
            }
        )

        self.assertIsNotNone(result)
        self.assertEqual(result["title"], "Gemini互联网世界中绝对冷静地观察者")
        self.assertIn("作者：AI观察员", result["text"])
        self.assertEqual(
            result["media_urls"],
            [
                {"type": "image", "url": "https://p3-sign.douyinpic.com/example-1.webp", "order": 0},
                {"type": "image", "url": "https://p3-sign.douyinpic.com/example-2.webp", "order": 1},
            ],
        )

    async def test_extract_douyin_uses_slides_api_when_share_page_has_no_text(self) -> None:
        class _FakeResponse:
            def __init__(self) -> None:
                self.text = "<html><head><title>抖音</title></head><body></body></html>"
                self.url = "https://www.iesdouyin.com/share/slides/7615238530122883769/"

            def raise_for_status(self) -> None:
                return None

        class _FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url):
                return _FakeResponse()

        with patch("services.extractor._build_client", return_value=_FakeClient()):
            with patch(
                "services.extractor._extract_douyin_slides_info",
                return_value={
                    "title": "图文笔记标题",
                    "text": "图文笔记标题\n\n正文",
                    "media_urls": [
                        {"type": "image", "url": "https://p3-sign.douyinpic.com/example.webp", "order": 0}
                    ],
                },
            ):
                result = await extract_douyin("https://v.douyin.com/test123/")

        self.assertIsNotNone(result)
        self.assertEqual(result.platform, "douyin")
        self.assertEqual(result.title, "图文笔记标题")
        self.assertEqual(result.media_urls[0]["type"], "image")

    def test_page_media_detects_youtube_iframe(self) -> None:
        soup = BeautifulSoup(
            """
            <html><body><article>
              <p>Intro</p>
              <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?feature=oembed"></iframe>
            </article></body></html>
            """,
            "lxml",
        )

        media = _extract_page_media(soup)

        self.assertEqual(len(media), 1)
        self.assertEqual(media[0]["type"], "video")
        self.assertEqual(media[0]["url"], "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_article_blocks_preserve_video_position(self) -> None:
        soup = BeautifulSoup(
            """
            <html><body><article>
              <p>Before</p>
              <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>
              <p>After</p>
            </article></body></html>
            """,
            "lxml",
        )

        blocks = _extract_article_blocks(soup)

        self.assertEqual(
            blocks,
            [
                {"type": "text", "content": "Before"},
                {"type": "video", "url": "https://www.youtube.com/embed/dQw4w9WgXcQ"},
                {"type": "text", "content": "After"},
            ],
        )

    def test_article_html_keeps_sanitized_iframe(self) -> None:
        soup = BeautifulSoup(
            """
            <html><body><article>
              <p>Lead</p>
              <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ?si=test" style="display:none"></iframe>
              <script>alert(1)</script>
            </article></body></html>
            """,
            "lxml",
        )

        html = _extract_article_html(soup)

        self.assertIsNotNone(html)
        self.assertIn('iframe', html)
        self.assertIn('https://www.youtube.com/embed/dQw4w9WgXcQ', html)
        self.assertNotIn('script', html)
        self.assertNotIn('style=', html)

    async def test_extract_generic_accepts_media_only_page(self) -> None:
        _StaticHtmlHandler.html = """
        <html>
          <head><title>Embedded Video Test</title></head>
          <body>
            <article>
              <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>
            </article>
          </body>
        </html>
        """

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = ThreadingHTTPServer(("127.0.0.1", port), _StaticHtmlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = await extract_generic(f"http://127.0.0.1:{port}/")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertIsNotNone(result)
        self.assertEqual(result.title, "Embedded Video Test")
        self.assertEqual(result.text, "Embedded Video Test")
        self.assertIsNotNone(result.media_urls)
        self.assertEqual(result.media_urls[0]["url"], "https://www.youtube.com/embed/dQw4w9WgXcQ")

    def test_parse_twitter_oembed_html_extracts_text(self) -> None:
        result = _parse_twitter_oembed_html(
            "jack",
            """
            <blockquote class="twitter-tweet">
              <p lang="en" dir="ltr">just setting up my twttr</p>
              &mdash; jack (@jack)
              <a href="https://twitter.com/jack/status/20">March 21, 2006</a>
            </blockquote>
            """,
        )

        self.assertIsNotNone(result)
        self.assertIn("jack", result.text)
        self.assertIn("just setting up my twttr", result.text)
        self.assertIn("March 21, 2006", result.text)

    def test_parse_x_article_result_extracts_text_and_media(self) -> None:
        result = _parse_x_article_result(
            {
                "title": "Article Title",
                "plain_text": "Paragraph one.\n\nParagraph two.",
                "cover_media": {
                    "media_info": {
                        "preview_image": {
                            "original_img_url": "https://pbs.twimg.com/media/cover.jpg"
                        }
                    }
                },
                "media_entities": [
                    {
                        "media_info": {
                            "variants": [
                                {
                                    "content_type": "video/mp4",
                                    "url": "https://video.twimg.com/ext_tw_video/1/pu/vid/avc1/test.mp4",
                                    "bit_rate": 832000,
                                }
                            ]
                        }
                    }
                ],
            },
            "https://x.com/i/article/123",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.title, "Article Title")
        self.assertIn("Paragraph one.", result.text)
        self.assertEqual(result.media_urls[0]["type"], "cover")
        self.assertEqual(result.media_urls[1]["type"], "video")

    async def test_extract_twitter_uses_article_path_for_x_article_urls(self) -> None:
        with patch(
            "services.extractor._extract_twitter_article",
            return_value=None,
        ) as mocked_article:
            with patch("services.extractor._extract_twitter_fallback", return_value=None):
                await extract_twitter("https://x.com/i/article/2030427028026277888")

        mocked_article.assert_called_once_with(
            "https://x.com/i/article/2030427028026277888",
            "2030427028026277888",
        )

    async def test_download_media_list_keeps_external_reference_when_video_url_returns_html(self) -> None:
        _StaticHtmlHandler.html = "<html><body>embed page</body></html>"

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = ThreadingHTTPServer(("127.0.0.1", port), _StaticHtmlHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch("services.downloader.should_keep_external_media", return_value=True):
                results = await download_media_list(
                    "test-item",
                    [{"type": "video", "url": f"http://127.0.0.1:{port}/video", "order": 0}],
                    referer=f"http://127.0.0.1:{port}/",
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["original_url"], f"http://127.0.0.1:{port}/video")
        self.assertEqual(results[0]["local_path"], "")

    async def test_download_media_list_uses_ytdlp_for_youtube_urls(self) -> None:
        item_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "media", "test-youtube"))
        os.makedirs(item_dir, exist_ok=True)
        final_path = os.path.join(item_dir, "video_000.mp4")
        with open(final_path, "wb") as fp:
            fp.write(b"video")

        try:
            with patch(
                "services.downloader._download_with_ytdlp",
                return_value=(Path(final_path), 5),
            ) as mocked_ytdlp:
                results = await download_media_list(
                    "test-youtube",
                    [{"type": "video", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "order": 0}],
                    referer="https://example.com/article",
                )
        finally:
            if os.path.exists(final_path):
                os.remove(final_path)
            if os.path.isdir(item_dir):
                try:
                    os.rmdir(item_dir)
                except OSError:
                    pass

        mocked_ytdlp.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["local_path"], "media/test-youtube/video_000.mp4")

    async def test_download_media_list_uses_ytdlp_for_douyin_page_urls(self) -> None:
        item_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "media", "test-douyin"))
        os.makedirs(item_dir, exist_ok=True)
        final_path = os.path.join(item_dir, "video_000.mp4")
        with open(final_path, "wb") as fp:
            fp.write(b"video")

        try:
            with patch(
                "services.downloader._download_with_ytdlp",
                return_value=(Path(final_path), 5),
            ) as mocked_ytdlp:
                results = await download_media_list(
                    "test-douyin",
                    [{"type": "video", "url": "https://v.douyin.com/test123/", "order": 0}],
                    referer="https://example.com/article",
                )
        finally:
            if os.path.exists(final_path):
                os.remove(final_path)
            if os.path.isdir(item_dir):
                try:
                    os.rmdir(item_dir)
                except OSError:
                    pass

        mocked_ytdlp.assert_called_once()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["local_path"], "media/test-douyin/video_000.mp4")

    def test_should_retry_video_via_referer_page_for_protected_douyin_cdn(self) -> None:
        self.assertTrue(
            _should_retry_video_via_referer_page(
                "https://aweme.snssdk.com/aweme/v1/play/?video_id=1",
                "video",
                "https://www.iesdouyin.com/share/video/123/",
            )
        )
        self.assertFalse(
            _should_retry_video_via_referer_page(
                "https://cdn.example.com/video.mp4",
                "video",
                "https://www.iesdouyin.com/share/video/123/",
            )
        )

    async def test_download_file_resumes_after_midstream_disconnect(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        server = ThreadingHTTPServer(("127.0.0.1", port), _InterruptingBinaryHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        save_path = Path(tempfile.gettempdir()) / "douyin-resume-test.mp4"
        try:
            final_path, file_size = await download_file(
                f"http://127.0.0.1:{port}/video.mp4",
                save_path,
                "video",
                referer=f"http://127.0.0.1:{port}/",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            if save_path.exists():
                save_path.unlink()

        self.assertIsNotNone(final_path)
        self.assertEqual(file_size, len(_InterruptingBinaryHandler.payload))

    async def test_download_media_list_uses_user_scoped_media_path(self) -> None:
        item_dir = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "static",
                "media",
                "users",
                "user-123",
                "test-youtube-user",
            )
        )
        os.makedirs(item_dir, exist_ok=True)
        final_path = os.path.join(item_dir, "video_000.mp4")
        with open(final_path, "wb") as fp:
            fp.write(b"video")

        try:
            with patch(
                "services.downloader._download_with_ytdlp",
                return_value=(Path(final_path), 5),
            ):
                results = await download_media_list(
                    "test-youtube-user",
                    [{"type": "video", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "order": 0}],
                    referer="https://example.com/article",
                    user_id="user-123",
                )
        finally:
            if os.path.exists(final_path):
                os.remove(final_path)
            current_dir = item_dir
            for _ in range(4):
                if os.path.isdir(current_dir):
                    try:
                        os.rmdir(current_dir)
                    except OSError:
                        break
                current_dir = os.path.dirname(current_dir)

        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["local_path"],
            "media/users/user-123/test-youtube-user/video_000.mp4",
        )


if __name__ == "__main__":
    unittest.main()
