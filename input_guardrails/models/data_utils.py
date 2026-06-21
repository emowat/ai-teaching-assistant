"""Shared data utilities for the Input CodeBERT guardrail train/eval scripts.

Pure-stdlib (no torch / transformers / sklearn imports here) so the data tests
load fast and the dry-run path needs no ML deps.

Dataset semantics:
    label = 1  -> unsafe / BLOCK / should_call_llm = false
    label = 0  -> safe   / PASS  / should_call_llm = true

The hard gold set (input_hard_gold_v1.jsonl) is EXTERNAL EVALUATION ONLY and
must never be loaded as training data.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

LABEL_UNSAFE = 1  # BLOCK
LABEL_SAFE = 0    # PASS


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_jsonl(path: str | Path) -> list[dict]:
    path = Path(path)
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_splits(path: str | Path) -> dict:
    """Return {context_id: 'train'|'val'|'test'}."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Input formatting — MUST be identical in train and eval.
# ---------------------------------------------------------------------------

def format_example(row: dict) -> str:
    """Format one row into the model's text input. Tagged sections so the
    tokenizer sees clear landmarks for query / code / topic / assignment.
    """
    return (
        "[USER_QUERY]\n"
        f"{(row.get('user_query') or '').strip()}\n\n"
        "[STUDENT_CODE]\n"
        f"{(row.get('student_code') or '').strip()}\n\n"
        "[COURSE_TOPIC]\n"
        f"{(row.get('course_topic') or '').strip()}\n\n"
        "[ASSIGNMENT_CONTEXT]\n"
        f"{(row.get('assignment_context') or '').strip()}"
    )


# ---------------------------------------------------------------------------
# Splitting by context_id
# ---------------------------------------------------------------------------

def apply_splits(rows: list[dict], splits: dict, *, require_reviewed: bool = False):
    """Partition rows into train/val/test by their context_id.

    Args:
        rows: candidate rows.
        splits: {context_id: split_name}.
        require_reviewed: if True, drop rows where reviewed is not True.

    Returns:
        dict {"train": [...], "val": [...], "test": [...]} and a list of rows
        whose context_id had no split entry (reported, not silently dropped).
    """
    if require_reviewed:
        rows = [r for r in rows if r.get("reviewed") is True]

    buckets = {"train": [], "val": [], "test": []}
    unassigned = []
    for r in rows:
        split = splits.get(r["context_id"])
        if split in buckets:
            buckets[split].append(r)
        else:
            unassigned.append(r)
    return buckets, unassigned


def assert_no_context_leakage(buckets: dict) -> None:
    """Raise AssertionError if any context_id appears in more than one split."""
    ctx_to_splits: dict[str, set] = {}
    for split_name, rows in buckets.items():
        for r in rows:
            ctx_to_splits.setdefault(r["context_id"], set()).add(split_name)
    leaked = {cid: s for cid, s in ctx_to_splits.items() if len(s) > 1}
    assert not leaked, f"context_id leakage across splits: {leaked}"


def context_ids(rows: list[dict]) -> set:
    return {r["context_id"] for r in rows}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def label_distribution(rows: list[dict]) -> dict:
    """{0: n_safe, 1: n_unsafe}."""
    return dict(Counter(int(r["label"]) for r in rows))


def split_report(buckets: dict) -> str:
    lines = []
    for name in ("train", "val", "test"):
        rows = buckets.get(name, [])
        dist = label_distribution(rows)
        n_ctx = len(context_ids(rows))
        lines.append(
            f"  {name:<5} rows={len(rows):<4} contexts={n_ctx:<3} "
            f"label{{0(safe):{dist.get(0,0)}, 1(unsafe):{dist.get(1,0)}}}"
        )
    return "\n".join(lines)
