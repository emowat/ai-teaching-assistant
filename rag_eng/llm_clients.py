"""Provider adapters used by the `rag_eng` service."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator

import httpx


@dataclass(frozen=True)
class OpenAIChatConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 120.0
    temperature: float = 0.7
    top_p: float = 0.9


def _chat_completion_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/chat/completions"


def _extract_chat_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    return ""


def _normalize_messages(messages: list[dict]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        normalized.append({"role": role, "content": str(content)})
    return normalized


def invoke_openai_chat_completion(prompt: str, config: OpenAIChatConfig) -> str:
    """Synchronously invoke OpenAI chat completions for prompt-based flows."""
    payload = {
        "model": config.model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": config.temperature,
        "top_p": config.top_p,
    }
    headers = {"Authorization": f"Bearer {config.api_key}"}
    with httpx.Client(timeout=config.timeout_seconds, headers=headers) as client:
        response = client.post(_chat_completion_url(config.base_url), json=payload)
        response.raise_for_status()
        return _extract_chat_content(response.json())


async def ainvoke_openai_chat_completion(
    messages: list[dict],
    config: OpenAIChatConfig,
) -> str:
    """Asynchronously invoke OpenAI chat completions for message-based flows."""
    payload = {
        "model": config.model,
        "messages": _normalize_messages(messages),
        "temperature": config.temperature,
        "top_p": config.top_p,
    }
    headers = {"Authorization": f"Bearer {config.api_key}"}
    async with httpx.AsyncClient(timeout=config.timeout_seconds, headers=headers) as client:
        response = await client.post(_chat_completion_url(config.base_url), json=payload)
        response.raise_for_status()
        return _extract_chat_content(response.json())


async def chunk_text(text: str, chunk_size: int = 20) -> AsyncIterator[bytes]:
    """Chunk a full response into NDJSON events for streaming endpoints."""
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield (json.dumps({"message": {"content": chunk}}) + "\n").encode()
        await asyncio.sleep(0.01)
