"""Structured result model for the (rule-based) input guardrail.

Pydantic model so the result drops straight into the orchestrator's JSON log
(model_dump() emits exactly the keys Eric's log schema expects).

Lives under input_guardrails/models/ and is re-exported from the package
__init__, so `from input_guardrails.models import InputGuardrailResult` works.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

VERSION = "input_guardrail_v1_rules"

# Error codes (flag_reason values). None on PASS.
ERR_PROMPT_INJECTION = "ERR_PROMPT_INJECTION"
ERR_FULL_SOLUTION_REQUEST = "ERR_FULL_SOLUTION_REQUEST"
ERR_OFF_TOPIC = "ERR_OFF_TOPIC"
ERR_LANGUAGE_SWITCH = "ERR_LANGUAGE_SWITCH"
ERR_INAPPROPRIATE_CONTENT = "ERR_INAPPROPRIATE_CONTENT"
ERR_EMPTY_INPUT = "ERR_EMPTY_INPUT"


class InputGuardrailResult(BaseModel):
    """One classification of a single student message.

    The input guardrail classifies ONLY the current message. It does not own
    violation_count — the orchestrator decides warning / END_CHAT / carrot.
    """

    action: Literal["PASS", "BLOCK"]
    flag_reason: Optional[str] = None
    processed_input: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    latency_ms: int = Field(ge=0)
    version: str = VERSION

    def to_log_dict(self) -> dict:
        """Exactly the keys the orchestrator logs under input_guardrail."""
        return {
            "action": self.action,
            "flag_reason": self.flag_reason,
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "version": self.version,
        }
