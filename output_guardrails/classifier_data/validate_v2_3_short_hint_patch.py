"""
Validate the v2.3 short-hint output guardrail patch dataset.

Run from repo root:
    python output_guardrails/classifier_data/validate_v2_3_short_hint_patch.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

BASE_DATASET  = HERE / "classifier_dataset_v2_2_merged.jsonl"  # v2.2 is the correct base for v2.3
PATCH         = HERE / "output_guardrail_v2_3_short_hint_patch.jsonl"
GOLD          = HERE / "hard_gold_test_set_v2_3_short_hint.jsonl"
MERGED        = HERE / "classifier_dataset_v2_3_merged.jsonl"
SPLITS        = HERE / "splits_v2_3.json"

REQUIRED_KEYS = {
    "scenario_id", "context_id", "user_query", "student_code",
    "assistant_draft", "label", "violation_type", "source",
    "label_source", "topic_style", "uses_placeholder", "reviewed", "id",
}

errors = []

def check(cond, msg):
    if not cond:
        errors.append(msg)

def load(path):
    if not path.exists():
        errors.append(f"MISSING file: {path.name}")
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


print("Loading files…")
base   = load(BASE_DATASET)
patch  = load(PATCH)
gold   = load(GOLD)
merged = load(MERGED)
splits = json.loads(SPLITS.read_text()) if SPLITS.exists() else {}

all_new = patch + gold
print(f"  base={len(base)} patch={len(patch)} gold={len(gold)} merged={len(merged)}")

# 1. all required fields
for r in all_new:
    missing = REQUIRED_KEYS - set(r)
    check(not missing, f"row {r.get('id','?')} missing: {missing}")

# 2. labels 0 or 1
check(all(r["label"] in (0,1) for r in all_new), "some rows have non-binary labels")

# 3. reviewed=true
check(all(r.get("reviewed") is True for r in all_new), "some new rows have reviewed != True")

# 4. no duplicate ids
ids = [r["id"] for r in all_new]
check(len(ids) == len(set(ids)), f"duplicate ids: {[i for i,c in Counter(ids).items() if c>1][:5]}")

# 5. no duplicate scenario_ids
sids = [r["scenario_id"] for r in all_new]
check(len(sids) == len(set(sids)), f"duplicate scenario_ids: {[i for i,c in Counter(sids).items() if c>1][:5]}")

# 6. no duplicate assistant_draft (first 80 chars) across patch AND gold
drafts_patch = [r["assistant_draft"][:80] for r in patch]
drafts_gold  = [r["assistant_draft"][:80] for r in gold]
dup_within_patch = [d for d,c in Counter(drafts_patch).items() if c>1]
dup_pg = set(drafts_patch) & set(drafts_gold)
check(not dup_within_patch, f"duplicate drafts within patch: {len(dup_within_patch)}")
check(not dup_pg, f"draft overlap between patch and gold: {len(dup_pg)}")

# 7. no <analysis> tags
check(all("<analysis>" not in r["assistant_draft"].lower() for r in all_new),
      "some rows contain <analysis> tags")

# 8. no context_id in multiple splits
ctx_splits: dict[str, set] = {}
for r in merged:
    cid = r["context_id"]
    sp = splits.get(cid)
    if sp:
        ctx_splits.setdefault(cid, set()).add(sp)
multi = {c: s for c, s in ctx_splits.items() if len(s) > 1}
check(not multi, f"context_ids in multiple splits: {list(multi.keys())[:5]}")

# 9. gold context_ids not in splits
gold_ctx = {r["context_id"] for r in gold}
leaked = gold_ctx & set(splits)
check(not leaked, f"gold context_ids leaked into splits: {list(leaked)[:5]}")

# 10. merged count = base + patch
check(len(merged) == len(base) + len(patch),
      f"merged {len(merged)} != base {len(base)} + patch {len(patch)} = {len(base)+len(patch)}")

# 11. safe and unsafe both present in patch
pd = Counter(r["label"] for r in patch)
check(pd[0] > 0 and pd[1] > 0, f"patch missing safe or unsafe rows: {dict(pd)}")

# Print results
print("\n" + "="*60)
print("VALIDATION RESULTS")
print("="*60)
if errors:
    print(f"\n❌ {len(errors)} ERROR(S):")
    for e in errors[:20]:
        print(f"  - {e}")
else:
    print("\n✅ All 11 checks passed")

def dist(rows, name):
    d = Counter(r["label"] for r in rows)
    print(f"  {name:<48} total={len(rows):>4}  safe(0)={d[0]:>4}  unsafe(1)={d[1]:>4}")

print("\n=== LABEL DISTRIBUTIONS ===")
dist(base,   "v2.1 base")
dist(patch,  "v2.3 patch (new rows only)")
dist(merged, "v2.3 merged (base + patch)")
dist(gold,   "v2.3 hard gold (eval only)")

print("\n=== SPLIT DISTRIBUTION ===")
sc = Counter(splits.values())
print(f"  contexts: train={sc['train']} val={sc['val']} test={sc['test']} total={len(splits)}")
by_split = {"train": 0, "val": 0, "test": 0}
for r in merged:
    s = splits.get(r["context_id"])
    if s: by_split[s] += 1
print(f"  rows:     train={by_split['train']} val={by_split['val']} test={by_split['test']}")

print("\n=== TOP VIOLATION_TYPES (patch) ===")
for k, v in Counter(r.get("violation_type") for r in patch).most_common(15):
    print(f"  {v:>3}  {k}")

print("\n=== TOP TOPIC_STYLES (patch) ===")
for k, v in Counter(r.get("topic_style") for r in patch).most_common(8):
    print(f"  {v:>3}  {k}")

print("\n=== 5 SAFE EXAMPLE ROWS ===")
safe_ex = [r for r in patch if r["label"] == 0][:5]
for r in safe_ex:
    print(f"\n  [{r['violation_type']}]")
    print(f"  Q: {r['user_query'][:70]}")
    print(f"  A: {r['assistant_draft'][:110]}")

print("\n=== 5 UNSAFE EXAMPLE ROWS ===")
unsafe_ex = [r for r in patch if r["label"] == 1][:5]
for r in unsafe_ex:
    print(f"\n  [{r['violation_type']}]")
    print(f"  Q: {r['user_query'][:70]}")
    print(f"  A: {r['assistant_draft'][:110]}")

if errors:
    sys.exit(1)
