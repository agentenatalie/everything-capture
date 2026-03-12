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


def extract_assistant_message(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices") or []
    if not choices:
        raise AiClientError("AI response did not include choices")

    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise AiClientError("AI response did not include a valid assistant message")
    return message


def extract_message_text(message: dict[str, Any], *, allow_empty: bool = False) -> str:
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        if text or allow_empty:
            return text
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text") or "").strip()
                if text:
                    parts.append(text)
        if parts or allow_empty:
            return "\n".join(parts).strip()
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

    try:
        response_payload = response.json()
    except json.JSONDecodeError as exc:
        raise AiClientError("AI returned a non-JSON response") from exc

    if not response.is_success:
        detail = response_payload.get("error")
        if isinstance(detail, dict):
            detail = detail.get("message")
        detail_text = str(detail or response.text or response.reason_phrase).strip()
        raise AiClientError(detail_text or "AI request failed")

    return response_payload


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
