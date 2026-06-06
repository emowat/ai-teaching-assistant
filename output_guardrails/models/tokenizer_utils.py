"""Shared input formatter for the V2 CodeBERT classifier.

The same formatter is used by training, evaluation, AND runtime
inference (guardrails/semantic_guardrail.py) so the model sees an
identical input schema in every context.

Truncation policy (per plan V2.2):
    [CLS] USER_QUERY [SEP] STUDENT_CODE [SEP] ASSISTANT_DRAFT [SEP]
        - keep ASSISTANT_DRAFT whole (priority) up to MAX_DRAFT
        - keep USER_QUERY whole up to MAX_QUERY
        - middle-truncate STUDENT_CODE: head MAX_CODE_HEAD + tail
          MAX_CODE_TAIL, joined by " ... ".
"""

from __future__ import annotations

MODEL_NAME = "microsoft/codebert-base"
MAX_TOTAL_TOKENS = 512
MAX_QUERY_TOKENS = 64
MAX_DRAFT_TOKENS = 200
MAX_CODE_HEAD_TOKENS = 128
MAX_CODE_TAIL_TOKENS = 64


def format_input_text(user_query: str, student_code: str, assistant_draft: str) -> str:
    """Return a single string with the three fields delimited so the
    tokenizer can attend to each. We DO NOT use HF's text/text_pair
    interface because we have THREE fields, not two.

    The literal markers `<query>`, `<code>`, `<draft>` survive
    BPE tokenization as cheap section landmarks.
    """
    user_query = (user_query or "").strip()
    student_code = (student_code or "").strip()
    assistant_draft = (assistant_draft or "").strip()
    return (
        f"<query> {user_query} "
        f"<code> {student_code} "
        f"<draft> {assistant_draft}"
    )


def encode_with_truncation(tokenizer, user_query: str, student_code: str, assistant_draft: str):
    """Token-budget-aware encoder. Returns a dict suitable for passing
    to the model: input_ids, attention_mask.

    We truncate at the token level (not character level) so the budget
    is honored exactly.
    """
    q_ids = tokenizer.encode(f"<query> {user_query}", add_special_tokens=False)[:MAX_QUERY_TOKENS]
    d_ids = tokenizer.encode(f"<draft> {assistant_draft}", add_special_tokens=False)[:MAX_DRAFT_TOKENS]
    c_ids = tokenizer.encode(f"<code> {student_code}", add_special_tokens=False)
    if len(c_ids) > MAX_CODE_HEAD_TOKENS + MAX_CODE_TAIL_TOKENS:
        ellipsis = tokenizer.encode(" ... ", add_special_tokens=False)
        c_ids = (
            c_ids[:MAX_CODE_HEAD_TOKENS]
            + ellipsis
            + c_ids[-MAX_CODE_TAIL_TOKENS:]
        )

    cls_id = tokenizer.cls_token_id
    sep_id = tokenizer.sep_token_id
    body = q_ids + [sep_id] + c_ids + [sep_id] + d_ids
    body = body[: MAX_TOTAL_TOKENS - 2]  # leave room for [CLS] and [SEP]
    ids = [cls_id] + body + [sep_id]

    return {
        "input_ids": ids,
        "attention_mask": [1] * len(ids),
    }
