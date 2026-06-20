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


@dataclass(frozen=True)
class BedrockChatConfig:
    region: str
    model_id: str
    timeout_seconds: float = 120.0
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 2048
    profile_name: str | None = None


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


def _normalize_bedrock_messages(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split system prompts and normalize chat messages for Bedrock Converse."""
    system_blocks: list[dict] = []
    normalized_messages: list[dict] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        if role == "system":
            system_blocks.append({"text": content})
            continue
        normalized_messages.append(
            {
                "role": role,
                "content": [{"text": content}],
            }
        )
    return system_blocks, normalized_messages


def _extract_bedrock_content(payload: dict) -> str:
    """Extract assistant text from a Bedrock Converse response."""
    output = payload.get("output") or {}
    message = output.get("message") or {}
    content = message.get("content") or []
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    if parts:
        return "".join(parts)
    return ""


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


def invoke_bedrock_chat_completion(
    messages: list[dict],
    config: BedrockChatConfig,
) -> str:
    """Synchronously invoke Bedrock Converse for prompt- or message-based flows."""
    import boto3
    from botocore.config import Config as BotocoreConfig

    system_blocks, normalized_messages = _normalize_bedrock_messages(messages)
    payload: dict[str, object] = {
        "modelId": config.model_id,
        "messages": normalized_messages,
        "inferenceConfig": {
            "maxTokens": config.max_tokens,
            "temperature": config.temperature,
            "topP": config.top_p,
        },
    }
    if system_blocks:
        payload["system"] = system_blocks

    session = boto3.Session(
        profile_name=config.profile_name,
        region_name=config.region,
    )
    client = session.client(
        "bedrock-runtime",
        region_name=config.region,
        config=BotocoreConfig(
            connect_timeout=config.timeout_seconds,
            read_timeout=config.timeout_seconds,
        ),
    )
    response = client.converse(**payload)
    return _extract_bedrock_content(response)


async def ainvoke_bedrock_chat_completion(
    messages: list[dict],
    config: BedrockChatConfig,
) -> str:
    """Asynchronously invoke Bedrock Converse using a worker thread."""
    return await asyncio.to_thread(invoke_bedrock_chat_completion, messages, config)


async def chunk_text(text: str, chunk_size: int = 20) -> AsyncIterator[bytes]:
    """Chunk a full response into NDJSON events for streaming endpoints."""
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        yield (json.dumps({"message": {"content": chunk}}) + "\n").encode()
        await asyncio.sleep(0.01)
