import asyncio
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Item, Settings  # noqa: E402
from routers import ai as ai_router  # noqa: E402
from schemas import AiAskRequest, AiAssistantRequest, AiConversationMessage  # noqa: E402
from security import encrypt_secret  # noqa: E402
from services.knowledge_base import KnowledgeBaseNote, KnowledgeBaseSnapshot, prepare_note_for_similarity  # noqa: E402
from database import Base  # noqa: E402


class AiRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

        with self.Session() as db:
            db.add(
                Item(
                    id="item-ai",
                    user_id="local-default-user",
                    workspace_id="local-default-workspace",
                    title="AI 写的 UI 太丑？这个 Skill 救了我",
                    source_url="https://example.com/ui",
                    canonical_text="AI 生成 UI 缺乏设计一致性，需要设计规范和打磨。",
                    platform="generic",
                    status="ready",
                )
            )
            db.add(
                Settings(
                    user_id="local-default-user",
                    workspace_id="local-default-workspace",
                    ai_api_key=encrypt_secret("test-ai-key"),
                    ai_base_url="https://api.example.com/v1",
                    ai_model="test-model",
                )
            )
            db.commit()

    def tearDown(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def _make_snapshot(self) -> KnowledgeBaseSnapshot:
        current = prepare_note_for_similarity(
            KnowledgeBaseNote(
                note_id="AI/Coding/ui-skill.md",
                title="AI 写的 UI 太丑？这个 Skill 救了我",
                summary="impeccable 插件让 AI 生成 UI 从能用升级到专业美观",
                body="正文",
                excerpt="AI 做 UI 的问题在于缺少设计规范和系统性打磨。",
                extracted_text="",
                tags=["AI/UI设计", "VibeCoding"],
                folder="AI/Coding",
                source="https://example.com/ui",
                created_at=datetime(2026, 3, 12, 10, 0, 0),
                relative_path="AI/Coding/ui-skill.md",
                item_id="item-ai",
            )
        )
        related = prepare_note_for_similarity(
            KnowledgeBaseNote(
                note_id="AI/Coding/component-gallery.md",
                title="Vibe Coding 的时候不知道怎么描述 UI？",
                summary="Component Gallery 让提示词准确描述 UI 组件",
                body="正文",
                excerpt="可以直接看不同设计系统里的真实组件。",
                extracted_text="",
                tags=["VibeCoding", "UI设计"],
                folder="AI/Coding",
                source="https://example.com/gallery",
                created_at=datetime(2026, 3, 11, 10, 0, 0),
                relative_path="AI/Coding/component-gallery.md",
                item_id="item-related",
            )
        )
        return KnowledgeBaseSnapshot(
            root_path="/tmp/Sources.base",
            notes=[current, related],
            loaded_at=datetime.utcnow(),
        )

    def test_ask_ai_returns_answer_and_citations(self) -> None:
        request = AiAskRequest(question="我之前保存过哪些关于 AI UI 设计的内容？", top_k=4)

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "load_knowledge_base_snapshot",
                return_value=self._make_snapshot(),
            ), patch.object(
                ai_router,
                "chat_completion",
                return_value="你保存过两类和 AI UI 设计相关的内容：[1] 关于 impeccable 打磨界面，[2] 关于 Component Gallery 帮助描述组件。",
            ):
                response = asyncio.run(ai_router.ask_ai(request, db=db))

        self.assertIn("AI UI 设计", response.answer)
        self.assertEqual(len(response.citations), 2)
        self.assertEqual(response.citations[0].title, "AI 写的 UI 太丑？这个 Skill 救了我")

    def test_analyze_item_returns_structured_fields(self) -> None:
        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "load_knowledge_base_snapshot",
                return_value=self._make_snapshot(),
            ), patch.object(
                ai_router,
                "chat_completion",
                return_value=(
                    '{'
                    '"one_liner":"这条笔记的核心价值是把 AI UI 的问题从能力不足转成规范缺失。",'
                    '"core_points":["问题不在模型能力，在设计规范缺失","impeccable 适合作为后处理打磨层"],'
                    '"why_saved":"因为它解释了为什么 AI UI 常常差最后一口气。",'
                    '"themes":["AI/UI设计","VibeCoding"],'
                    '"thinking_questions":["我的工作流里是否也缺少统一设计规范？"]'
                    '}'
                ),
            ):
                response = asyncio.run(ai_router.analyze_item("item-ai", db=db))

        self.assertEqual(response.item_id, "item-ai")
        self.assertEqual(response.themes, ["AI/UI设计", "VibeCoding"])
        self.assertIn("规范缺失", response.one_liner)
        self.assertGreaterEqual(len(response.citations), 1)

    def test_assistant_chat_returns_message_and_citations(self) -> None:
        request = AiAssistantRequest(
            mode="chat",
            messages=[AiConversationMessage(role="user", content="总结我保存过的 AI UI 设计内容")],
            top_k=4,
        )

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "load_knowledge_base_snapshot",
                return_value=self._make_snapshot(),
            ), patch.object(
                ai_router,
                "chat_completion",
                return_value="你保存过的 AI UI 设计内容主要集中在界面打磨和组件表达两个方向。[1][2]",
            ):
                response = asyncio.run(ai_router.assistant(request, db=db))

        self.assertEqual(response.mode, "chat")
        self.assertIn("AI UI 设计", response.message)
        self.assertEqual(len(response.citations), 2)
        self.assertFalse(response.insufficient_context)

    def test_assistant_agent_executes_tool_and_returns_tool_events(self) -> None:
        request = AiAssistantRequest(
            mode="agent",
            messages=[AiConversationMessage(role="user", content="帮我看看最近跟 AI UI 设计相关的笔记")],
        )
        tool_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-1",
                                "type": "function",
                                "function": {
                                    "name": "search_knowledge_base",
                                    "arguments": '{"query":"AI UI 设计","limit":2}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
        final_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "我找到了两条最相关的笔记，分别关于 AI UI 打磨和组件表达。",
                    }
                }
            ]
        }

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "load_knowledge_base_snapshot",
                return_value=self._make_snapshot(),
            ), patch.object(
                ai_router,
                "create_chat_completion",
                side_effect=[tool_payload, final_payload],
            ):
                response = asyncio.run(ai_router.assistant(request, db=db))

        self.assertEqual(response.mode, "agent")
        self.assertEqual(len(response.tool_events), 1)
        self.assertEqual(response.tool_events[0].name, "search_knowledge_base")
        self.assertGreaterEqual(len(response.citations), 1)
        self.assertIn("两条", response.message)

    def test_related_notes_uses_local_knowledge_base_even_without_ai_call(self) -> None:
        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "load_knowledge_base_snapshot",
                return_value=self._make_snapshot(),
            ):
                response = ai_router.related_notes("item-ai", limit=3, db=db)

        self.assertEqual(response.item_id, "item-ai")
        self.assertEqual(len(response.related), 1)
        self.assertEqual(response.related[0].title, "Vibe Coding 的时候不知道怎么描述 UI？")


if __name__ == "__main__":
    unittest.main()
