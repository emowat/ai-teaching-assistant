"""Runtime orchestration for the input guardrail pipeline.

Rules run first. If they pass, an optional CodeBERT classifier score can
block the request before RAG/inference. The model stage is best-effort and
fails open when the checkpoint is unavailable.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Optional

from input_guardrails.detector import check_input_guardrail
from input_guardrails.models import VERSION, format_example
from input_guardrails.responses import first_warning_response, response_for

_CHECKPOINT_ENV_VAR = "INPUT_GUARDRAILS_CODEBERT_CHECKPOINT_DIR"
_ENABLED_ENV_VAR = "INPUT_GUARDRAILS_ENABLED"
_PASS_BELOW_ENV_VAR = "INPUT_GUARDRAILS_CODEBERT_PASS_BELOW"
_BLOCK_ABOVE_ENV_VAR = "INPUT_GUARDRAILS_CODEBERT_BLOCK_ABOVE"

_DEFAULT_CHECKPOINT_DIR = (
    Path(__file__).resolve().parent / "models" / "checkpoints" / "input_codebert_v1"
)

_PASS_BELOW = float(os.getenv(_PASS_BELOW_ENV_VAR, "0.30"))
# Input CodeBERT selected baseline deployment threshold. Can be overridden by INPUT_GUARDRAILS_CODEBERT_BLOCK_ABOVE.
_BLOCK_ABOVE = float(os.getenv(_BLOCK_ABOVE_ENV_VAR, "0.80"))

_model = None
_tokenizer = None
_loaded_checkpoint_dir: Optional[Path] = None
_predict_fn: Optional[Callable[[str], float]] = None


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def set_thresholds(pass_below: float, block_above: float) -> None:
    """Override the model decision thresholds at runtime."""
    global _PASS_BELOW, _BLOCK_ABOVE
    if not 0.0 <= pass_below < block_above <= 1.0:
        raise ValueError("require 0 <= pass_below < block_above <= 1")
    _PASS_BELOW = pass_below
    _BLOCK_ABOVE = block_above


def set_predict_fn(fn: Optional[Callable[[str], float]]) -> None:
    """Inject a predict function for tests."""
    global _predict_fn
    _predict_fn = fn


def resolve_checkpoint_dir(explicit: str | Path | None = None) -> Path:
    """Resolve the local Hugging Face checkpoint directory."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env_path = os.getenv(_CHECKPOINT_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _DEFAULT_CHECKPOINT_DIR.resolve()


def runtime_status(checkpoint_dir: str | Path | None = None) -> dict[str, Any]:
    """Return current runtime configuration and local checkpoint state."""
    resolved = resolve_checkpoint_dir(checkpoint_dir)
    enabled = _env_bool(_ENABLED_ENV_VAR, True)
    return {
        "enabled": enabled,
        "checkpoint_dir": str(resolved),
        "checkpoint_exists": resolved.exists(),
        "pass_below": _PASS_BELOW,
        "block_above": _BLOCK_ABOVE,
        "version": VERSION,
    }


def _try_load_model(checkpoint_dir: str | Path | None = None):
    """Attempt to load the classifier and tokenizer. Returns (model, tokenizer)."""
    global _model, _tokenizer, _loaded_checkpoint_dir
    checkpoint_path = resolve_checkpoint_dir(checkpoint_dir)
    if (
        _model is not None
        and _tokenizer is not None
        and _loaded_checkpoint_dir == checkpoint_path
    ):
        return _model, _tokenizer

    _model = None
    _tokenizer = None
    _loaded_checkpoint_dir = None
    if not checkpoint_path.exists():
        return None, None

    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: WPS433

        _tokenizer = AutoTokenizer.from_pretrained(str(checkpoint_path))
        _model = AutoModelForSequenceClassification.from_pretrained(str(checkpoint_path))
        _model.eval()
        _loaded_checkpoint_dir = checkpoint_path
        return _model, _tokenizer
    except Exception:  # noqa: BLE001 - runtime should fail open
        _model = None
        _tokenizer = None
        _loaded_checkpoint_dir = None
        return None, None


def _score_model(text: str, checkpoint_dir: str | Path | None = None) -> float | None:
    model, tokenizer = _try_load_model(checkpoint_dir)
    if model is None or tokenizer is None:
        return None

    import torch  # noqa: WPS433

    inputs = tokenizer(
        text,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    with torch.no_grad():
        logits = model(**inputs).logits
        score = torch.softmax(logits, dim=-1)[0, 1].item()
    return float(score)


def _format_model_input(
    *,
    student_message: str,
    student_code: str,
    course_topic: str,
    assignment_context: str,
) -> str:
    return format_example(
        {
            "user_query": student_message,
            "student_code": student_code,
            "course_topic": course_topic,
            "assignment_context": assignment_context,
        }
    )


def evaluate_input_guardrail(
    *,
    student_message: str,
    student_code: str = "",
    course_topic: str = "",
    assignment_context: str = "",
    checkpoint_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the input guardrail stack and return a structured decision."""
    started = time.perf_counter()
    # Pass pasted/selected code through so a code-only paste (empty message +
    # code) is treated as a valid request instead of ERR_EMPTY_INPUT.
    rule_result = check_input_guardrail(
        student_message,
        ide_context={"student_code": student_code} if student_code else None,
    )
    rule_data = rule_result.model_dump()
    model_enabled = _env_bool(_ENABLED_ENV_VAR, True)
    resolved_checkpoint_dir = resolve_checkpoint_dir(checkpoint_dir)

    result: dict[str, Any] = {
        "stage": "input_guardrail",
        "action": "pass",
        "safe": True,
        "blocked": False,
        "violation_type": "none",
        "severity": "",
        "evidence": "rules passed",
        "final_answer": "",
        "version": f"{VERSION}+input_codebert_v1",
        "latency_ms": 0,
        "rules": rule_data,
        "model": {
            "enabled": model_enabled,
            "available": False,
            "decision": "skipped",
            "score": None,
            "pass_below": _PASS_BELOW,
            "block_above": _BLOCK_ABOVE,
            "checkpoint_dir": str(resolved_checkpoint_dir),
        },
    }

    if rule_result.action == "BLOCK":
        result.update(
            {
                "action": "block",
                "safe": False,
                "blocked": True,
                "violation_type": rule_result.flag_reason or "ERR_INPUT_GUARDRAIL_RULE",
                "severity": "medium",
                "evidence": f"rule hit {rule_result.flag_reason or 'input guardrail rule'}",
                "final_answer": response_for(rule_result.flag_reason),
                "model": {
                    **result["model"],
                    "decision": "skipped",
                },
            }
        )
        result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
        return result

    if not model_enabled:
        result["evidence"] = "input guardrail model disabled; rules passed"
        result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
        return result

    text = _format_model_input(
        student_message=student_message,
        student_code=student_code,
        course_topic=course_topic,
        assignment_context=assignment_context,
    )

    score = _predict_fn(text) if _predict_fn is not None else _score_model(text, resolved_checkpoint_dir)
    model_meta = {
        **result["model"],
        "available": score is not None,
        "score": score,
    }

    if score is None:
        result["evidence"] = "input guardrail model unavailable; rules passed"
        result["model"] = {
            **model_meta,
            "decision": "pass",
        }
        result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
        return result

    if score < _PASS_BELOW:
        result["evidence"] = f"input model score={score:.3f} < {_PASS_BELOW:.2f}"
        result["model"] = {
            **model_meta,
            "decision": "pass",
        }
        result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
        return result

    if score > _BLOCK_ABOVE:
        result.update(
            {
                "action": "block",
                "safe": False,
                "blocked": True,
                "violation_type": "ERR_INPUT_MODEL_UNSAFE",
                "severity": "medium",
                "evidence": f"input model score={score:.3f} > {_BLOCK_ABOVE:.2f}",
                "final_answer": first_warning_response(),
                "model": {
                    **model_meta,
                    "decision": "block",
                },
            }
        )
        result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
        return result

    result.update(
        {
            "action": "log_only",
            "safe": False,
            "blocked": False,
            "violation_type": "ERR_INPUT_MODEL_UNCERTAIN",
            "severity": "low",
            "evidence": (
                f"input model score={score:.3f} in "
                f"[{_PASS_BELOW:.2f}, {_BLOCK_ABOVE:.2f}]"
            ),
            "final_answer": "",
            "model": {
                **model_meta,
                "decision": "log_only",
            },
        }
    )
    result["latency_ms"] = max(0, round((time.perf_counter() - started) * 1000))
    return result
