"""Validate the v2.5 TOXICITY-ONLY output-guardrail dataset.

Run: python output_guardrails/classifier_data/validate_v2_5_toxicity.py

Exits non-zero if any hard check fails. Toxicity model rules:
  * label=1 must be genuine toxicity/harm only.
  * code-leakage / persona / off-topic / system-boundary categories must
    NOT appear as label=1.
  * hard-gold contexts and drafts must be disjoint from the training corpus.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "output_guardrail_v2_5_toxicity_patch.jsonl"
MERGED = HERE / "classifier_dataset_v2_5_toxicity_merged.jsonl"
GOLD = HERE / "hard_gold_test_set_v2_5_toxicity.jsonl"
SPLITS = HERE / "splits_v2_5_toxicity.json"

REQUIRED = {"scenario_id", "context_id", "user_query", "student_code",
            "assistant_draft", "label", "violation_type", "source",
            "label_source", "topic_style", "uses_placeholder", "reviewed", "id"}

# Categories that must never carry label=1 in this toxicity-only model.
FORBIDDEN_UNSAFE_TYPES = {
    # code leakage (V1 regex owns these)
    "code_leakage", "unfenced_inline_code_leakage", "pseudocode_solution",
    "exact_patch_changed_line", "direct_solution", "unsafe_multistatement_direct_patch",
    "unsafe_direct_code_replacement", "unsafe_full_solution_leakage",
    "unsafe_fenced_solution_code", "unsafe_fenced_code_solution",
    "unsafe_direct_answer_leakage", "unsafe_exact_line_replacement",
    "unsafe_multistatement_inline_patch", "unsafe_full_function_solution",
    "unsafe_complete_class_solution",
    # persona / off-topic / system boundary
    "persona_drift", "off_topic_leakage", "system_prompt_leakage",
    "unsafe_end_chat", "unsafe_content_embedded_in_code",
}

# Target bands (from the task spec).
MERGED_MIN, MERGED_MAX = 700, 1000
MERGED_SAFE_MIN, MERGED_SAFE_MAX = 500, 700
MERGED_UNSAFE_MIN, MERGED_UNSAFE_MAX = 150, 300
GOLD_TOTAL, GOLD_SAFE, GOLD_UNSAFE = 80, 50, 30

errors: list[str] = []
warns: list[str] = []


def err(cond: bool, msg: str) -> None:
    if not cond:
        errors.append(msg)


def warn(cond: bool, msg: str) -> None:
    if not cond:
        warns.append(msg)


def load(p: Path) -> list[dict]:
    if not p.exists():
        errors.append(f"MISSING FILE: {p.name}")
        return []
    rows = []
    for i, line in enumerate(p.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"{p.name}:{i} invalid JSON: {e}")
    return rows


patch = load(PATCH)
merged = load(MERGED)
gold = load(GOLD)
splits = json.loads(SPLITS.read_text()) if SPLITS.exists() else {}
if not SPLITS.exists():
    errors.append("MISSING FILE: splits_v2_5_toxicity.json")

all_rows = merged + gold

# --- schema / field checks -------------------------------------------------
err(all(REQUIRED.issubset(r) for r in all_rows), "some rows missing required fields")
err(all(r.get("label") in (0, 1) for r in all_rows), "labels not all in {0,1}")
err(all(r.get("reviewed") is True for r in all_rows), "some rows have reviewed != True")
err(not any("<analysis>" in r.get("assistant_draft", "").lower() for r in all_rows),
    "<analysis>/CoT text found in a draft")
err(not any("</analysis>" in r.get("assistant_draft", "").lower() for r in all_rows),
    "</analysis>/CoT text found in a draft")

# --- duplicate id / scenario_id -------------------------------------------
ids = [r["id"] for r in all_rows]
dup_ids = [i for i, c in Counter(ids).items() if c > 1]
err(not dup_ids, f"duplicate ids: {dup_ids[:5]}")

sids = [r["scenario_id"] for r in all_rows if r.get("scenario_id")]
dup_sids = [s for s, c in Counter(sids).items() if c > 1]
err(not dup_sids, f"duplicate scenario_ids: {dup_sids[:5]}")

# --- no forbidden categories as unsafe ------------------------------------
bad_unsafe = [r for r in all_rows if r["label"] == 1
              and r.get("violation_type") in FORBIDDEN_UNSAFE_TYPES]
err(not bad_unsafe,
    f"{len(bad_unsafe)} rows labeled unsafe with code-leak/persona/off-topic/"
    f"system-boundary category (e.g. {[r['violation_type'] for r in bad_unsafe[:3]]})")

# --- draft overlap between training corpus and hard gold ------------------
train_drafts = {r["assistant_draft"].strip() for r in merged}
gold_drafts = {r["assistant_draft"].strip() for r in gold}
overlap = train_drafts & gold_drafts
err(not overlap, f"{len(overlap)} assistant_draft(s) shared between merged and gold")

# --- context leakage across splits ----------------------------------------
ctx_to_splits: dict[str, set] = {}
for r in merged:
    s = splits.get(r["context_id"])
    if s:
        ctx_to_splits.setdefault(r["context_id"], set()).add(s)
multi = {c: s for c, s in ctx_to_splits.items() if len(s) > 1}
err(not multi, f"context_id in multiple splits: {list(multi)[:5]}")

missing_split = [r["context_id"] for r in merged if r["context_id"] not in splits]
err(not missing_split, f"{len(missing_split)} merged contexts missing from splits")

gold_ctxs = {r["context_id"] for r in gold}
leaked = gold_ctxs & set(splits)
err(not leaked, f"{len(leaked)} gold contexts appear in train/val/test splits")

# --- balance / size bands --------------------------------------------------
md = Counter(r["label"] for r in merged)
err(MERGED_MIN <= len(merged) <= MERGED_MAX,
    f"merged size {len(merged)} outside [{MERGED_MIN},{MERGED_MAX}]")
err(MERGED_SAFE_MIN <= md[0] <= MERGED_SAFE_MAX,
    f"merged safe {md[0]} outside [{MERGED_SAFE_MIN},{MERGED_SAFE_MAX}]")
err(MERGED_UNSAFE_MIN <= md[1] <= MERGED_UNSAFE_MAX,
    f"merged unsafe {md[1]} outside [{MERGED_UNSAFE_MIN},{MERGED_UNSAFE_MAX}]")

gd = Counter(r["label"] for r in gold)
err(len(gold) == GOLD_TOTAL, f"gold total {len(gold)} != {GOLD_TOTAL}")
err(gd[0] == GOLD_SAFE, f"gold safe {gd[0]} != {GOLD_SAFE}")
err(gd[1] == GOLD_UNSAFE, f"gold unsafe {gd[1]} != {GOLD_UNSAFE}")

pd = Counter(r["label"] for r in patch)
err(pd[0] > 0 and pd[1] > 0, f"patch missing a class: {dict(pd)}")

# Both safe and unsafe should carry >1 distinct violation_type category.
tox_cats = {r["violation_type"] for r in merged if r["label"] == 1}
warn(len(tox_cats) >= 3, f"few toxicity categories in merged: {tox_cats}")

# ---------------------------------------------------------------------------
print("=" * 64)
print("v2.5 TOXICITY DATASET VALIDATION")
print("=" * 64)
if errors:
    print(f"\n❌ {len(errors)} ERROR(S):")
    for e in errors:
        print(f"  - {e}")
else:
    print("\n✅ All hard checks passed")
if warns:
    print(f"\n⚠️  {len(warns)} WARNING(S):")
    for w in warns:
        print(f"  - {w}")


def dist(rows, name):
    d = Counter(r["label"] for r in rows)
    print(f"  {name:<40} total={len(rows):>5}  safe={d[0]:>5}  unsafe={d[1]:>5}")


print("\n=== DISTRIBUTIONS ===")
dist(patch, "patch (new authored rows)")
dist(merged, "merged (training corpus)")
dist(gold, "hard gold (held-out eval)")

print("\n=== SPLITS ===")
sc = Counter(splits.values())
print(f"  contexts: train={sc['train']} val={sc['val']} test={sc['test']} total={len(splits)}")
by = Counter(splits.get(r["context_id"]) for r in merged)
print(f"  rows:     train={by['train']} val={by['val']} test={by['test']}")

print("\n=== MERGED UNSAFE (toxicity) BY CATEGORY ===")
for k, v in Counter(r["violation_type"] for r in merged if r["label"] == 1).most_common():
    print(f"  {v:>4}  {k}")
print("\n=== MERGED SAFE BY CATEGORY (top 12) ===")
for k, v in Counter(r["violation_type"] for r in merged if r["label"] == 0).most_common(12):
    print(f"  {v:>4}  {k}")

if errors:
    sys.exit(1)
