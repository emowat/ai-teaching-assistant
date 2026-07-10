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
    ERR_LANGUAGE_SWITCH,
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
    LANG_SWITCH_REGEXES,
    OFF_TOPIC_PHRASES,
    OFF_TOPIC_REGEXES,
    has_cpp_anchor,
    is_lang_switch_rescued,
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
    ERR_LANGUAGE_SWITCH: 0.85,
}
_PASS_CONF = 0.10

# Editor/file-context keys that may carry code the student pasted or selected
# without typing a question. The service passes it as `code_raw`; the other
# names are accepted so the guardrail is robust to the caller's payload shape.
_CODE_CONTEXT_KEYS = (
    "code_raw",
    "student_code",
    "selected_code",
    "code_context",
    "editor_content",
    "raw_code_snippet",
)


def _extract_code_context(ide_context: dict | None) -> str:
    """Return non-empty pasted/selected code from ide_context, else ''.

    Checks the recognized keys in order and returns the first that holds
    non-whitespace text. Never raises on odd input.
    """
    if not isinstance(ide_context, dict):
        return ""
    for key in _CODE_CONTEXT_KEYS:
        value = ide_context.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _hit(text_lower: str, phrases, regexes) -> bool:
    return (matches_any(text_lower, phrases) is not None
            or matches_any_regex(text_lower, regexes) is not None)


def check_input_guardrail(raw_input: str, ide_context: dict | None = None) -> InputGuardrailResult:
    """Classify a single student message as PASS or BLOCK.

    Args:
        raw_input: the student's raw question, verbatim.
        ide_context: optional editor/file context. Recognized keys carry any
            pasted / selected code the student attached without typing a
            question (see _CODE_CONTEXT_KEYS). A code-only paste is a valid
            request — it triggers an out-of-band question about the code — so
            it must NOT be blocked as ERR_EMPTY_INPUT.

    Returns:
        InputGuardrailResult. On BLOCK, processed_input is None; on PASS it
        equals raw_input, except a code-only paste (empty message + code)
        passes with processed_input set to the pasted code.
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

    # 0. Empty / whitespace-only message. Invalid input, not a real violation —
    #    UNLESS the student pasted/selected code with no accompanying question.
    #    That code-only paste is a legitimate request (it drives an out-of-band
    #    question about the code), so let it PASS to the model stage instead of
    #    blocking as ERR_EMPTY_INPUT.
    if raw_input is None or not raw_input.strip():
        pasted_code = _extract_code_context(ide_context)
        if pasted_code:
            return _result("PASS", None, pasted_code, _PASS_CONF)
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

    # 5. Language-switch / off-topic implementation pivot.
    #    Rescued if the message is a comparative/analogy question with a C++ anchor
    #    (e.g. "how is C++ different from Python?", "explain using a Python analogy").
    if matches_any_regex(text, LANG_SWITCH_REGEXES) and not is_lang_switch_rescued(text):
        return _result("BLOCK", ERR_LANGUAGE_SWITCH, None, _CONF[ERR_LANGUAGE_SWITCH])

    # PASS — legitimate C++ learning/debugging question.
    return _result("PASS", None, raw_input, _PASS_CONF)
