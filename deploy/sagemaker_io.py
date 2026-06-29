"""SageMaker async inference payload helpers (HuggingFace pipeline vs vLLM DLC)."""

from __future__ import annotations

import json
from typing import Any


def build_async_payload(
    backend: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    top_p: float,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    formatted_prompt: str | None = None,
) -> dict[str, Any]:
    """Build JSON body for invoke_endpoint_async."""
    if backend == "vllm":
        return {
            "messages": [
                {"role": msg["role"], "content": msg["content"]} for msg in messages
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
            "presence_penalty": presence_penalty,
            "frequency_penalty": frequency_penalty,
            "stop": ["<|im_end|>", "<|endoftext|>"],
        }

    if not formatted_prompt:
        raise ValueError("formatted_prompt is required for huggingface backend")
    return {
        "inputs": formatted_prompt,
        "parameters": {
            "max_new_tokens": max_tokens,
            "temperature": temperature,
            "top_p": top_p,
        },
    }


def parse_async_response(backend: str, result: Any) -> str:
    """Extract assistant text from async inference S3 output."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return result

    if backend == "vllm":
        choices = result.get("choices") if isinstance(result, dict) else None
        if choices:
            first = choices[0]
            message = first.get("message") or {}
            if message.get("content"):
                return str(message["content"])
            if first.get("text"):
                return str(first["text"])
        if isinstance(result, dict) and "generated_text" in result:
            return str(result["generated_text"])

    if isinstance(result, list) and result and isinstance(result[0], dict):
        if "generated_text" in result[0]:
            return str(result[0]["generated_text"])

    if isinstance(result, dict) and "generated_text" in result:
        return str(result["generated_text"])

    raise ValueError(f"Unexpected SageMaker response shape ({backend}): {result!r}")
