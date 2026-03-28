import asyncio
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import Folder, Item, Settings  # noqa: E402
from routers import ai as ai_router  # noqa: E402
from schemas import (  # noqa: E402
    AiAskRequest,
    AiAssistantRequest,
    AiConversationMessage,
    AiConversationSaveRequest,
    AiConversationStoredMessage,
)
from security import encrypt_secret  # noqa: E402
from services.knowledge_base import KnowledgeBaseNote, KnowledgeBaseSnapshot, prepare_note_for_similarity  # noqa: E402
from database import Base  # noqa: E402

_SNAPSHOT_FUNC = "_build_items_only_snapshot"


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
                    extracted_text="内容分析：这条内容强调 AI 做 UI 的问题不只是模型能力，而是缺少统一视觉规范。",
                    ocr_text="AI UI 设计规范",
                    parse_status="completed",
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
            db.add(
                Folder(
                    id="folder-ai",
                    user_id="local-default-user",
                    workspace_id="local-default-workspace",
                    name="AI 设计",
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

    def _make_rag_context(
        self,
        *,
        insufficient_context: bool = False,
        note_count: int = 2,
    ) -> ai_router.RagGroundedContext:
        snapshot = self._make_snapshot()
        ranked_notes = [
            (snapshot.notes[0], 0.98),
            (snapshot.notes[1], 0.91),
        ]
        return ai_router.RagGroundedContext(
            context_text=(
                "[1] 标题: AI 写的 UI 太丑？这个 Skill 救了我\n"
                "[1] 摘要: impeccable 插件让 AI 生成 UI 从能用升级到专业美观\n"
                "[1] 相关片段1: AI 做 UI 的问题在于缺少设计规范和系统性打磨。\n\n"
                "[2] 标题: Vibe Coding 的时候不知道怎么描述 UI？\n"
                "[2] 摘要: Component Gallery 让提示词准确描述 UI 组件\n"
                "[2] 相关片段1: 可以直接看不同设计系统里的真实组件。"
            ),
            ranked_notes=ranked_notes,
            note_count=note_count,
            insufficient_context=insufficient_context,
            retrieval_mode="semantic",
        )

    def test_ask_ai_returns_answer_and_citations(self) -> None:
        request = AiAskRequest(question="我之前保存过哪些关于 AI UI 设计的内容？", top_k=4)

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "_retrieve_rag_context",
                return_value=self._make_rag_context(),
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
                _SNAPSHOT_FUNC,
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
                "_retrieve_rag_context",
                return_value=self._make_rag_context(),
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

    def test_assistant_chat_can_answer_from_current_item_context_without_kb(self) -> None:
        request = AiAssistantRequest(
            mode="chat",
            current_item_id="item-ai",
            messages=[AiConversationMessage(role="user", content="请总结当前这条内容")],
            top_k=4,
        )
        captured_messages: list[list[dict]] = []

        async def fake_chat_completion(**kwargs):
            captured_messages.append(kwargs["messages"])
            return "这条内容主要在讨论 AI UI 为什么容易缺少设计一致性，以及如何通过规范和组件表达来改善。[1]"

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "_retrieve_rag_context",
                return_value=ai_router.RagGroundedContext(
                    context_text="[1] 标题: AI 写的 UI 太丑？这个 Skill 救了我\n[1] 相关片段1: AI 做 UI 的问题在于缺少设计规范。",
                    ranked_notes=[(self._make_snapshot().notes[0], 0.99)],
                    note_count=1,
                    insufficient_context=False,
                    retrieval_mode="semantic",
                ),
            ), patch.object(
                ai_router,
                "chat_completion",
                side_effect=fake_chat_completion,
            ):
                response = asyncio.run(ai_router.assistant(request, db=db))

        self.assertEqual(response.mode, "chat")
        self.assertIn("AI UI", response.message)
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].library_item_id, "item-ai")
        self.assertFalse(response.insufficient_context)
        self.assertEqual([message.get("role") for message in captured_messages[0]], ["system", "user"])
        self.assertIn("下面是当前文章上下文", captured_messages[0][0]["content"])

    def test_resolve_ai_config_requires_base_url(self) -> None:
        settings = Settings(
            ai_api_key=encrypt_secret("test-ai-key"),
            ai_model="test-model",
        )

        with self.assertRaises(ai_router.HTTPException) as ctx:
            ai_router._resolve_ai_config(settings)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "AI settings are incomplete: ai_base_url")

    def test_assistant_agent_includes_current_item_context(self) -> None:
        request = AiAssistantRequest(
            mode="agent",
            current_item_id="item-ai",
            messages=[AiConversationMessage(role="user", content="请总结当前文章，并说明怎么处理这类内容")],
        )
        captured_messages: list[list[dict]] = []
        final_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "当前文章主要在讲 AI UI 需要设计规范和后处理打磨。[1]",
                    }
                }
            ]
        }

        async def fake_create_chat_completion(**kwargs):
            captured_messages.append(kwargs["messages"])
            return final_payload

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                _SNAPSHOT_FUNC,
                return_value=KnowledgeBaseSnapshot(
                    root_path="/tmp/Sources.base",
                    notes=[],
                    loaded_at=datetime.utcnow(),
                ),
            ), patch.object(
                ai_router,
                "create_chat_completion",
                side_effect=fake_create_chat_completion,
            ):
                response = asyncio.run(ai_router.assistant(request, db=db))

        self.assertEqual(response.mode, "agent")
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].library_item_id, "item-ai")
        self.assertIn("设计规范", response.message)
        self.assertEqual([message.get("role") for message in captured_messages[0]], ["system", "user"])
        self.assertIn("当前文章 item_id：item-ai", str(captured_messages[0][0].get("content", "")))

    def test_organize_item_analysis_persists_updated_extracted_text(self) -> None:
        captured_system_prompt = ""
        captured_user_prompt = ""

        async def fake_chat_completion(**kwargs):
            nonlocal captured_system_prompt
            nonlocal captured_user_prompt
            messages = kwargs.get("messages") or []
            captured_system_prompt = next(
                (str(message.get("content", "")) for message in messages if message.get("role") == "system"),
                "",
            )
            captured_user_prompt = next(
                (str(message.get("content", "")) for message in messages if message.get("role") == "user"),
                "",
            )
            return (
                "<think>\n先写内部推理\n</think>\n\n"
                "[detected_title]\nAI UI 为什么总差最后一口气\n\n"
                "[body]\n## 按原文整理\nAI 生成 UI 的核心问题是缺少统一设计规范。\n\n"
                "问题不只是模型能力，而是缺设计系统。后处理打磨很关键。"
            )

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "chat_completion",
                side_effect=fake_chat_completion,
            ):
                response = asyncio.run(ai_router.organize_item_analysis("item-ai", db=db))

        self.assertEqual(response.id, "item-ai")
        self.assertEqual(response.parse_status, "completed")
        self.assertIn("[detected_title]", response.extracted_text or "")
        self.assertIn("AI UI 为什么总差最后一口气", response.extracted_text or "")
        self.assertIn("## 按原文整理", response.extracted_text or "")
        self.assertNotIn("## 摘要", response.extracted_text or "")
        self.assertNotIn("<think>", response.extracted_text or "")
        self.assertIn("最大限度保留原有内容", captured_system_prompt)
        self.assertIn("不要默认输出", captured_system_prompt)
        self.assertIn("当前文章已有的内容分析文本", captured_user_prompt)
        self.assertIn("不要总结、不要压缩成提要", captured_user_prompt)
        self.assertNotIn("当前文章抓取到的正文文本", captured_user_prompt)
        self.assertNotIn("当前文章额外抓取到的 OCR / 帧文字", captured_user_prompt)

    def test_organize_item_analysis_requires_existing_analysis_text(self) -> None:
        with self.Session() as db:
            item = db.query(Item).filter(Item.id == "item-ai").one()
            item.extracted_text = ""
            db.commit()

            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"):
                with self.assertRaises(ai_router.HTTPException) as ctx:
                    asyncio.run(ai_router.organize_item_analysis("item-ai", db=db))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "No current item analysis available for organization")

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
                                    "name": "search_library_items",
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
                        "content": "我找到了两条最相关的笔记，分别关于 AI UI 打磨和组件表达。[1][2]",
                    }
                }
            ]
        }

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                _SNAPSHOT_FUNC,
                return_value=self._make_snapshot(),
            ), patch.object(
                ai_router,
                "create_chat_completion",
                side_effect=[tool_payload, final_payload],
            ):
                response = asyncio.run(ai_router.assistant(request, db=db))

        self.assertEqual(response.mode, "agent")
        self.assertEqual(len(response.tool_events), 1)
        self.assertEqual(response.tool_events[0].name, "search_library_items")
        self.assertGreaterEqual(len(response.citations), 1)
        self.assertIn("两条", response.message)

    def test_assistant_chat_omits_citations_when_answer_has_no_reference_markers(self) -> None:
        request = AiAssistantRequest(
            mode="chat",
            messages=[AiConversationMessage(role="user", content="总结我保存过的 AI UI 设计内容")],
            top_k=4,
        )

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                "_retrieve_rag_context",
                return_value=self._make_rag_context(),
            ), patch.object(
                ai_router,
                "chat_completion",
                return_value="你保存过的 AI UI 设计内容主要集中在界面打磨和组件表达两个方向。",
            ):
                response = asyncio.run(ai_router.assistant(request, db=db))

        self.assertEqual(response.mode, "chat")
        self.assertEqual(response.citations, [])

    def test_retrieve_rag_context_builds_grounded_context_from_ranked_chunks(self) -> None:
        snapshot = self._make_snapshot()

        async def fake_embed_texts(ai_config, texts):
            vectors: list[list[float]] = []
            for text in texts:
                normalized = text.lower()
                if "impeccable" in normalized or "ai 写的 ui 太丑" in normalized:
                    vectors.append([1.0, 0.0])
                elif "component gallery" in normalized:
                    vectors.append([0.7, 0.3])
                else:
                    vectors.append([0.1, 0.9])
            return vectors

        async def fake_embed_query(ai_config, text):
            self.assertIn("AI UI", text)
            return [1.0, 0.0]

        async def fake_rerank(ai_config, *, question, candidates, limit):
            self.assertIn("AI UI", question)
            return candidates[:limit]

        with self.Session() as db:
            with patch.object(ai_router, _SNAPSHOT_FUNC, return_value=snapshot), patch.object(
                ai_router,
                "_embed_texts",
                side_effect=fake_embed_texts,
            ), patch.object(
                ai_router,
                "_embed_query",
                side_effect=fake_embed_query,
            ), patch.object(
                ai_router,
                "_ai_rerank_chunks",
                side_effect=fake_rerank,
            ):
                rag_context = asyncio.run(
                    ai_router._retrieve_rag_context(
                        db=db,
                        user_id="local-default-user",
                        ai_config={
                            "api_key": "test-ai-key",
                            "base_url": "https://api.example.com/v1",
                            "model": "test-model",
                            "embedding_model": "test-embedding-model",
                        },
                        question="我之前保存过哪些关于 AI UI 设计的内容？",
                        top_k=4,
                    )
                )

        self.assertFalse(rag_context.insufficient_context)
        self.assertEqual(rag_context.retrieval_mode, "semantic")
        self.assertEqual(rag_context.ranked_notes[0][0].title, "AI 写的 UI 太丑？这个 Skill 救了我")
        self.assertIn("[1] 标题: AI 写的 UI 太丑？这个 Skill 救了我", rag_context.context_text)
        self.assertIn("相关片段1", rag_context.context_text)

    def test_assistant_agent_returns_updated_items_for_mutations(self) -> None:
        request = AiAssistantRequest(
            mode="agent",
            messages=[AiConversationMessage(role="user", content="把这条内容放到 AI 设计 文件夹")],
        )
        tool_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "tool-assign",
                                "type": "function",
                                "function": {
                                    "name": "assign_item_folders",
                                    "arguments": '{"item_id":"item-ai","folder_names":["AI 设计"]}',
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
                        "content": "已经调整好了文件夹。",
                    }
                }
            ]
        }

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                _SNAPSHOT_FUNC,
                return_value=self._make_snapshot(),
            ), patch.object(
                ai_router,
                "create_chat_completion",
                side_effect=[tool_payload, final_payload],
            ):
                response = asyncio.run(ai_router.assistant(request, db=db))

        self.assertEqual(response.mode, "agent")
        self.assertEqual(len(response.updated_items), 1)
        self.assertEqual(response.updated_items[0].id, "item-ai")
        self.assertEqual(response.updated_items[0].folder_names, ["AI 设计"])

    def test_related_notes_uses_local_knowledge_base_even_without_ai_call(self) -> None:
        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"), patch.object(
                ai_router,
                _SNAPSHOT_FUNC,
                return_value=self._make_snapshot(),
            ):
                response = ai_router.related_notes("item-ai", limit=3, db=db)

        self.assertEqual(response.item_id, "item-ai")
        self.assertEqual(len(response.related), 1)
        self.assertEqual(response.related[0].title, "Vibe Coding 的时候不知道怎么描述 UI？")

    def test_save_and_query_ai_conversation_history(self) -> None:
        request = AiConversationSaveRequest(
            mode="chat",
            current_item_id="item-ai",
            messages=[
                AiConversationStoredMessage(role="user", content="帮我总结 AI UI 设计规范"),
                AiConversationStoredMessage(
                    role="assistant",
                    content="这批内容主要在讨论 AI UI 生成之后，为什么还需要统一设计规范与后处理。",
                    note_count=2,
                    knowledge_base_path="/tmp/Sources.base",
                ),
            ],
        )

        with self.Session() as db:
            with patch.object(ai_router, "get_current_user_id", return_value="local-default-user"):
                saved = ai_router.save_ai_conversation(request, db=db)
                listed = ai_router.list_ai_conversations(q="设计规范", current_item_id="item-ai", db=db)
                loaded = ai_router.get_ai_conversation(saved.id, db=db)

        self.assertEqual(saved.current_item_id, "item-ai")
        self.assertEqual(saved.title, "帮我总结 AI UI 设计规范")
        self.assertEqual(len(saved.messages), 2)
        self.assertEqual(len(listed.conversations), 1)
        self.assertEqual(listed.conversations[0].id, saved.id)
        self.assertEqual(loaded.messages[1].note_count, 2)
        self.assertIn("统一设计规范", loaded.messages[1].content)


if __name__ == "__main__":
    unittest.main()
