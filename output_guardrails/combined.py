"""V1 + V2 chained guardrail dispatcher.

Runtime usage from the eventual FastAPI /chat handler:

    from output_guardrails.combined import apply_all_guardrails
    result = apply_all_guardrails(
        answer=draft,
        user_query=last_user_msg,
        student_code=request.student_code,
        conversation_history=request.history,
    )
    return {"answer": result["final_answer"], "guardrail": result}

Order:
    1. V1 rule-based output_guardrails. If V1 replaces, ship V1 fallback.
    2. Otherwise, run V2 semantic_guardrail. If V2 replaces, ship V2
       fallback. If V2 is uncertain (log_only), ship the original draft
       but flag the result.
    3. If both pass, ship the original draft.

V1 is preserved unchanged. This file only chains the two layers.
"""

from __future__ import annotations

from .output_guardrails import apply_output_guardrails
from .semantic_guardrail import predict_safety


def apply_all_guardrails(
    answer: str,
    user_query: str,
    student_code: str,
    conversation_history: list,
) -> dict:
    """Chained V1 + V2 guardrail. Returns the same dict shape both
    layers produce; downstream code should look at `final_answer`.
    """
    v1 = apply_output_guardrails(answer, user_query, student_code, conversation_history)
    if v1["action"] == "replace":
        return {**v1, "stage": "v1"}

    # V1 passed or log_only — give V2 a look.
    v2 = predict_safety(answer, user_query, student_code, conversation_history)

    if v2["action"] == "replace":
        return {**v2, "stage": "v2"}
    if v2["action"] == "log_only":
        # Prefer V2's log signal over V1's pass when V2 is uncertain;
        # but if V1 itself was log_only, keep that label too in evidence.
        merged = dict(v2)
        if v1["action"] == "log_only":
            merged["evidence"] = f"{v1['evidence']} | {v2['evidence']}"
        return {**merged, "stage": "v2"}

    # Both layers passed.
    return {**v1, "stage": "v1+v2"}
