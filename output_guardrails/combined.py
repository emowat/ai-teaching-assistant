"""V1 + V2 chained output-guardrail dispatcher.

This module is the single place that decides how the two output guardrail
layers interact:

1. Run V1 first.
2. If V1 replaces the draft, stop immediately and return the V1 fallback.
3. If V1 passes, run V2.
4. If V2 replaces the draft, stop immediately and return the V2 fallback.
5. If either layer only wants to log, keep the original draft but preserve
   the log-only signal in the returned metadata.
6. If both layers pass, return the original draft with a clean pass result.

Runtime usage from the FastAPI /chat handler:

    from output_guardrails.combined import apply_all_guardrails
    result = apply_all_guardrails(
        answer=draft,
        user_query=last_user_msg,
        student_code=request.student_code,
        conversation_history=request.history,
    )
    return {"answer": result["final_answer"], "guardrail": result}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .output_guardrails import apply_output_guardrails
from .semantic_guardrail import predict_safety


@dataclass(frozen=True)
class GuardrailDispatchConfig:
    """Readable switches for the combined output-guardrail flow."""

    enable_v2_semantic_guardrail: bool = True
    v1_stage_name: str = "v1"
    v2_stage_name: str = "v2"
    merged_stage_name: str = "v1+v2"
    evidence_separator: str = " | "


DISPATCH_CONFIG = GuardrailDispatchConfig()


def _merge_evidence(v1: dict[str, Any], v2: dict[str, Any]) -> str | None:
    """Combine distinct evidence strings from both guardrail layers."""
    evidence_parts: list[str] = []
    for evidence in (v1.get("evidence"), v2.get("evidence")):
        text = str(evidence).strip() if evidence else ""
        if text and text not in evidence_parts:
            evidence_parts.append(text)
    if not evidence_parts:
        return None
    return DISPATCH_CONFIG.evidence_separator.join(evidence_parts)


def _log_only_result(
    *,
    source_stage: str,
    merged: dict[str, Any],
    source_result: dict[str, Any],
    answer: str,
) -> dict[str, Any]:
    """Return a consistent log-only result for either guardrail layer."""
    merged.update({
        "safe": False,
        "blocked": False,
        "action": "log_only",
        "violation_type": source_result.get("violation_type", "none"),
        "severity": source_result.get("severity", "low"),
        "final_answer": answer,
        "stage": source_stage,
    })
    return merged


def _pass_result(merged: dict[str, Any], answer: str) -> dict[str, Any]:
    """Return the explicit pass result when both layers allow the draft."""
    merged.update({
        "safe": True,
        "blocked": False,
        "action": "pass",
        "violation_type": "none",
        "severity": "",
        "final_answer": answer,
        "stage": DISPATCH_CONFIG.merged_stage_name,
    })
    return merged


def apply_all_guardrails(
    answer: str,
    user_query: str,
    student_code: str,
    conversation_history: list[dict],
) -> dict[str, Any]:
    """Apply V1 first, then V2, while preserving the visible answer."""
    v1 = apply_output_guardrails(answer, user_query, student_code, conversation_history)
    if v1["action"] == "replace":
        return {**v1, "stage": DISPATCH_CONFIG.v1_stage_name}

    merged = dict(v1)

    if DISPATCH_CONFIG.enable_v2_semantic_guardrail:
        v2 = predict_safety(answer, user_query, student_code, conversation_history)
        merged["v2_score"] = v2.get("v2_score")
    else:
        v2 = {
            "safe": True,
            "blocked": False,
            "violation_type": "none",
            "severity": "",
            "action": "pass",
            "evidence": "v2 disabled",
            "final_answer": answer,
            "v2_score": None,
        }

    if v2["action"] == "replace":
        return {**v2, "stage": DISPATCH_CONFIG.v2_stage_name}

    evidence = _merge_evidence(v1, v2)
    if evidence is not None:
        merged["evidence"] = evidence

    if v2["action"] == "log_only":
        return _log_only_result(
            source_stage=DISPATCH_CONFIG.v2_stage_name,
            merged=merged,
            source_result=v2,
            answer=answer,
        )

    if v1["action"] == "log_only":
        return _log_only_result(
            source_stage=DISPATCH_CONFIG.v1_stage_name,
            merged=merged,
            source_result=v1,
            answer=answer,
        )

    return _pass_result(merged, answer)
