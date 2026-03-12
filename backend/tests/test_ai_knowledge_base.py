import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.knowledge_base import (  # noqa: E402
    KnowledgeBaseNote,
    KnowledgeBaseSnapshot,
    parse_knowledge_note,
    prepare_note_for_similarity,
    rank_notes_for_query,
    rank_related_notes,
)


class KnowledgeBaseParsingTests(unittest.TestCase):
    def test_parse_knowledge_note_reads_summary_tags_and_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            note_path = root / "AI" / "Coding" / "design-note-1234abcd.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(
                "---\n"
                "item_id: item-123\n"
                "source: https://example.com/design\n"
                "platform: web\n"
                "date: 03/12 10:46\n"
                'folder: "AI / Coding"\n'
                "摘要: 现有 summary 应优先作为 AI 理解入口\n"
                "tags:\n"
                "  - UI设计\n"
                "  - VibeCoding\n"
                "---\n\n"
                "# 设计提示词\n\n"
                "这是正文。\n\n"
                "```text\n"
                "[ocr_text]\n截图里的文字\n"
                "```\n",
                encoding="utf-8",
            )

            note = parse_knowledge_note(note_path, root)

        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note.item_id, "item-123")
        self.assertEqual(note.title, "设计提示词")
        self.assertEqual(note.summary, "现有 summary 应优先作为 AI 理解入口")
        self.assertEqual(note.tags, ["UI设计", "VibeCoding"])
        self.assertEqual(note.folder, "AI / Coding")
        self.assertEqual(note.relative_path, "AI/Coding/design-note-1234abcd.md")
        self.assertIn("截图里的文字", note.extracted_text)


class KnowledgeBaseRankingTests(unittest.TestCase):
    def make_note(self, note_id: str, **overrides) -> KnowledgeBaseNote:
        payload = {
            "note_id": note_id,
            "title": f"Note {note_id}",
            "summary": "",
            "body": "",
            "excerpt": "",
            "extracted_text": "",
            "tags": [],
            "folder": "General",
            "source": None,
            "created_at": datetime(2026, 3, 12, 12, 0, 0),
            "relative_path": f"{note_id}.md",
            "item_id": note_id,
        }
        payload.update(overrides)
        return prepare_note_for_similarity(KnowledgeBaseNote(**payload))

    def test_rank_notes_for_query_prioritizes_summary_terms(self) -> None:
        snapshot = KnowledgeBaseSnapshot(
            root_path="/tmp/Sources.base",
            notes=[
                self.make_note(
                    "ui-skill",
                    title="AI 写的 UI 太丑？这个 Skill 救了我",
                    summary="impeccable 插件让 AI 生成 UI 从能用升级到专业美观",
                    tags=["AI/UI设计"],
                    folder="AI/Coding",
                ),
                self.make_note(
                    "finance-note",
                    title="宏观复盘",
                    summary="关于利率和市场情绪的观察",
                    tags=["Finance"],
                    folder="Finance",
                ),
            ],
            loaded_at=datetime.utcnow(),
        )

        ranked = rank_notes_for_query(snapshot, "有哪些关于 AI UI 设计的内容？", limit=2)

        self.assertEqual(ranked[0][0].note_id, "ui-skill")

    def test_rank_related_notes_prefers_shared_theme_and_terms(self) -> None:
        seed = self.make_note(
            "seed",
            title="Vibe Coding 的时候不知道怎么描述 UI？",
            summary="Component Gallery 让提示词准确描述 UI 组件",
            tags=["VibeCoding", "UI设计"],
            folder="AI/Coding",
        )
        related = self.make_note(
            "related",
            title="AI 写的 UI 太丑？这个 Skill 救了我",
            summary="impeccable 插件改善 AI 生成 UI 的设计一致性",
            tags=["VibeCoding", "UI设计"],
            folder="AI/Coding",
        )
        unrelated = self.make_note(
            "unrelated",
            title="投资复盘",
            summary="记录市场与套利逻辑",
            tags=["Finance"],
            folder="Finance",
        )
        snapshot = KnowledgeBaseSnapshot(
            root_path="/tmp/Sources.base",
            notes=[seed, related, unrelated],
            loaded_at=datetime.utcnow(),
        )

        ranked = rank_related_notes(snapshot, seed, limit=2)

        self.assertEqual(ranked[0][0].note_id, "related")


if __name__ == "__main__":
    unittest.main()
