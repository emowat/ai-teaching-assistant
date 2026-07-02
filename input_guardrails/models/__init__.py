"""Input guardrail models package.

Holds BOTH:
  - the rule-based v1 result schema (InputGuardrailResult, ERR_* codes),
    re-exported here so `from input_guardrails.models import InputGuardrailResult`
    continues to work for detector.py / responses.py / the package __init__;
  - the CodeBERT train/eval data utilities.

Separate from output_guardrails/ — this is the INPUT guardrail only.
"""

from input_guardrails.models.result import (
    ERR_EMPTY_INPUT,
    ERR_FULL_SOLUTION_REQUEST,
    ERR_INAPPROPRIATE_CONTENT,
    ERR_LANGUAGE_SWITCH,
    ERR_OFF_TOPIC,
    ERR_PROMPT_INJECTION,
    VERSION,
    InputGuardrailResult,
)
from input_guardrails.models.data_utils import (
    apply_splits,
    assert_no_context_leakage,
    format_example,
    label_distribution,
    load_jsonl,
    load_splits,
)

__all__ = [
    # result schema
    "InputGuardrailResult", "VERSION",
    "ERR_PROMPT_INJECTION", "ERR_FULL_SOLUTION_REQUEST", "ERR_OFF_TOPIC",
    "ERR_LANGUAGE_SWITCH", "ERR_INAPPROPRIATE_CONTENT", "ERR_EMPTY_INPUT",
    # data utils
    "apply_splits", "assert_no_context_leakage", "format_example",
    "label_distribution", "load_jsonl", "load_splits",
]
