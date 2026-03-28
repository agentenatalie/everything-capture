import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services import ai_client


class _FakeResponse:
    def __init__(self, *, status_code: int, text: str, reason_phrase: str = "OK") -> None:
        self.status_code = status_code
        self.text = text
        self.reason_phrase = reason_phrase

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        raise json.JSONDecodeError("Expecting value", self.text, 0)


class _JsonResponse(_FakeResponse):
    def __init__(self, *, status_code: int, payload: dict, reason_phrase: str = "OK") -> None:
        super().__init__(status_code=status_code, text=json.dumps(payload), reason_phrase=reason_phrase)
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse, **kwargs) -> None:
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, headers=None, json=None):
        return self._response


class AiClientTests(unittest.TestCase):
    def test_chat_completion_accepts_plain_text_success_response(self) -> None:
        response = _FakeResponse(status_code=200, text="这条笔记的核心观点是：先统一设计规范，再让 AI 生成内容。")

        with patch.object(ai_client.httpx, "AsyncClient", side_effect=lambda **kwargs: _FakeAsyncClient(response, **kwargs)):
            message = asyncio.run(
                ai_client.chat_completion(
                    api_key="test-key",
                    base_url="https://api.example.com/v1",
                    model="test-model",
                    messages=[{"role": "user", "content": "总结这条笔记的核心观点"}],
                )
            )

        self.assertIn("核心观点", message)
        self.assertIn("设计规范", message)

    def test_create_chat_completion_surfaces_plain_text_error_response(self) -> None:
        response = _FakeResponse(status_code=502, text="upstream overloaded", reason_phrase="Bad Gateway")

        with patch.object(ai_client.httpx, "AsyncClient", side_effect=lambda **kwargs: _FakeAsyncClient(response, **kwargs)):
            with self.assertRaises(ai_client.AiClientError) as ctx:
                asyncio.run(
                    ai_client.create_chat_completion(
                        api_key="test-key",
                        base_url="https://api.example.com/v1",
                        model="test-model",
                        messages=[{"role": "user", "content": "总结这条笔记的核心观点"}],
                    )
                )

        self.assertEqual(str(ctx.exception), "upstream overloaded")

    def test_create_embeddings_returns_vectors_sorted_by_index(self) -> None:
        response = _JsonResponse(
            status_code=200,
            payload={
                "data": [
                    {"index": 1, "embedding": [0.1, 0.2, 0.3]},
                    {"index": 0, "embedding": [0.9, 0.8, 0.7]},
                ]
            },
        )

        with patch.object(ai_client.httpx, "AsyncClient", side_effect=lambda **kwargs: _FakeAsyncClient(response, **kwargs)):
            vectors = asyncio.run(
                ai_client.create_embeddings(
                    api_key="test-key",
                    base_url="https://api.example.com/v1",
                    model="test-embedding-model",
                    inputs=["first", "second"],
                )
            )

        self.assertEqual(vectors, [[0.9, 0.8, 0.7], [0.1, 0.2, 0.3]])
