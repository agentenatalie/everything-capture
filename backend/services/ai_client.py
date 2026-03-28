from __future__ import annotations

import json
from typing import Any

import httpx


class AiClientError(RuntimeError):
    pass


def _chat_completion_url(base_url: str) -> str:
    cleaned = (base_url or "").strip().rstrip("/")
    if not cleaned:
        raise AiClientError("AI base URL is empty")
    if cleaned.endswith("/chat/completions"):
        return cleaned
    return f"{cleaned}/chat/completions"


def _embeddings_url(base_url: str) -> str:
    cleaned = (base_url or "").strip().rstrip("/")
    if not cleaned:
        raise AiClientError("AI base URL is empty")
    if cleaned.endswith("/embeddings"):
        return cleaned
    if cleaned.endswith("/chat/completions"):
        return f"{cleaned[: -len('/chat/completions')]}/embeddings"
    return f"{cleaned}/embeddings"


def extract_assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    if not choices:
        raise AiClientError("AI response did not include choices")

    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise AiClientError("AI response did not include a valid assistant message")
    return message


def extract_message_text(message: dict[str, Any], *, allow_empty: bool = False) -> str:
    # Capture reasoning_content (used by some models for thinking process)
    reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
    if isinstance(reasoning, str):
        reasoning = reasoning.strip()

    content = message.get("content")
    text = ""
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = str(block.get("text") or "").strip()
                if t:
                    parts.append(t)
        text = "\n".join(parts).strip()

    # Wrap reasoning in <think> tags so frontend can render it
    if reasoning:
        result = f"<think>\n{reasoning}\n</think>\n{text}"
        return result
    if text or allow_empty:
        return text
    if allow_empty:
        return ""
    raise AiClientError("AI response did not include readable content")


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    tool_calls = message.get("tool_calls") or []
    if not isinstance(tool_calls, list):
        return []
    return [tool_call for tool_call in tool_calls if isinstance(tool_call, dict)]


async def create_chat_completion(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    timeout_seconds: float = 60.0,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = _chat_completion_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise AiClientError(f"AI request failed: {exc}") from exc

    response_text = (response.text or "").strip()
    try:
        response_payload = response.json()
    except json.JSONDecodeError as exc:
        if response.is_success and response_text:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": response_text,
                        }
                    }
                ]
            }
        detail_text = response_text or response.reason_phrase or "AI request failed"
        raise AiClientError(detail_text if not response.is_success else "AI returned a non-JSON response") from exc

    if not response.is_success:
        detail = response_payload.get("error")
        if isinstance(detail, dict):
            detail = detail.get("message")
        detail_text = str(detail or response.text or response.reason_phrase).strip()
        raise AiClientError(detail_text or "AI request failed")

    return response_payload


async def create_embeddings(
    *,
    api_key: str,
    base_url: str,
    model: str,
    inputs: list[str] | str,
    timeout_seconds: float = 60.0,
) -> list[list[float]]:
    url = _embeddings_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "input": inputs,
        "encoding_format": "float",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise AiClientError(f"AI embeddings request failed: {exc}") from exc

    response_text = (response.text or "").strip()
    try:
        response_payload = response.json()
    except json.JSONDecodeError as exc:
        detail_text = response_text or response.reason_phrase or "AI embeddings request failed"
        raise AiClientError(detail_text if not response.is_success else "AI embeddings returned a non-JSON response") from exc

    if not response.is_success:
        detail = response_payload.get("error")
        if isinstance(detail, dict):
            detail = detail.get("message")
        detail_text = str(detail or response.text or response.reason_phrase).strip()
        raise AiClientError(detail_text or "AI embeddings request failed")

    raw_data = response_payload.get("data")
    if not isinstance(raw_data, list) or not raw_data:
        raise AiClientError("AI embeddings response did not include data")

    ordered = sorted(
        (entry for entry in raw_data if isinstance(entry, dict)),
        key=lambda entry: int(entry.get("index", 0)),
    )
    embeddings: list[list[float]] = []
    for entry in ordered:
        embedding = entry.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise AiClientError("AI embeddings response included an invalid embedding")
        try:
            vector = [float(value) for value in embedding]
        except (TypeError, ValueError) as exc:
            raise AiClientError("AI embeddings response included a non-numeric embedding") from exc
        embeddings.append(vector)

    return embeddings


async def chat_completion(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    timeout_seconds: float = 60.0,
) -> str:
    payload = await create_chat_completion(
        api_key=api_key,
        base_url=base_url,
        model=model,
        messages=messages,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
    )
    return extract_message_text(extract_assistant_message(payload))


async def stream_chat_completion(
    *,
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.2,
    timeout_seconds: float = 120.0,
):
    """Yield content delta strings from a streaming chat completion (SSE)."""
    url = _chat_completion_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if not response.is_success:
                    body = await response.aread()
                    detail = body.decode(errors="replace").strip()
                    raise AiClientError(detail or "AI streaming request failed")

                buffer = ""
                in_think = False
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if line == "data: [DONE]":
                            if in_think:
                                yield "</think>"
                            return
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                            except json.JSONDecodeError:
                                continue
                            choices = data.get("choices") or []
                            if not choices:
                                continue
                            delta = choices[0].get("delta") or {}
                            reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                            content = delta.get("content")
                            if reasoning:
                                if not in_think:
                                    yield "<think>"
                                    in_think = True
                                yield reasoning
                            if content:
                                if in_think:
                                    yield "</think>"
                                    in_think = False
                                yield content
    except httpx.HTTPError as exc:
        raise AiClientError(f"AI streaming request failed: {exc}") from exc
