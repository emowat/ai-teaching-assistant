"""Runtime output guardrails for the CodingRabbit.dev Socratic C++ TA."""

from .output_guardrails import (
    STRICT_PEDAGOGY,
    apply_output_guardrails,
    check_code_leakage,
    check_direct_solution_leakage,
    check_off_topic_leakage,
    check_system_prompt_leakage,
    check_unsafe_end_chat,
)
from .semantic_guardrail import predict_safety, set_predict_fn, set_thresholds
from .combined import apply_all_guardrails

__all__ = [
    "STRICT_PEDAGOGY",
    "apply_output_guardrails",
    "check_code_leakage",
    "check_direct_solution_leakage",
    "check_off_topic_leakage",
    "check_system_prompt_leakage",
    "check_unsafe_end_chat",
    "predict_safety",
    "set_predict_fn",
    "set_thresholds",
    "apply_all_guardrails",
]
