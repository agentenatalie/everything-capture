import asyncio
import datetime
import json
import os
import sys
import unittest

from bs4 import BeautifulSoup


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Folder, Item, ItemFolderLink, Media  # noqa: E402
from routers.connect import (  # noqa: E402
    _build_notion_page_properties,
    _build_notion_children,
    _build_obsidian_note,
    _collect_referenced_media,
    _format_item_datetime,
    _get_structured_blocks,
    _sync_blocks,
)
from services.extractor import _extract_article_blocks, _extract_article_html  # noqa: E402


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

    def test_html_fallback_keeps_images_inside_paragraph_wrappers(self) -> None:
        item = Item(
            id="item-inline-image",
            title="Paragraph Wrapped Image",
            source_url="https://example.com/article",
            final_url="https://example.com/article",
            platform="generic",
            canonical_text="Intro\n\nOutro",
            canonical_html=(
                "<article>"
                "<p>Intro</p>"
                '<p><img src="/static/media/first.png" alt="inline image" /></p>'
                "<p>Outro</p>"
                "</article>"
            ),
            created_at=datetime.datetime(2026, 3, 6, 12, 0, 0),
        )

        blocks = _get_structured_blocks(item)

        self.assertEqual(
            blocks,
            [
                {"type": "paragraph", "content": "Intro", "markdown": "Intro"},
                {"type": "image", "url": "/static/media/first.png"},
                {"type": "paragraph", "content": "Outro", "markdown": "Outro"},
            ],
        )

    def test_html_fallback_preserves_preformatted_code_from_span_wrapped_blocks(self) -> None:
        item = Item(
            id="item-code",
            title="Code Sample",
            source_url="https://example.com/repo",
            final_url="https://example.com/repo",
            platform="generic",
            canonical_text="code sample",
            canonical_html=(
                "<article>"
                "<h3>Example</h3>"
                '<div><pre><span>import</span> <span>easyquotation</span>\n'
                '<span>quotation</span>  <span>=</span> <span>easyquotation</span>.<span>use</span>(<span>"daykline"</span>)\n'
                '<span>print</span>(<span>quotation</span>)</pre></div>'
                "</article>"
            ),
            created_at=datetime.datetime(2026, 3, 6, 12, 0, 0),
        )

        blocks = _get_structured_blocks(item)

        self.assertEqual(blocks[0]["type"], "heading_3")
        self.assertEqual(blocks[1]["type"], "code")
        self.assertEqual(
            blocks[1]["content"],
            'import easyquotation\nquotation  = easyquotation.use("daykline")\nprint(quotation)',
        )

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

    def test_obsidian_note_keeps_list_items_compact(self) -> None:
        item = Item(
            id="item-list",
            title="Roadmap",
            source_url="https://example.com/roadmap",
            final_url="https://example.com/roadmap",
            platform="generic",
            canonical_text="Roadmap",
            canonical_html=(
                "<article>"
                "<h2>Roadmap</h2>"
                "<ul>"
                "<li>Claude Code Plugin support</li>"
                "<li>Custom agent (subagent) support</li>"
                "</ul>"
                "</article>"
            ),
            created_at=datetime.datetime(2026, 3, 6, 12, 0, 0),
        )

        note = _build_obsidian_note(item, {})

        self.assertIn("## Roadmap", note)
        self.assertIn("- Claude Code Plugin support\n- Custom agent (subagent) support", note)
        self.assertNotIn("- Claude Code Plugin support\n\n- Custom agent (subagent) support", note)

    def test_obsidian_note_places_parsed_text_code_block_before_source(self) -> None:
        item = self.make_item()
        item.extracted_text = "[ocr_text]\n图片里的原始文字"

        note = _build_obsidian_note(
            item,
            {"/static/media/first.png": "EverythingCapture_Media/item-1234/first.png"},
        )

        self.assertIn("```text\n[ocr_text]\n图片里的原始文字\n```", note)
        self.assertIn("[Source](https://example.com/article)", note)
        self.assertLess(
            note.index("```text\n[ocr_text]\n图片里的原始文字\n```"),
            note.index("[Source](https://example.com/article)"),
        )

    def test_obsidian_note_skips_douyin_cover_when_video_exists(self) -> None:
        item = Item(
            id="item-douyin",
            title="Douyin Video",
            source_url="https://www.douyin.com/video/123",
            final_url="https://www.douyin.com/video/123",
            platform="douyin",
            canonical_text="Douyin video",
            created_at=datetime.datetime(2026, 3, 6, 12, 0, 0),
        )
        item.content_blocks_json = json.dumps(
            [
                {"type": "paragraph", "content": "Video body"},
                {"type": "cover", "url": "/static/media/douyin-cover.webp"},
                {"type": "video", "url": "/static/media/douyin-video.mp4"},
            ]
        )
        item.media = [
            Media(
                id="media-cover",
                item_id=item.id,
                type="cover",
                original_url="https://cdn.example.com/douyin-cover.webp",
                local_path="media/douyin-cover.webp",
                display_order=0,
            ),
            Media(
                id="media-video",
                item_id=item.id,
                type="video",
                original_url="https://cdn.example.com/douyin-video.mp4",
                local_path="media/douyin-video.mp4",
                display_order=1,
            ),
        ]

        note = _build_obsidian_note(
            item,
            {
                "/static/media/douyin-cover.webp": "EverythingCapture_Media/item-douyin/douyin-cover.webp",
                "/static/media/douyin-video.mp4": "EverythingCapture_Media/item-douyin/douyin-video.mp4",
            },
        )
        referenced_media = _collect_referenced_media(item, _sync_blocks(item))

        self.assertNotIn("douyin-cover.webp", note)
        self.assertIn("douyin-video.mp4", note)
        self.assertEqual([media.type for media in referenced_media], ["video"])

    def test_notion_children_skip_douyin_cover_when_video_exists(self) -> None:
        item = Item(
            id="item-douyin-notion",
            title="Douyin Video",
            source_url="https://www.douyin.com/video/456",
            final_url="https://www.douyin.com/video/456",
            platform="douyin",
            canonical_text="Douyin video",
            created_at=datetime.datetime(2026, 3, 6, 12, 0, 0),
        )
        item.content_blocks_json = json.dumps(
            [
                {"type": "paragraph", "content": "Video body"},
                {"type": "cover", "url": "https://cdn.example.com/douyin-cover.webp"},
                {"type": "video", "url": "https://cdn.example.com/douyin-video.mp4"},
            ]
        )

        children = asyncio.run(
            _build_notion_children(
                object(),
                {"Authorization": "Bearer test", "Notion-Version": "2025-09-03"},
                item,
            )
        )

        self.assertEqual([child["type"] for child in children[:2]], ["paragraph", "bookmark"])
        self.assertEqual(children[1]["bookmark"]["url"], "https://cdn.example.com/douyin-video.mp4")

    def test_notion_children_append_parsed_text_after_source(self) -> None:
        item = self.make_item()
        item.extracted_text = "[frame_texts]\n00:01\n视频里的原始文字"

        children = asyncio.run(
            _build_notion_children(
                object(),
                {"Authorization": "Bearer test", "Notion-Version": "2025-09-03"},
                item,
            )
        )

        self.assertEqual(children[-3]["paragraph"]["rich_text"][0]["text"]["content"], "'''")
        self.assertEqual(children[-2]["type"], "code")
        self.assertIn("视频里的原始文字", children[-2]["code"]["rich_text"][0]["text"]["content"])
        self.assertEqual(children[-1]["paragraph"]["rich_text"][0]["text"]["content"], "'''")

    def test_xiaohongshu_sync_omits_trailing_topic_tags(self) -> None:
        item = Item(
            id="item-xhs",
            title="XHS Note",
            source_url="https://www.xiaohongshu.com/explore/123",
            final_url="https://www.xiaohongshu.com/explore/123",
            platform="xiaohongshu",
            canonical_text=(
                "港股和 AI 的一些观察。\n"
                "#港股[话题]# #ai[话题]# #minimax[话题]# #我的理财日记[话题]# #港股 #ai #minimax #我的理财日记"
            ),
            created_at=datetime.datetime(2026, 3, 6, 12, 0, 0),
        )
        item.content_blocks_json = json.dumps(
            [
                {
                    "type": "paragraph",
                    "content": (
                        "港股和 AI 的一些观察。 "
                        "#港股[话题]# #ai[话题]# #minimax[话题]# #我的理财日记[话题]# #港股 #ai #minimax #我的理财日记"
                    ),
                    "markdown": (
                        "港股和 AI 的一些观察。 "
                        "#港股[话题]# #ai[话题]# #minimax[话题]# #我的理财日记[话题]# #港股 #ai #minimax #我的理财日记"
                    ),
                }
            ]
        )

        note = _build_obsidian_note(item, {})
        children = asyncio.run(
            _build_notion_children(
                object(),
                {"Authorization": "Bearer test", "Notion-Version": "2025-09-03"},
                item,
            )
        )

        self.assertIn("港股和 AI 的一些观察。", note)
        self.assertNotIn("#港股[话题]#", note)
        self.assertNotIn("#我的理财日记", note)
        self.assertEqual(children[0]["paragraph"]["rich_text"][0]["text"]["content"], "港股和 AI 的一些观察。")

    def test_notion_page_properties_include_sync_fields(self) -> None:
        item = self.make_item()
        folder_a = Folder(id="folder-a", name="Alpha")
        folder_b = Folder(id="folder-b", name="Beta")
        item.folder_links = [
            ItemFolderLink(
                item_id=item.id,
                folder_id="folder-b",
                folder=folder_b,
                created_at=datetime.datetime(2026, 3, 6, 12, 2, 0),
            ),
            ItemFolderLink(
                item_id=item.id,
                folder_id="folder-a",
                folder=folder_a,
                created_at=datetime.datetime(2026, 3, 6, 12, 1, 0),
            ),
        ]

        properties = _build_notion_page_properties(
            item,
            {
                "title_property_name": "Name",
                "sync_property_names": {
                    "date": "Date",
                    "source": "Source",
                    "platform": "Platform",
                    "folder": "Folder",
                },
            },
        )

        self.assertEqual(properties["Name"]["title"][0]["text"]["content"], "Sample Capture")
        self.assertEqual(properties["Date"]["rich_text"][0]["text"]["content"], "03/06 07:00")
        self.assertEqual(properties["Source"]["url"], "https://example.com/article")
        self.assertEqual(properties["Platform"]["rich_text"][0]["text"]["content"], "generic")
        self.assertEqual(properties["Folder"]["rich_text"][0]["text"]["content"], "Alpha, Beta")

    def test_obsidian_note_frontmatter_includes_ordered_folder_property(self) -> None:
        item = self.make_item()
        folder_a = Folder(id="folder-a", name="Alpha")
        folder_b = Folder(id="folder-b", name="Beta")
        item.folder_links = [
            ItemFolderLink(
                item_id=item.id,
                folder_id="folder-b",
                folder=folder_b,
                created_at=datetime.datetime(2026, 3, 6, 12, 2, 0),
            ),
            ItemFolderLink(
                item_id=item.id,
                folder_id="folder-a",
                folder=folder_a,
                created_at=datetime.datetime(2026, 3, 6, 12, 1, 0),
            ),
        ]

        note = _build_obsidian_note(item, {"/static/media/first.png": "EverythingCapture_Media/item-1234/first.png"})

        self.assertIn('folder: "Alpha, Beta"', note)

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

    def test_extractor_prefers_new_content_container_over_site_shell(self) -> None:
        soup = BeautifulSoup(
            (
                "<html><body>"
                "<h1>眼馋苹果刚发布的液态玻璃效果？藏师傅教你提示词一键实现</h1>"
                "<div id='h5-menu-panel'>站点导航 首页 AI资讯 APP 下载 热门搜索 大模型 人工智能</div>"
                "<div id='app'>"
                "<div class='changebutton'>正文</div>"
                "<div class='changebutton'>资源拓展</div>"
                "<div class='newContent' id='content1'>"
                "<p>小编PS：亲测提示词，UI效果是可以完全复现的，但是水纹的动态效果没能复现成功。</p>"
                "<p><img src='https://cdn.example.com/inline.jpg' alt='inline'></p>"
                "<p>这里藏师傅也是一上午探索了一下如何将液态玻璃效果融入到网页生成的提示词里面。</p>"
                "</div>"
                "<div class='newContent' id='content2'><p>资源拓展</p><p>cursor</p></div>"
                "</div>"
                "<div>底部下载栏 IOS下载 安卓下载 微信群</div>"
                "</body></html>"
            ),
            "html.parser",
        )

        blocks = _extract_article_blocks(soup, "https://example.com/article")
        html = _extract_article_html(soup, "https://example.com/article")
        text_content = "\n".join(block["content"] for block in blocks if block["type"] == "text")

        self.assertIn("小编PS：亲测提示词", text_content)
        self.assertIn("如何将液态玻璃效果融入到网页生成的提示词里面", text_content)
        self.assertNotIn("站点导航", text_content)
        self.assertNotIn("热门搜索", text_content)
        self.assertNotIn("底部下载栏", text_content)
        self.assertIsNotNone(html)
        self.assertIn("小编PS：亲测提示词", html)
        self.assertIn("https://cdn.example.com/inline.jpg", html)
        self.assertNotIn("站点导航", html)
        self.assertNotIn("资源拓展", html)


if __name__ == "__main__":
    unittest.main()
