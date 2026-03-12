import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Item, Media  # noqa: E402
from services.content_extraction import parse_item_content, parse_subtitle_lines  # noqa: E402


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

    @patch("services.content_extraction._find_video_companion_text")
    @patch("services.content_extraction._resolve_media_inputs")
    @patch("services.content_extraction._run_swift_media_extractor")
    def test_parse_item_content_merges_text_ocr_and_subtitle(self, mock_swift, mock_media_inputs, mock_companion) -> None:
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
        }
        # Video has a subtitle companion
        mock_companion.return_value = ("今天我们来聊聊这个话题\n非常有意思", "subtitle")

        result = parse_item_content(item)

        self.assertEqual(result.parse_status, "completed")
        self.assertEqual(result.source_type, "mixed")
        self.assertEqual(result.detected_title, "图文解析测试")
        self.assertIn("海报标题", result.ocr_text)
        # Videos no longer produce frame_texts (no frame OCR)
        self.assertEqual(result.frame_texts, [])
        # Images still produce QR links; videos do not
        self.assertEqual(result.qr_links, ["https://qr.example.com"])
        # URLs come from canonical_text and image OCR only (not video)
        self.assertEqual(
            result.urls,
            [
                "https://example.com/source",
                "https://foo.bar/path",
                "https://image.example.com/page",
            ],
        )
        self.assertIn("[ocr_text]", result.extracted_text)
        self.assertIn("[subtitle_text]", result.extracted_text)
        self.assertIn("今天我们来聊聊", result.extracted_text)
        # Swift was called with videos=[] (no video OCR)
        mock_swift.assert_called_once_with(images=mock_media_inputs.return_value["images"], videos=[])

    @patch("services.content_extraction._transcribe_video_with_mlx_whisper")
    @patch("services.content_extraction._extract_embedded_subtitles")
    @patch("services.content_extraction._find_video_companion_text")
    @patch("services.content_extraction._resolve_media_inputs")
    @patch("services.content_extraction._run_swift_media_extractor")
    def test_parse_item_content_video_no_subtitle_no_transcript(self, mock_swift, mock_media_inputs, mock_companion, mock_embedded, mock_whisper) -> None:
        item = self.make_item()
        mock_media_inputs.return_value = {
            "images": [],
            "videos": [{"path": "/tmp/video.mp4", "type": "video", "relative_path": "video.mp4"}],
        }
        mock_companion.return_value = ("", "")
        mock_embedded.return_value = ""
        mock_whisper.return_value = ""

        result = parse_item_content(item)

        self.assertEqual(result.frame_texts, [])
        self.assertEqual(result.ocr_text, "")
        self.assertNotIn("[subtitle_text]", result.extracted_text)
        self.assertNotIn("[transcript_text]", result.extracted_text)
        mock_swift.assert_not_called()
        # Verify fallback chain: companion → embedded → whisper
        mock_companion.assert_called_once()
        mock_embedded.assert_called_once()
        mock_whisper.assert_called_once()

    @patch("services.content_extraction._transcribe_video_with_mlx_whisper")
    @patch("services.content_extraction._extract_embedded_subtitles")
    @patch("services.content_extraction._find_video_companion_text")
    @patch("services.content_extraction._resolve_media_inputs")
    @patch("services.content_extraction._run_swift_media_extractor")
    def test_parse_item_content_whisper_fallback_produces_transcript(self, mock_swift, mock_media_inputs, mock_companion, mock_embedded, mock_whisper) -> None:
        item = self.make_item()
        mock_media_inputs.return_value = {
            "images": [],
            "videos": [{"path": "/tmp/video.mp4", "type": "video", "relative_path": "video.mp4"}],
        }
        mock_companion.return_value = ("", "")
        mock_embedded.return_value = ""
        mock_whisper.return_value = "这是一段测试转录文本"

        result = parse_item_content(item)

        self.assertIn("[transcript_text]", result.extracted_text)
        self.assertIn("这是一段测试转录文本", result.extracted_text)
        self.assertNotIn("[subtitle_text]", result.extracted_text)

    @patch("services.content_extraction._transcribe_video_with_mlx_whisper")
    @patch("services.content_extraction._extract_embedded_subtitles")
    @patch("services.content_extraction._find_video_companion_text")
    @patch("services.content_extraction._resolve_media_inputs")
    @patch("services.content_extraction._run_swift_media_extractor")
    def test_parse_item_content_embedded_subtitle_skips_whisper(self, mock_swift, mock_media_inputs, mock_companion, mock_embedded, mock_whisper) -> None:
        item = self.make_item()
        mock_media_inputs.return_value = {
            "images": [],
            "videos": [{"path": "/tmp/video.mp4", "type": "video", "relative_path": "video.mp4"}],
        }
        mock_companion.return_value = ("", "")
        mock_embedded.return_value = "嵌入字幕内容"

        result = parse_item_content(item)

        self.assertIn("[subtitle_text]", result.extracted_text)
        self.assertIn("嵌入字幕内容", result.extracted_text)
        self.assertNotIn("[transcript_text]", result.extracted_text)
        # Whisper should NOT be called when embedded subtitles are found
        mock_whisper.assert_not_called()

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


class SubtitleParsingTests(unittest.TestCase):
    def test_parse_srt_content(self) -> None:
        srt = "1\n00:00:01,000 --> 00:00:03,000\n你好世界\n\n2\n00:00:04,000 --> 00:00:06,000\n你好世界\n测试字幕\n"
        result = parse_subtitle_lines(srt)
        self.assertEqual(result, "你好世界\n测试字幕")

    def test_parse_vtt_content(self) -> None:
        vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<b>Hello</b> world\n\n00:00:04.000 --> 00:00:06.000\nHello world\nSecond line\n"
        result = parse_subtitle_lines(vtt)
        self.assertEqual(result, "Hello world\nSecond line")

    def test_empty_input(self) -> None:
        self.assertEqual(parse_subtitle_lines(""), "")


if __name__ == "__main__":
    unittest.main()
