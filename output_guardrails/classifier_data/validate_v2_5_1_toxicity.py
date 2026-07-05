"""Validate the v2.5.1 TOXICITY robustness dataset (short-safe patch).

Run: python output_guardrails/classifier_data/validate_v2_5_1_toxicity.py

Checks the rebuilt merged corpus + splits, the v2.5.1 short-safe patch,
and BOTH held-out gold sets (original v2.5 gold + v2.5.1 supplemental).
Exits non-zero on any hard failure.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "output_guardrail_v2_5_1_toxicity_short_safe_patch.jsonl"
MERGED = HERE / "classifier_dataset_v2_5_toxicity_merged.jsonl"
SPLITS = HERE / "splits_v2_5_toxicity.json"
GOLD_V25 = HERE / "hard_gold_test_set_v2_5_toxicity.jsonl"
GOLD_V251 = HERE / "hard_gold_test_set_v2_5_1_short_safe_toxicity.jsonl"

REQUIRED = {"scenario_id", "context_id", "user_query", "student_code",
            "assistant_draft", "label", "violation_type", "source",
            "label_source", "topic_style", "uses_placeholder", "reviewed", "id"}

FORBIDDEN_UNSAFE_TYPES = {
    "code_leakage", "unfenced_inline_code_leakage", "pseudocode_solution",
    "exact_patch_changed_line", "direct_solution", "unsafe_multistatement_direct_patch",
    "unsafe_direct_code_replacement", "unsafe_full_solution_leakage",
    "unsafe_fenced_solution_code", "unsafe_fenced_code_solution",
    "unsafe_direct_answer_leakage", "unsafe_exact_line_replacement",
    "unsafe_multistatement_inline_patch", "unsafe_full_function_solution",
    "unsafe_complete_class_solution",
    "persona_drift", "off_topic_leakage", "system_prompt_leakage",
    "unsafe_end_chat", "unsafe_content_embedded_in_code",
}

# v2.5.1 targets.
PATCH_MIN, PATCH_MAX = 180, 240
PATCH_SAFE_MIN, PATCH_SAFE_MAX = 120, 170
PATCH_UNSAFE_MIN, PATCH_UNSAFE_MAX = 50, 80
MERGED_MIN, MERGED_MAX = 1000, 1100
SUPP_GOLD_TOTAL, SUPP_GOLD_SAFE, SUPP_GOLD_UNSAFE = 60, 35, 25

errors: list[str] = []
warns: list[str] = []


def err(cond, msg):
    if not cond:
        errors.append(msg)


def warn(cond, msg):
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
gold_v25 = load(GOLD_V25)
gold_v251 = load(GOLD_V251)
splits = json.loads(SPLITS.read_text()) if SPLITS.exists() else {}
if not SPLITS.exists():
    errors.append("MISSING FILE: splits_v2_5_toxicity.json")

gold_all = gold_v25 + gold_v251
all_rows = merged + gold_all

# --- schema / fields ------------------------------------------------------
err(all(REQUIRED.issubset(r) for r in all_rows), "some rows missing required fields")
err(all(r.get("label") in (0, 1) for r in all_rows), "labels not all in {0,1}")
err(all(r.get("reviewed") is True for r in all_rows), "some rows reviewed != True")
err(not any("<analysis>" in r.get("assistant_draft", "").lower() for r in all_rows),
    "<analysis>/CoT found in a draft")
err(not any("</analysis>" in r.get("assistant_draft", "").lower() for r in all_rows),
    "</analysis>/CoT found in a draft")

# --- duplicate id / scenario_id -------------------------------------------
ids = [r["id"] for r in all_rows]
err(len(ids) == len(set(ids)),
    f"duplicate ids: {[i for i, c in Counter(ids).items() if c > 1][:5]}")
sids = [r["scenario_id"] for r in all_rows if r.get("scenario_id")]
err(len(sids) == len(set(sids)),
    f"duplicate scenario_ids: {[s for s, c in Counter(sids).items() if c > 1][:5]}")

# --- forbidden categories as unsafe ---------------------------------------
bad = [r for r in all_rows if r["label"] == 1 and r.get("violation_type") in FORBIDDEN_UNSAFE_TYPES]
err(not bad, f"{len(bad)} unsafe rows with code-leak/persona/off-topic/system-boundary "
             f"category (e.g. {[r['violation_type'] for r in bad[:3]]})")

# --- draft overlap between training and either gold -----------------------
train_drafts = {r["assistant_draft"].strip() for r in merged}
gold_drafts = {r["assistant_draft"].strip() for r in gold_all}
overlap = train_drafts & gold_drafts
err(not overlap, f"{len(overlap)} assistant_draft(s) shared between merged and gold "
                 f"(e.g. {list(overlap)[:3]})")

# --- context leakage ------------------------------------------------------
ctx_to_splits: dict[str, set] = {}
for r in merged:
    s = splits.get(r["context_id"])
    if s:
        ctx_to_splits.setdefault(r["context_id"], set()).add(s)
multi = {c: s for c, s in ctx_to_splits.items() if len(s) > 1}
err(not multi, f"context_id in multiple splits: {list(multi)[:5]}")
missing = [r["context_id"] for r in merged if r["context_id"] not in splits]
err(not missing, f"{len(missing)} merged contexts missing from splits")
gold_ctxs = {r["context_id"] for r in gold_all}
leaked = gold_ctxs & set(splits)
err(not leaked, f"{len(leaked)} gold contexts appear in train/val/test")

# --- count / balance bands ------------------------------------------------
pdst = Counter(r["label"] for r in patch)
err(PATCH_MIN <= len(patch) <= PATCH_MAX, f"patch size {len(patch)} outside [{PATCH_MIN},{PATCH_MAX}]")
err(PATCH_SAFE_MIN <= pdst[0] <= PATCH_SAFE_MAX, f"patch safe {pdst[0]} outside [{PATCH_SAFE_MIN},{PATCH_SAFE_MAX}]")
err(PATCH_UNSAFE_MIN <= pdst[1] <= PATCH_UNSAFE_MAX, f"patch unsafe {pdst[1]} outside [{PATCH_UNSAFE_MIN},{PATCH_UNSAFE_MAX}]")

mdst = Counter(r["label"] for r in merged)
err(MERGED_MIN <= len(merged) <= MERGED_MAX, f"merged size {len(merged)} outside [{MERGED_MIN},{MERGED_MAX}]")
unsafe_frac = mdst[1] / len(merged) if merged else 0
err(0.20 <= unsafe_frac <= 0.45, f"merged unsafe fraction {unsafe_frac:.2f} outside [0.20,0.45]")

sgd = Counter(r["label"] for r in gold_v251)
err(len(gold_v251) == SUPP_GOLD_TOTAL, f"supp gold total {len(gold_v251)} != {SUPP_GOLD_TOTAL}")
err(sgd[0] == SUPP_GOLD_SAFE, f"supp gold safe {sgd[0]} != {SUPP_GOLD_SAFE}")
err(sgd[1] == SUPP_GOLD_UNSAFE, f"supp gold unsafe {sgd[1]} != {SUPP_GOLD_UNSAFE}")

# Short-safe rows should really be short (robustness intent).
long_safe = [r for r in patch if r["label"] == 0 and len(r["assistant_draft"].split()) > 20]
warn(not long_safe, f"{len(long_safe)} 'short safe' patch rows exceed 20 words")

# ---------------------------------------------------------------------------
print("=" * 64)
print("v2.5.1 TOXICITY ROBUSTNESS VALIDATION")
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
    print(f"  {name:<44} total={len(rows):>5}  safe={d[0]:>5}  unsafe={d[1]:>5}")


print("\n=== DISTRIBUTIONS ===")
dist(patch, "v2.5.1 patch (short safe + short toxic)")
dist(merged, "merged (rebuilt training corpus)")
dist(gold_v25, "hard gold v2.5 (held out)")
dist(gold_v251, "hard gold v2.5.1 supplemental (held out)")

print("\n=== SPLITS ===")
sc = Counter(splits.values())
print(f"  contexts: train={sc['train']} val={sc['val']} test={sc['test']} total={len(splits)}")
by = Counter(splits.get(r["context_id"]) for r in merged)
print(f"  rows:     train={by['train']} val={by['val']} test={by['test']}")

print("\n=== v2.5.1 PATCH SAFE BY CATEGORY ===")
for k, v in Counter(r["violation_type"] for r in patch if r["label"] == 0).most_common():
    print(f"  {v:>4}  {k}")
print("\n=== v2.5.1 PATCH UNSAFE BY CATEGORY ===")
for k, v in Counter(r["violation_type"] for r in patch if r["label"] == 1).most_common():
    print(f"  {v:>4}  {k}")

if errors:
    sys.exit(1)
