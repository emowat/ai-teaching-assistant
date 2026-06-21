"""Input guardrail (v1, rule-based) for the CodingRabbit C++ Socratic TA.

Runs on the student's RAW question BEFORE RAG/Qwen inference to block obvious
adversarial / off-topic / full-solution / inappropriate requests and save GPU
cost. Deterministic, fast, no LLM or external calls.

Pipeline position:
    Student input -> [Input guardrail] -> RAG/Qwen -> Output guardrails -> Final answer

This module is fully self-contained: it does NOT import from output_guardrails
or touch the CodeBERT model, thresholds, S3, or SageMaker.
"""

from .detector import check_input_guardrail
from .models import InputGuardrailResult

__all__ = ["check_input_guardrail", "InputGuardrailResult"]
