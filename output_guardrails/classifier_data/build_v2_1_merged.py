"""Build the v2_1 merged training dataset + splits.

Inputs:
    classifier_dataset.jsonl            (all base rows)
    classifier_dataset_v2_1_extra.jsonl (reviewed=true rows only)

Outputs:
    classifier_dataset_v2_1_merged.jsonl
    splits_v2_1.json

Design:
  - Every base row is kept (its fields preserved verbatim).
  - Only extra rows with reviewed==true are included.
  - hard_gold_test_set_v2_1.jsonl is NEVER read here, so it can't leak
    into training.
  - Splits are by context_id (sha256 of user_query+student_code), so any
    rows sharing the same (user_query, student_code) land in one split.
    Base contexts REUSE their existing split from splits.json (so v2_0
    train/val/test membership is unchanged). The new v2_1 extra contexts
    are assigned train/val/test deterministically with the same
    70/15/15 fractions and a fixed seed.

Run from ai-teaching-assistant/:
    python -m output_guardrails.classifier_data.build_v2_1_merged
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

DATA_DIR = PKG_ROOT / "classifier_data"
BASE_PATH = DATA_DIR / "classifier_dataset.jsonl"
EXTRA_PATH = DATA_DIR / "classifier_dataset_v2_1_extra.jsonl"
BASE_SPLITS_PATH = DATA_DIR / "splits.json"
ORIG_GOLD_PATH = DATA_DIR / "gold_test_set.jsonl"
HARD_GOLD_PATH = DATA_DIR / "hard_gold_test_set_v2_1.jsonl"

OUT_MERGED = DATA_DIR / "classifier_dataset_v2_1_merged.jsonl"
OUT_SPLITS = DATA_DIR / "splits_v2_1.json"

SPLIT_SEED = 42
SPLIT_FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}


def load_jsonl(path: Path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def assign_new_contexts(new_context_ids, seed=SPLIT_SEED):
    """Deterministically split a list of context_ids 70/15/15."""
    rng = random.Random(seed)
    cids = sorted(new_context_ids)
    rng.shuffle(cids)
    n = len(cids)
    n_train = int(n * SPLIT_FRACTIONS["train"])
    n_val = int(n * SPLIT_FRACTIONS["val"])
    out = {}
    for i, cid in enumerate(cids):
        if i < n_train:
            out[cid] = "train"
        elif i < n_train + n_val:
            out[cid] = "val"
        else:
            out[cid] = "test"
    return out


def main():
    base = load_jsonl(BASE_PATH)
    extra_all = load_jsonl(EXTRA_PATH)
    base_splits = json.loads(BASE_SPLITS_PATH.read_text())

    # Requirement #1: only reviewed==true extra rows.
    extra = [r for r in extra_all if r.get("reviewed") is True]
    skipped = len(extra_all) - len(extra)

    merged = base + extra

    # Splits: reuse base context assignments; assign new contexts fresh.
    base_ctx = {r["context_id"] for r in base}
    extra_ctx = {r["context_id"] for r in extra}
    new_ctx = extra_ctx - base_ctx  # contexts not already split by v2_0

    splits = dict(base_splits)  # start from the existing assignments
    splits.update(assign_new_contexts(new_ctx))

    # Every merged row's context must now have a split entry.
    missing = sorted({r["context_id"] for r in merged if r["context_id"] not in splits})
    if missing:
        print(f"[error] {len(missing)} merged contexts have no split entry; aborting")
        return

    # Write outputs (fields preserved verbatim per row).
    with OUT_MERGED.open("w") as f:
        for r in merged:
            f.write(json.dumps(r) + "\n")
    OUT_SPLITS.write_text(json.dumps(splits, indent=2, sort_keys=True))

    # ---- Console report ----
    print(f"base rows:   {len(base)}")
    print(f"extra rows:  {len(extra)} kept ({skipped} skipped for reviewed!=true)")
    print(f"merged rows: {len(merged)} -> {OUT_MERGED.name}")
    print(f"labels: {dict(Counter(r['label'] for r in merged))} (0=safe,1=unsafe)")

    by_split = Counter(splits[r["context_id"]] for r in merged)
    print(f"rows by split: {dict(by_split)}")
    print(f"new contexts assigned: {dict(Counter(assign_new_contexts(new_ctx).values()))}")


if __name__ == "__main__":
    main()
