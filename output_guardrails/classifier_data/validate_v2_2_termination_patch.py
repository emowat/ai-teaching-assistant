"""
Validate the v2.2 termination-language patch dataset.
Run from repo root: python output_guardrails/classifier_data/validate_v2_2_termination_patch.py
"""

import json
from collections import Counter
from pathlib import Path

DATA_DIR = Path(__file__).parent

BASE_DATASET  = DATA_DIR / "output_guardrail_v2_1_files" / "classifier_dataset_v2_1_merged.jsonl"
BASE_GOLD_V21 = DATA_DIR / "output_guardrail_v2_1_files" / "hard_gold_test_set_v2_1.jsonl"
PATCH         = DATA_DIR / "output_guardrail_v2_2_termination_patch.jsonl"
GOLD_V22      = DATA_DIR / "hard_gold_test_set_v2_2_termination.jsonl"
MERGED        = DATA_DIR / "classifier_dataset_v2_2_merged.jsonl"
SPLITS_V22    = DATA_DIR / "splits_v2_2.json"

REQUIRED_KEYS = {
    "scenario_id", "context_id", "user_query", "student_code",
    "assistant_draft", "label", "violation_type", "source",
    "label_source", "topic_style", "uses_placeholder", "reviewed", "id",
}
FORBIDDEN_KEYS = {"analysis", "<analysis>"}

errors = []
warnings = []

def check(cond, msg, warn=False):
    if not cond:
        (warnings if warn else errors).append(msg)


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append(f"  Invalid JSON on line {i} in {path.name}: {e}")
    return rows


print("Loading files...")
base_rows      = load_jsonl(BASE_DATASET)
patch_rows     = load_jsonl(PATCH)
gold_v21_rows  = load_jsonl(BASE_GOLD_V21)
gold_rows      = load_jsonl(GOLD_V22)
merged_rows    = load_jsonl(MERGED)
splits = json.load(open(SPLITS_V22, encoding="utf-8"))
print(f"  v2.1 base={len(base_rows)} patch={len(patch_rows)} gold_v2.1={len(gold_v21_rows)} gold_v2.2={len(gold_rows)} merged={len(merged_rows)}")

all_new = patch_rows + gold_rows

# 1. Every row has all required schema keys
for r in all_new:
    missing = REQUIRED_KEYS - set(r.keys())
    if missing:
        errors.append(f"  Row {r.get('id','?')} missing keys: {missing}")

# 2. Labels are only 0 or 1
for r in all_new:
    check(r.get("label") in (0, 1), f"  Row {r.get('id','?')} bad label: {r.get('label')}")

# 3. reviewed is True for all new rows
for r in all_new:
    check(r.get("reviewed") is True, f"  Row {r.get('id','?')} reviewed != True: {r.get('reviewed')}")

# 4. No duplicate ids (within patch + within gold)
patch_ids = [r["id"] for r in patch_rows]
gold_ids  = [r["id"] for r in gold_rows]
dup_patch = [i for i, c in Counter(patch_ids).items() if c > 1]
dup_gold  = [i for i, c in Counter(gold_ids).items() if c > 1]
check(not dup_patch, f"  Duplicate ids in patch: {dup_patch[:5]}")
check(not dup_gold,  f"  Duplicate ids in gold:  {dup_gold[:5]}")

# 5. No duplicate scenario_id
patch_sids = [r["scenario_id"] for r in patch_rows]
gold_sids  = [r["scenario_id"] for r in gold_rows]
dup_ps = [i for i, c in Counter(patch_sids).items() if c > 1]
dup_gs = [i for i, c in Counter(gold_sids).items() if c > 1]
check(not dup_ps, f"  Duplicate scenario_ids in patch: {dup_ps[:5]}")
check(not dup_gs, f"  Duplicate scenario_ids in gold:  {dup_gs[:5]}")

# 6. No overlap between v2.2 gold and v2.2 patch contexts
patch_ctx = {r["context_id"] for r in patch_rows}
gold_ctx  = {r["context_id"] for r in gold_rows}
overlap = patch_ctx & gold_ctx
check(not overlap, f"  context_id overlap between patch and gold: {len(overlap)} ids")

# 7. No context_id appears in more than one split
ctx_to_splits: dict = {}
for r in merged_rows:
    cid = r["context_id"]
    sp = splits.get(cid)
    if sp:
        ctx_to_splits.setdefault(cid, set()).add(sp)
multi_split = {c: s for c, s in ctx_to_splits.items() if len(s) > 1}
check(not multi_split, f"  context_id in multiple splits: {list(multi_split.keys())[:5]}")

# 8b. All existing v2.1 split assignments are preserved in v2.2 splits
v21_splits = json.load(open(DATA_DIR / "output_guardrail_v2_1_files" / "splits_v2_1.json", encoding="utf-8"))
changed_assignments = {
    cid: (v21_splits[cid], splits[cid])
    for cid in v21_splits
    if splits.get(cid) != v21_splits[cid]
}
check(not changed_assignments,
      f"  {len(changed_assignments)} v2.1 split assignments changed in v2.2 splits: {list(changed_assignments.items())[:3]}")

# 8. Merged row count = base + patch
check(
    len(merged_rows) == len(base_rows) + len(patch_rows),
    f"  Merged row count mismatch: {len(merged_rows)} != {len(base_rows)} + {len(patch_rows)} = {len(base_rows)+len(patch_rows)}"
)

# 9. No <analysis> tags in assistant_draft
for r in all_new:
    draft = r.get("assistant_draft", "")
    has_analysis = "<analysis>" in draft.lower() or "[analysis]" in draft.lower()
    check(not has_analysis, f"  Row {r.get('id','?')} contains analysis tag in draft")

# Print results
print("\n" + "="*60)
print("VALIDATION RESULTS")
print("="*60)
if errors:
    print(f"\n❌ {len(errors)} ERROR(S):")
    for e in errors[:20]:
        print(e)
else:
    print("\n✅ All checks passed — no errors")
if warnings:
    print(f"\n⚠  {len(warnings)} WARNING(S):")
    for w in warnings[:10]:
        print(w)

# ---- Distribution report ----
print("\n" + "="*60)
print("LABEL DISTRIBUTIONS")
print("="*60)
def dist(rows, name):
    d = Counter(r["label"] for r in rows)
    print(f"  {name:<45} total={len(rows):>4}  safe(0)={d[0]:>4}  unsafe(1)={d[1]:>4}")
dist(base_rows,     "v2.1 base (classifier_dataset_v2_1_merged)")
dist(patch_rows,    "v2.2 patch (new rows only)")
dist(merged_rows,   "v2.2 merged (v2.1 base + patch)")
dist(gold_v21_rows, "v2.1 hard gold (original eval only)")
dist(gold_rows,     "v2.2 hard gold termination (new eval only)")

print(f"\nPatch violation_type breakdown:")
for k, v in Counter(r["violation_type"] for r in patch_rows).most_common():
    print(f"  {k:<50} {v}")

print(f"\nSplit distribution (v2.2):")
sc = Counter(splits.values())
print(f"  train={sc['train']}  val={sc['val']}  test={sc['test']}  total_contexts={len(splits)}")

# ---- Sample examples ----
print("\n" + "="*60)
print("SAMPLE SAFE TECHNICAL ROWS (label=0)")
print("="*60)
safe_samples = [r for r in patch_rows if r["label"] == 0 and
                r["violation_type"] == "safe_systems_programming_termination_language"][:5]
for r in safe_samples:
    print(f"\n  id={r['id']}  topic={r['topic_style']}")
    print(f"  Q: {r['user_query'][:80]}")
    print(f"  A: {r['assistant_draft'][:140]}...")

print("\n" + "="*60)
print("SAMPLE UNSAFE CONTRAST ROWS (label=1)")
print("="*60)
unsafe_samples = [r for r in patch_rows if r["label"] == 1][:5]
for r in unsafe_samples:
    print(f"\n  id={r['id']}  topic={r['topic_style']}")
    print(f"  Q: {r['user_query'][:80]}")
    print(f"  A (blocked): {r['assistant_draft'][:100]}...")

print("\n" + "="*60)
print("SAMPLE BORDERLINE SOCRATIC ROWS (label=0)")
print("="*60)
soc_samples = [r for r in patch_rows if r["violation_type"] == "safe_socratic_tutoring_borderline"][:3]
for r in soc_samples:
    print(f"\n  id={r['id']}  topic={r['topic_style']}")
    print(f"  Q: {r['user_query'][:80]}")
    print(f"  A: {r['assistant_draft'][:140]}...")
