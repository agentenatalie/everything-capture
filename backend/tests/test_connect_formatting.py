import asyncio
import datetime
import json
import os
import sys
import unittest

from bs4 import BeautifulSoup


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Item, Media  # noqa: E402
from routers.connect import (  # noqa: E402
    _build_notion_page_properties,
    _build_notion_children,
    _build_obsidian_note,
    _format_item_datetime,
    _get_structured_blocks,
)
from services.extractor import _extract_article_blocks  # noqa: E402


class HtmlFallbackFormattingTests(unittest.TestCase):
    def make_item(self, *, content_block_mode: str | None = None) -> Item:
        item = Item(
            id="item-1234",
            title="Sample Capture",
            source_url="https://example.com/article",
            final_url="https://example.com/article",
            platform="generic",
            canonical_text="Intro text\n\nAfter image",
            canonical_html=(
                "<article>"
                "<h2>Intro Section</h2>"
                '<p>Start <strong>bold</strong> and <a href="https://example.com/ref">linked text</a>.</p>'
                '<a href="https://example.com/full"><picture><img src="/static/media/first.png" alt="inline image" /></picture></a>'
                "<p>After image paragraph.</p>"
                "<ul><li>First bullet</li><li>Second bullet</li></ul>"
                "<blockquote>Quoted <em>idea</em>.</blockquote>"
                "</article>"
            ),
            created_at=datetime.datetime(2026, 3, 6, 12, 0, 0),
        )
        item.media = [
            Media(
                id="media-1",
                item_id=item.id,
                type="image",
                original_url="https://cdn.example.com/first.png",
                local_path="media/first.png",
                display_order=0,
                inline_position=0.5,
            )
        ]
        if content_block_mode == "rich":
            item.content_blocks_json = json.dumps(
                [
                    {"type": "heading_2", "content": "Structured block wins"},
                    {"type": "image", "url": "/static/media/first.png"},
                ]
            )
        elif content_block_mode == "text_only":
            item.content_blocks_json = json.dumps(
                [
                    {"type": "text", "content": "Flattened title"},
                    {"type": "text", "content": "Flattened paragraph without inline media"},
                ]
            )
        return item

    def test_html_fallback_generates_ordered_blocks(self) -> None:
        item = self.make_item()

        blocks = _get_structured_blocks(item)

        self.assertEqual(
            [block["type"] for block in blocks[:6]],
            ["heading_2", "paragraph", "image", "paragraph", "bulleted_list_item", "bulleted_list_item"],
        )
        self.assertEqual(blocks[2]["url"], "/static/media/first.png")
        self.assertEqual(blocks[1]["markdown"], "Start **bold** and [linked text](https://example.com/ref).")

    def test_rich_structured_blocks_override_html_fallback(self) -> None:
        item = self.make_item(content_block_mode="rich")

        blocks = _get_structured_blocks(item)

        self.assertEqual(blocks[0]["content"], "Structured block wins")
        self.assertEqual(blocks[1]["url"], "/static/media/first.png")

    def test_text_only_structured_blocks_fall_back_to_html(self) -> None:
        item = self.make_item(content_block_mode="text_only")

        blocks = _get_structured_blocks(item)

        self.assertEqual(
            [block["type"] for block in blocks[:4]],
            ["heading_2", "paragraph", "image", "paragraph"],
        )
        self.assertEqual(blocks[2]["url"], "/static/media/first.png")

    def test_obsidian_note_keeps_inline_image_and_markdown(self) -> None:
        item = self.make_item()

        note = _build_obsidian_note(
            item,
            {"/static/media/first.png": "EverythingCapture_Media/item-1234/first.png"},
        )

        self.assertIn("## Intro Section", note)
        self.assertIn("date: 03/06 07:00", note)
        self.assertIn("Start **bold** and [linked text](https://example.com/ref).", note)
        self.assertIn("![[EverythingCapture_Media/item-1234/first.png]]", note)
        self.assertIn("- First bullet", note)
        self.assertIn("> Quoted *idea*.", note)
        self.assertLess(note.index("Start **bold**"), note.index("![[EverythingCapture_Media/item-1234/first.png]]"))
        self.assertLess(note.index("![[EverythingCapture_Media/item-1234/first.png]]"), note.index("After image paragraph."))

    def test_notion_page_properties_include_sync_fields(self) -> None:
        item = self.make_item()

        properties = _build_notion_page_properties(
            item,
            {
                "title_property_name": "Name",
                "sync_property_names": {
                    "date": "Date",
                    "source": "Source",
                    "platform": "Platform",
                },
            },
        )

        self.assertEqual(properties["Name"]["title"][0]["text"]["content"], "Sample Capture")
        self.assertEqual(properties["Date"]["rich_text"][0]["text"]["content"], "03/06 07:00")
        self.assertEqual(properties["Source"]["url"], "https://example.com/article")
        self.assertEqual(properties["Platform"]["rich_text"][0]["text"]["content"], "generic")

    def test_notion_children_keep_inline_image_order(self) -> None:
        item = self.make_item()

        children = asyncio.run(_build_notion_children(object(), {"Authorization": "Bearer test", "Notion-Version": "2025-09-03"}, item))

        self.assertEqual(
            [child["type"] for child in children[:6]],
            ["heading_2", "paragraph", "image", "paragraph", "bulleted_list_item", "bulleted_list_item"],
        )
        self.assertEqual(children[0]["heading_2"]["rich_text"][0]["text"]["content"], "Intro Section")
        self.assertEqual(children[1]["paragraph"]["rich_text"][0]["text"]["content"], "Start bold and linked text.")
        self.assertEqual(children[2]["image"]["type"], "external")

    def test_datetime_format_matches_expected_style(self) -> None:
        self.assertEqual(
            _format_item_datetime(datetime.datetime(2026, 3, 5, 17, 11, 0)),
            "03/05 12:11",
        )

    def test_extractor_keeps_images_inside_wrapper_elements(self) -> None:
        soup = BeautifulSoup(
            (
                "<article>"
                "<p>Intro</p>"
                '<a href="https://example.com/full"><picture><img src="https://cdn.example.com/inline.jpg" /></picture></a>'
                "<p>Outro</p>"
                "</article>"
            ),
            "html.parser",
        )

        blocks = _extract_article_blocks(soup, "https://example.com/article")

        self.assertEqual(
            blocks,
            [
                {"type": "text", "content": "Intro"},
                {"type": "image", "url": "https://cdn.example.com/inline.jpg"},
                {"type": "text", "content": "Outro"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
