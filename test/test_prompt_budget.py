"""Tests for SageMaker prompt budgeting."""

from __future__ import annotations

from rag_eng.config import (
    SageMakerContextConfig,
    SageMakerGenerationConfig,
    SageMakerInferenceConfig,
)
from rag_eng.prompt_budget import (
    assemble_sagemaker_messages,
    effective_max_tokens,
    estimate_tokens,
    trim_formatted_context,
)
from rag_eng.prompts import get_system_prompt


def _sm_config(max_model_len: int = 10240) -> SageMakerInferenceConfig:
    return SageMakerInferenceConfig(
        poll_interval_seconds=2.0,
        streaming_chunk_size=20,
        generation=SageMakerGenerationConfig(
            max_tokens=2048,
            temperature=0.7,
            top_p=0.9,
        ),
        context=SageMakerContextConfig(
            max_model_len=max_model_len,
            reserved_output_tokens=2048,
            safety_tokens=128,
            chars_per_token=4.0,
        ),
    )


def test_trim_formatted_context_drops_guidelines_before_syllabus() -> None:
    context = (
        "[Retrieved_Syllabus_Chunk]\nweek 1 syllabus\n\n"
        "[Pedagogical_Context]\npedagogy\n\n"
        "[CppCoreGuidelines]\nguidelines"
    )
    trimmed = trim_formatted_context(context, 60)
    assert "[Retrieved_Syllabus_Chunk]" in trimmed
    assert "[CppCoreGuidelines]" not in trimmed


def test_assemble_sagemaker_messages_fits_10k_window() -> None:
    cfg = _sm_config()
    system = get_system_prompt("Homework Assist")
    rag = "[Retrieved_Syllabus_Chunk]\nforbidden pointers\n\n[Strict_Rules]\nrule"
    users = [{"role": "user", "content": "Why does my pointer segfault?"}]
    messages = assemble_sagemaker_messages(system, rag, users, "Homework Assist", cfg)
    prompt_tokens = sum(estimate_tokens(m["content"], 4.0) for m in messages)
    assert prompt_tokens + cfg.generation.max_tokens <= cfg.context.max_model_len


def test_assemble_uses_compact_prompt_when_full_prompt_exceeds_4k_window() -> None:
    cfg = _sm_config(max_model_len=4096)
    system = get_system_prompt("Homework Assist")
    rag = "[Retrieved_Syllabus_Chunk]\nsyllabus"
    users = [{"role": "user", "content": "help"}]
    messages = assemble_sagemaker_messages(system, rag, users, "Homework Assist", cfg)
    assert len(messages[0]["content"]) < len(system)


def test_effective_max_tokens_caps_to_remaining_room() -> None:
    cfg = _sm_config()
    messages = [{"role": "system", "content": "x" * 40000}, {"role": "user", "content": "hi"}]
    assert effective_max_tokens(messages, cfg) < cfg.generation.max_tokens
