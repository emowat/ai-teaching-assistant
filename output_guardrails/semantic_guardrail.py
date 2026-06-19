"""V2 semantic guardrail — CodeBERT classifier wrapper.

Same result shape as V1's apply_output_guardrails so combined.py can
chain them. The model is loaded lazily on first call so importing this
module is free (no torch import, no checkpoint load) until the runtime
actually needs to score a draft.

If the checkpoint or transformers package is unavailable, predict_safety
returns a "pass" result with evidence="v2 unavailable" — V1 still runs
and the system stays usable.

Public API:
    predict_safety(answer, user_query, student_code, conversation_history)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from .fallbacks import get_fallback

# Threshold policy from plan V2.11. Tunable via set_thresholds().
_PASS_BELOW = 0.30
_REPLACE_ABOVE = 0.70

_CHECKPOINT_ENV_VAR = "GUARDRAILS_CODEBERT_CHECKPOINT_DIR"
_DEFAULT_CHECKPOINT = (
    Path(__file__).resolve().parent / "models" / "checkpoints" / "codebert_v2_1"
)

# Cached singletons; populated on first real use.
_model = None
_tokenizer = None
_loaded_checkpoint_dir: Optional[Path] = None
_predict_fn: Optional[Callable[[str, str, str], float]] = None


def set_thresholds(pass_below: float, replace_above: float) -> None:
    """Adjust the pass / log_only / replace bands at runtime."""
    global _PASS_BELOW, _REPLACE_ABOVE
    if not 0.0 <= pass_below < replace_above <= 1.0:
        raise ValueError("require 0 <= pass_below < replace_above <= 1")
    _PASS_BELOW = pass_below
    _REPLACE_ABOVE = replace_above


def set_predict_fn(fn: Optional[Callable[[str, str, str], float]]) -> None:
    """Inject a custom predict function. Tests use this to stub the
    model. Pass None to revert to the real loader.
    """
    global _predict_fn
    _predict_fn = fn


def resolve_checkpoint_dir(explicit: str | Path | None = None) -> Path:
    """Resolve the CodeBERT checkpoint directory.

    The runtime prefers an explicit path, then the environment override,
    then the repo-local S3 restore target.
    """
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env_path = os.getenv(_CHECKPOINT_ENV_VAR)
    if env_path:
        return Path(env_path).expanduser().resolve()
    return _DEFAULT_CHECKPOINT.resolve()


def _try_load_model(checkpoint_dir: str | Path | None = None):
    """Attempt to load CodeBERT + tokenizer. Returns (model, tokenizer)
    or (None, None) if anything goes wrong. Never raises.
    """
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
        # Imported lazily so the package is usable without torch.
        from transformers import AutoModelForSequenceClassification, AutoTokenizer  # noqa: WPS433
        _tokenizer = AutoTokenizer.from_pretrained(str(checkpoint_path))
        _model = AutoModelForSequenceClassification.from_pretrained(str(checkpoint_path))
        _model.eval()
        _loaded_checkpoint_dir = checkpoint_path
        return _model, _tokenizer
    except Exception:  # noqa: BLE001 — broad on purpose; never crash runtime
        _model = None
        _tokenizer = None
        _loaded_checkpoint_dir = None
        return None, None


def _real_predict(user_query: str, student_code: str, assistant_draft: str) -> Optional[float]:
    """Run the loaded model. Returns p(unsafe) ∈ [0, 1] or None if the
    model is not available.
    """
    model, tokenizer = _try_load_model()
    if model is None or tokenizer is None:
        return None
    # Imported here so the test environment doesn't need torch.
    import torch  # noqa: WPS433
    from output_guardrails.models.tokenizer_utils import encode_with_truncation  # noqa: WPS433

    feats = encode_with_truncation(tokenizer, user_query, student_code, assistant_draft)
    input_ids = torch.tensor([feats["input_ids"]])
    mask = torch.tensor([feats["attention_mask"]])
    with torch.no_grad():
        logits = model(input_ids=input_ids, attention_mask=mask).logits
        prob_unsafe = torch.softmax(logits, dim=-1)[0, 1].item()
    return float(prob_unsafe)


def _result(*, safe, blocked, violation_type, severity, action,
            evidence, final_answer, v2_score):
    return {
        "safe": safe,
        "blocked": blocked,
        "violation_type": violation_type,
        "severity": severity,
        "action": action,
        "evidence": evidence,
        "final_answer": final_answer,
        "v2_score": v2_score,
    }


def predict_safety(
    answer: str,
    user_query: str,
    student_code: str,
    conversation_history: list,
) -> dict:
    """Score a draft response for semantic safety.

    Args mirror V1's apply_output_guardrails. conversation_history is
    accepted for shape compatibility but not used by the v2.0 model
    (multi-turn context is V2.1+ work).

    Returns the same dict shape V1 returns plus a v2_score float.
    """
    # Short-circuits (plan V2.1). [END_CHAT] check first so terminal
    # 2-word drafts like "Done. [END_CHAT]" route to the right branch.
    if "[END_CHAT]" in answer:
        return _result(
            safe=True, blocked=False, violation_type="none", severity="",
            action="pass", evidence="terminal state", final_answer=answer, v2_score=0.0,
        )
    if not answer or len(answer.split()) < 3:
        return _result(
            safe=True, blocked=False, violation_type="none", severity="",
            action="pass", evidence="empty/too-short draft",
            final_answer=answer, v2_score=0.0,
        )

    # Score: stub-injected fn (tests) > real model > unavailable.
    score: Optional[float] = None
    if _predict_fn is not None:
        try:
            score = float(_predict_fn(user_query, student_code, answer))
        except Exception:  # noqa: BLE001
            score = None
    if score is None:
        score = _real_predict(user_query, student_code, answer)

    if score is None:
        # Model unavailable: don't block, just log.
        return _result(
            safe=True, blocked=False, violation_type="none", severity="",
            action="pass", evidence="v2 unavailable",
            final_answer=answer, v2_score=0.0,
        )

    # Threshold-based dispatch.
    if score < _PASS_BELOW:
        return _result(
            safe=True, blocked=False, violation_type="none", severity="",
            action="pass", evidence=f"v2 score={score:.3f} < {_PASS_BELOW}",
            final_answer=answer, v2_score=score,
        )

    if score > _REPLACE_ABOVE:
        return _result(
            safe=False, blocked=True, violation_type="v2_unsafe", severity="medium",
            action="replace", evidence=f"v2 score={score:.3f} > {_REPLACE_ABOVE}",
            final_answer=get_fallback("off_topic"), v2_score=score,
        )

    # Uncertain band: keep original draft, flag for review.
    return _result(
        safe=False, blocked=False, violation_type="v2_uncertain", severity="low",
        action="log_only",
        evidence=f"v2 score={score:.3f} in [{_PASS_BELOW}, {_REPLACE_ABOVE}]",
        final_answer=answer, v2_score=score,
    )
