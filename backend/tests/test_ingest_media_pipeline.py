import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routers.ingest import (  # noqa: E402
    _replace_media_urls_in_blocks,
    _replace_media_urls_in_html,
    _serialize_content_blocks,
    _should_background_media_processing,
)


class IngestMediaPipelineTests(unittest.TestCase):
    def test_replace_media_urls_in_blocks_swaps_remote_urls(self) -> None:
        blocks = [
            {"type": "text", "content": "Lead"},
            {"type": "image", "url": "https://cdn.example.com/image.jpg"},
            {"type": "video", "url": "https://cdn.example.com/video.mp4"},
        ]

        result = _replace_media_urls_in_blocks(
            blocks,
            {
                "https://cdn.example.com/image.jpg": "/static/media/image.jpg",
                "https://cdn.example.com/video.mp4": "/static/media/video.mp4",
            },
        )

        self.assertEqual(
            result,
            _serialize_content_blocks(
                [
                    {"type": "text", "content": "Lead"},
                    {"type": "image", "url": "/static/media/image.jpg"},
                    {"type": "video", "url": "/static/media/video.mp4"},
                ]
            ),
        )

    def test_replace_media_urls_in_html_swaps_img_and_video_sources(self) -> None:
        html = """
        <article>
          <p>Lead</p>
          <img src="https://cdn.example.com/image.jpg">
          <video src="https://cdn.example.com/video.mp4"></video>
        </article>
        """

        result = _replace_media_urls_in_html(
            html,
            {
                "https://cdn.example.com/image.jpg": "/static/media/image.jpg",
                "https://cdn.example.com/video.mp4": "/static/media/video.mp4",
            },
        )

        self.assertIn('/static/media/image.jpg', result)
        self.assertIn('/static/media/video.mp4', result)
        self.assertNotIn('https://cdn.example.com/image.jpg', result)


class IngestMediaSchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_media_processing_only_for_mobile_long_video(self) -> None:
        mobile_request = SimpleNamespace(headers={"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile"}, cookies={})
        desktop_request = SimpleNamespace(headers={"user-agent": "Mozilla/5.0 Chrome/122.0"}, cookies={})
        media_list = [{"type": "video", "url": "https://www.youtube.com/watch?v=test"}]

        with patch("routers.ingest.probe_video_duration_seconds", return_value=16 * 60):
            self.assertTrue(await _should_background_media_processing(mobile_request, media_list, "https://example.com"))
            self.assertFalse(await _should_background_media_processing(desktop_request, media_list, "https://example.com"))

        with patch("routers.ingest.probe_video_duration_seconds", return_value=5 * 60):
            self.assertFalse(await _should_background_media_processing(mobile_request, media_list, "https://example.com"))


if __name__ == "__main__":
    unittest.main()
