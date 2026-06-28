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


def test_evaluate_input_guardrail_passes_on_low_model_score(monkeypatch) -> None:
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
