"""Fit chat messages to the SageMaker vLLM context window without dropping critical sections."""

from __future__ import annotations

import logging
import re

from rag_eng.config import SageMakerInferenceConfig
from rag_eng.prompts import get_compact_system_prompt

logger = logging.getLogger(__name__)

# Lowest index = trimmed first when over budget (syllabus trimmed last).
_RAG_CHUNK_ORDER = (
    "[CppCoreGuidelines]",
    "[Supplementary]",
    "[Pedagogical_Context]",
    "[Strict_Rules]",
    "[Retrieved_Syllabus_Chunk]",
)


def estimate_tokens(text: str, chars_per_token: float) -> int:
    """Conservative token estimate (ceil) for budgeting."""
    if not text:
        return 0
    return max(1, int(len(text) / chars_per_token) + 1)


def estimate_messages_tokens(messages: list[dict], chars_per_token: float) -> int:
    return sum(estimate_tokens(m.get("content", ""), chars_per_token) for m in messages)


def _char_budget(
    max_model_len: int,
    reserved_output_tokens: int,
    safety_tokens: int,
    chars_per_token: float,
) -> int:
    input_tokens = max_model_len - reserved_output_tokens - safety_tokens
    return max(0, int(input_tokens * chars_per_token))


def _split_rag_chunks(formatted_context: str) -> list[str]:
    if not formatted_context.strip():
        return []
    return [p for p in re.split(r"\n\n(?=\[)", formatted_context.strip()) if p.strip()]


def _chunk_priority(header: str) -> int:
    for idx, tag in enumerate(_RAG_CHUNK_ORDER):
        if header.startswith(tag):
            return idx
    return -1


def trim_formatted_context(formatted_context: str, max_chars: int) -> str:
    """Drop lowest-priority RAG chunks first; syllabus is kept until last resort."""
    if len(formatted_context) <= max_chars:
        return formatted_context

    chunks = _split_rag_chunks(formatted_context)
    if not chunks:
        return formatted_context[:max_chars]

    keep = list(chunks)
    while len(keep) > 1:
        text = "\n\n".join(keep)
        if len(text) <= max_chars:
            return text
        drop_idx = min(range(len(keep)), key=lambda i: _chunk_priority(keep[i]))
        keep.pop(drop_idx)

    return keep[0][:max_chars]


def effective_max_tokens(
    messages: list[dict],
    cfg: SageMakerInferenceConfig,
) -> int:
    """Cap generation tokens so prompt + output fits max_model_len."""
    ctx = cfg.context
    prompt_tokens = estimate_messages_tokens(messages, ctx.chars_per_token)
    room = ctx.max_model_len - prompt_tokens - ctx.safety_tokens
    return max(1, min(cfg.generation.max_tokens, room))


def assemble_sagemaker_messages(
    system_prompt: str,
    rag_context: str,
    user_messages: list[dict],
    mode: str,
    cfg: SageMakerInferenceConfig,
) -> list[dict]:
    """Build system+user messages that fit the SageMaker context budget.

    Trim order (never modify user/extension content):
      1. Drop lowest-priority RAG chunks (guidelines first, syllabus last).
      2. Swap to compact system prompt (core pedagogy, short analysis note).
      3. Hard-truncate system text only as a last resort.
    """
    ctx = cfg.context
    char_budget = _char_budget(
        ctx.max_model_len,
        ctx.reserved_output_tokens,
        ctx.safety_tokens,
        ctx.chars_per_token,
    )
    user_chars = sum(len(m.get("content", "")) for m in user_messages)
    system_char_budget = max(0, char_budget - user_chars)

    rag_trimmed = trim_formatted_context(rag_context, system_char_budget)
    system_content = f"{system_prompt}\n{rag_trimmed}".strip()
    used_compact = False

    if len(system_content) > system_char_budget:
        compact = get_compact_system_prompt(mode)
        rag_trimmed = trim_formatted_context(
            rag_context,
            max(0, system_char_budget - len(compact) - 1),
        )
        system_content = f"{compact}\n{rag_trimmed}".strip()
        used_compact = True

    if len(system_content) > system_char_budget:
        system_content = system_content[:system_char_budget]
        logger.warning(
            "SageMaker system prompt truncated to %s chars (budget %s)",
            len(system_content),
            system_char_budget,
        )

    if used_compact:
        logger.info("Using compact system prompt for SageMaker context budget")
    if rag_trimmed != rag_context:
        logger.info(
            "Trimmed RAG context from %s to %s chars for SageMaker",
            len(rag_context),
            len(rag_trimmed),
        )

    return [{"role": "system", "content": system_content}, *user_messages]
