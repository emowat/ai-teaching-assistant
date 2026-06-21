"""Main entry point for the v1 rule-based input guardrail.

check_input_guardrail(raw_input, ide_context=None) -> InputGuardrailResult

Deterministic, fast, no LLM/GPU/external calls. Classifies ONLY the current
message. Severity precedence for multi-category matches:
    injection > inappropriate > full_solution > off_topic
The conservative allow-list rescue applies to full_solution / off_topic only;
injection and inappropriate always win.
"""

from __future__ import annotations

import re
import time

from .models import (
    ERR_EMPTY_INPUT,
    ERR_FULL_SOLUTION_REQUEST,
    ERR_INAPPROPRIATE_CONTENT,
    ERR_OFF_TOPIC,
    ERR_PROMPT_INJECTION,
    InputGuardrailResult,
)
from .rules import (
    FULL_SOLUTION_PHRASES,
    FULL_SOLUTION_REGEXES,
    INAPPROPRIATE_PHRASES,
    INAPPROPRIATE_REGEXES,
    INJECTION_PHRASES,
    INJECTION_REGEXES,
    OFF_TOPIC_PHRASES,
    OFF_TOPIC_REGEXES,
    has_cpp_anchor,
    is_rescued,
    matches_any,
    matches_any_regex,
)

# Per-category confidence for a BLOCK (deterministic, not learned).
_CONF = {
    ERR_EMPTY_INPUT: 1.0,
    ERR_PROMPT_INJECTION: 0.95,
    ERR_INAPPROPRIATE_CONTENT: 0.95,
    ERR_FULL_SOLUTION_REQUEST: 0.90,
    ERR_OFF_TOPIC: 0.85,
}
_PASS_CONF = 0.10


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _hit(text_lower: str, phrases, regexes) -> bool:
    return (matches_any(text_lower, phrases) is not None
            or matches_any_regex(text_lower, regexes) is not None)


def check_input_guardrail(raw_input: str, ide_context: dict | None = None) -> InputGuardrailResult:
    """Classify a single student message as PASS or BLOCK.

    Args:
        raw_input: the student's raw question, verbatim.
        ide_context: reserved for future use (editor/file context). UNUSED in v1.

    Returns:
        InputGuardrailResult. On BLOCK, processed_input is None; on PASS it
        equals raw_input.
    """
    start = time.perf_counter()

    def _result(action, flag_reason, processed_input, confidence):
        latency_ms = max(0, round((time.perf_counter() - start) * 1000))
        return InputGuardrailResult(
            action=action,
            flag_reason=flag_reason,
            processed_input=processed_input,
            confidence=confidence,
            latency_ms=latency_ms,
        )

    # 0. Empty / whitespace-only — invalid input, not a real violation.
    if raw_input is None or not raw_input.strip():
        return _result("BLOCK", ERR_EMPTY_INPUT, None, _CONF[ERR_EMPTY_INPUT])

    text = _normalize(raw_input)
    rescued = is_rescued(text)

    # 1. Prompt injection (never rescued).
    if _hit(text, INJECTION_PHRASES, INJECTION_REGEXES):
        return _result("BLOCK", ERR_PROMPT_INJECTION, None, _CONF[ERR_PROMPT_INJECTION])

    # 2. Inappropriate / unsafe (never rescued).
    if _hit(text, INAPPROPRIATE_PHRASES, INAPPROPRIATE_REGEXES):
        return _result("BLOCK", ERR_INAPPROPRIATE_CONTENT, None, _CONF[ERR_INAPPROPRIATE_CONTENT])

    # 3. Full-solution request (rescued by clear pedagogical-intent/negation).
    if _hit(text, FULL_SOLUTION_PHRASES, FULL_SOLUTION_REGEXES) and not rescued:
        return _result("BLOCK", ERR_FULL_SOLUTION_REQUEST, None, _CONF[ERR_FULL_SOLUTION_REQUEST])

    # 4. Off-topic (rescued by clear pedagogical-intent OR a C++ anchor).
    if _hit(text, OFF_TOPIC_PHRASES, OFF_TOPIC_REGEXES) and not (rescued or has_cpp_anchor(text)):
        return _result("BLOCK", ERR_OFF_TOPIC, None, _CONF[ERR_OFF_TOPIC])

    # PASS — legitimate C++ learning/debugging question.
    return _result("PASS", None, raw_input, _PASS_CONF)
