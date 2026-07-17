from __future__ import annotations

from input_guardrails.models import InputGuardrailResult
from input_guardrails.runtime import (
    evaluate_input_guardrail,
    set_predict_fn,
    set_thresholds,
)


def _pass_rule_result() -> InputGuardrailResult:
    return InputGuardrailResult(
        action="PASS",
        flag_reason=None,
        processed_input="Explain pointers",
        confidence=0.1,
        latency_ms=1,
    )


def test_v2_model_stage_is_skipped_by_default(monkeypatch) -> None:
    # V2_INPUTGUARD_DISABLE defaults to disabled: even a stubbed high/blocking
    # score must never be consulted, and the model stage should be marked
    # "skipped" rather than evaluated. Rules alone decide the outcome.
    monkeypatch.delenv("V2_INPUTGUARD_DISABLE", raising=False)
    monkeypatch.setattr(
        "input_guardrails.runtime.check_input_guardrail",
        lambda raw_input, ide_context=None: _pass_rule_result(),
    )
    set_thresholds(0.30, 0.70)
    set_predict_fn(lambda _text: 0.99)
    try:
        result = evaluate_input_guardrail(
            student_message="works!",
            student_code="int *p;",
            course_topic="pointers",
            assignment_context="lab",
        )
    finally:
        set_predict_fn(None)
        set_thresholds(0.30, 0.70)

    assert result["blocked"] is False
    assert result["action"] == "pass"
    assert result["model"]["decision"] == "skipped"
    assert result["model"]["enabled"] is False
    assert result["model"]["score"] is None


def test_evaluate_input_guardrail_passes_on_low_model_score(monkeypatch) -> None:
    # The v2 (CodeBERT) stage is disabled by default; opt back in to exercise it.
    monkeypatch.setenv("V2_INPUTGUARD_DISABLE", "false")
    monkeypatch.setattr(
        "input_guardrails.runtime.check_input_guardrail",
        lambda raw_input, ide_context=None: _pass_rule_result(),
    )
    set_thresholds(0.30, 0.70)
    set_predict_fn(lambda _text: 0.05)
    try:
        result = evaluate_input_guardrail(
            student_message="Explain pointers",
            student_code="int *p;",
            course_topic="pointers",
            assignment_context="lab",
        )
    finally:
        set_predict_fn(None)
        set_thresholds(0.30, 0.70)

    assert result["blocked"] is False
    assert result["action"] == "pass"
    assert result["model"]["decision"] == "pass"
    assert result["model"]["score"] == 0.05


def test_evaluate_input_guardrail_blocks_on_high_model_score(monkeypatch) -> None:
    # The v2 (CodeBERT) stage is disabled by default; opt back in to exercise it.
    monkeypatch.setenv("V2_INPUTGUARD_DISABLE", "false")
    monkeypatch.setattr(
        "input_guardrails.runtime.check_input_guardrail",
        lambda raw_input, ide_context=None: _pass_rule_result(),
    )
    set_thresholds(0.30, 0.70)
    set_predict_fn(lambda _text: 0.91)
    try:
        result = evaluate_input_guardrail(
            student_message="Explain pointers",
            student_code="int *p;",
            course_topic="pointers",
            assignment_context="lab",
        )
    finally:
        set_predict_fn(None)
        set_thresholds(0.30, 0.70)

    assert result["blocked"] is True
    assert result["action"] == "block"
    assert result["model"]["decision"] == "block"
    assert result["final_answer"].startswith("Let's keep this focused")


def test_empty_message_with_pasted_code_reaches_model_not_empty_block(monkeypatch) -> None:
    # Regression: a code-only paste (empty message + student_code) must NOT be
    # blocked as ERR_EMPTY_INPUT by the rule layer; it should flow to the model
    # stage. Real rules run here (no monkeypatch) with the model stubbed low.
    # The v2 (CodeBERT) stage is disabled by default; opt back in to exercise it.
    monkeypatch.setenv("V2_INPUTGUARD_DISABLE", "false")
    set_thresholds(0.30, 0.70)
    set_predict_fn(lambda _text: 0.05)
    try:
        result = evaluate_input_guardrail(
            student_message="",
            student_code="int main() { int* p; *p = 5; }",
            course_topic="pointers",
            assignment_context="lab",
        )
    finally:
        set_predict_fn(None)
        set_thresholds(0.30, 0.70)

    assert result["rules"]["action"] == "PASS"
    assert result["rules"]["flag_reason"] is None
    assert result["violation_type"] != "ERR_EMPTY_INPUT"
    assert result["blocked"] is False
    assert result["action"] == "pass"
    assert result["model"]["decision"] == "pass"


def test_empty_message_without_code_still_blocks_empty_input() -> None:
    # Real rules; no code attached -> ERR_EMPTY_INPUT preserved.
    result = evaluate_input_guardrail(
        student_message="",
        student_code="",
        course_topic="pointers",
        assignment_context="lab",
    )
    assert result["blocked"] is True
    assert result["action"] == "block"
    assert result["rules"]["flag_reason"] == "ERR_EMPTY_INPUT"
    assert result["violation_type"] == "ERR_EMPTY_INPUT"
