import asyncio
import datetime
import json
import os
import sys
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Item, Media  # noqa: E402
from routers.connect import (  # noqa: E402
    _build_notion_children,
    _build_obsidian_note,
    _get_structured_blocks,
)


class HtmlFallbackFormattingTests(unittest.TestCase):
    def make_item(self, *, with_content_blocks: bool = False) -> Item:
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
        if with_content_blocks:
            item.content_blocks_json = json.dumps(
                [
                    {"type": "text", "content": "Structured block wins"},
                    {"type": "image", "url": "/static/media/first.png"},
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

    def test_existing_structured_blocks_override_html_fallback(self) -> None:
        item = self.make_item(with_content_blocks=True)

        blocks = _get_structured_blocks(item)

        self.assertEqual(blocks[0]["content"], "Structured block wins")
        self.assertEqual(blocks[1]["url"], "/static/media/first.png")

    def test_obsidian_note_keeps_inline_image_and_markdown(self) -> None:
        item = self.make_item()

        note = _build_obsidian_note(
            item,
            {"/static/media/first.png": "EverythingCapture_Media/item-1234/first.png"},
        )

        self.assertIn("## Intro Section", note)
        self.assertIn("Start **bold** and [linked text](https://example.com/ref).", note)
        self.assertIn("![[EverythingCapture_Media/item-1234/first.png]]", note)
        self.assertIn("- First bullet", note)
        self.assertIn("> Quoted *idea*.", note)
        self.assertLess(note.index("Start **bold**"), note.index("![[EverythingCapture_Media/item-1234/first.png]]"))
        self.assertLess(note.index("![[EverythingCapture_Media/item-1234/first.png]]"), note.index("After image paragraph."))

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


if __name__ == "__main__":
    unittest.main()
