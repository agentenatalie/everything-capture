import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Item, Media  # noqa: E402
from services.content_extraction import parse_item_content  # noqa: E402


class ContentExtractionTests(unittest.TestCase):
    def make_item(self) -> Item:
        item = Item(
            id="item-parse-1",
            title="图文解析测试",
            canonical_text="原始正文里有链接 https://example.com/source 和第二个链接 https://foo.bar/path",
            platform="generic",
        )
        item.media = [
            Media(
                id="media-image-1",
                item_id=item.id,
                type="image",
                local_path="media/users/test-user/item-parse-1/image_000.png",
                display_order=0,
            ),
            Media(
                id="media-video-1",
                item_id=item.id,
                type="video",
                local_path="media/users/test-user/item-parse-1/video_000.mp4",
                display_order=1,
            ),
        ]
        return item

    @patch("services.content_extraction._resolve_media_inputs")
    @patch("services.content_extraction._run_swift_media_extractor")
    def test_parse_item_content_merges_text_ocr_video_and_qr_results(self, mock_swift, mock_media_inputs) -> None:
        item = self.make_item()
        mock_media_inputs.return_value = {
            "images": [{"path": "/tmp/image.png", "type": "image", "relative_path": "image.png"}],
            "videos": [{"path": "/tmp/video.mp4", "type": "video", "relative_path": "video.mp4"}],
        }
        mock_swift.return_value = {
            "images": [
                {
                    "path": "/tmp/image.png",
                    "ocr_text": "海报标题\n访问 https://image.example.com/page",
                    "qr_links": ["https://qr.example.com"],
                    "urls": ["https://image.example.com/page"],
                }
            ],
            "videos": [
                {
                    "path": "/tmp/video.mp4",
                    "frame_texts": [
                        {"timestamp_seconds": 1.2, "text": "第一帧文字"},
                        {"timestamp_seconds": 9.8, "text": "第二帧 https://video.example.com"},
                    ],
                    "qr_links": ["https://video-qr.example.com"],
                    "urls": ["https://video.example.com"],
                }
            ],
        }

        result = parse_item_content(item)

        self.assertEqual(result.parse_status, "completed")
        self.assertEqual(result.source_type, "mixed")
        self.assertEqual(result.detected_title, "图文解析测试")
        self.assertIn("海报标题", result.ocr_text)
        self.assertEqual(len(result.frame_texts), 2)
        self.assertEqual(
            result.urls,
            [
                "https://example.com/source",
                "https://foo.bar/path",
                "https://image.example.com/page",
                "https://video.example.com",
            ],
        )
        self.assertEqual(
            result.qr_links,
            [
                "https://qr.example.com",
                "https://video-qr.example.com",
            ],
        )
        self.assertIn("[ocr_text]", result.extracted_text)
        self.assertIn("[frame_texts]", result.extracted_text)
        self.assertIn("00:10", result.extracted_text)

    @patch("services.content_extraction._resolve_media_inputs")
    def test_parse_item_content_handles_text_only_items(self, mock_media_inputs) -> None:
        item = Item(
            id="item-parse-2",
            title="",
            canonical_text="第一行标题\n\n正文内容 https://docs.example.com",
            platform="web",
        )
        item.media = []
        mock_media_inputs.return_value = {"images": [], "videos": []}

        result = parse_item_content(item)

        self.assertEqual(result.source_type, "text")
        self.assertEqual(result.detected_title, "第一行标题")
        self.assertEqual(result.urls, ["https://docs.example.com"])
        self.assertIn("[detected_title]\n第一行标题", result.extracted_text)
        self.assertIn("[urls]\nhttps://docs.example.com", result.extracted_text)


if __name__ == "__main__":
    unittest.main()
