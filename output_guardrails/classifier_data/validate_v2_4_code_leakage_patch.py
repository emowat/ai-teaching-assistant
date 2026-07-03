"""Validate the v2.4 code-leakage-only output guardrail dataset.
Run: python output_guardrails/classifier_data/validate_v2_4_code_leakage_patch.py
"""
import json, sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH   = HERE / "output_guardrail_v2_4_code_leakage_patch.jsonl"
GOLD    = HERE / "hard_gold_test_set_v2_4_code_leakage.jsonl"
MERGED  = HERE / "classifier_dataset_v2_4_code_leakage_merged.jsonl"
SPLITS  = HERE / "splits_v2_4_code_leakage.json"

REQUIRED = {"scenario_id","context_id","user_query","student_code","assistant_draft",
             "label","violation_type","source","label_source","topic_style",
             "uses_placeholder","reviewed","id"}

# Types that must NOT appear as label=1 in v2.4 (out of scope)
OUT_OF_SCOPE_UNSAFE = {
    "unsafe_real_world_harm_language","unsafe_content_embedded_in_code",
    "persona_drift","off_topic_leakage","system_prompt_leakage","unsafe_end_chat",
}

errors = []
def chk(cond, msg):
    if not cond: errors.append(msg)

def load(p):
    if not p.exists(): errors.append(f"MISSING: {p.name}"); return []
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

print("Loading…")
patch  = load(PATCH); gold = load(GOLD); merged = load(MERGED)
splits = json.loads(SPLITS.read_text()) if SPLITS.exists() else {}

print(f"  patch={len(patch)} gold={len(gold)} merged={len(merged)}")

all_new = patch + gold
chk(all(REQUIRED.issubset(r) for r in all_new), "some rows missing required fields")
chk(all(r["label"] in (0,1) for r in all_new), "labels not in {0,1}")
chk(all(r.get("reviewed") is True for r in all_new), "some rows have reviewed!=True")
chk(not any("<analysis>" in r["assistant_draft"].lower() for r in all_new), "<analysis> tags found")

ids = [r["id"] for r in all_new]
chk(len(ids)==len(set(ids)), f"duplicate ids: {[i for i,c in Counter(ids).items() if c>1][:5]}")

sids = [r["scenario_id"] for r in all_new]
chk(len(sids)==len(set(sids)), f"duplicate scenario_ids: {[i for i,c in Counter(sids).items() if c>1][:5]}")

# No duplicate drafts between patch and gold
dp = {r["assistant_draft"][:80] for r in patch}
dg = {r["assistant_draft"][:80] for r in gold}
chk(not (dp & dg), f"draft overlap patch↔gold: {len(dp & dg)}")

# No out-of-scope types as unsafe
bad_types = [r for r in merged if r["label"]==1 and r.get("violation_type","") in OUT_OF_SCOPE_UNSAFE]
chk(not bad_types, f"{len(bad_types)} out-of-scope unsafe rows (toxicity/persona/off_topic) in merged")

# No context leakage
ctx_splits: dict = {}
for r in merged:
    c = r["context_id"]; s = splits.get(c)
    if s: ctx_splits.setdefault(c, set()).add(s)
multi = {c:s for c,s in ctx_splits.items() if len(s)>1}
chk(not multi, f"context_id in multiple splits: {list(multi.keys())[:5]}")

gold_ctxs = {r["context_id"] for r in gold}
leaked = gold_ctxs & set(splits)
chk(not leaked, f"gold contexts in splits: {list(leaked)[:5]}")

# Safe and unsafe both present
pd = Counter(r["label"] for r in patch)
chk(pd[0]>0 and pd[1]>0, f"patch missing safe or unsafe: {dict(pd)}")

print("\n"+"="*60)
print("VALIDATION RESULTS")
print("="*60)
if errors:
    print(f"\n❌ {len(errors)} ERROR(S):")
    for e in errors[:20]: print(f"  - {e}")
else:
    print("\n✅ All checks passed")

def dist(rows, name):
    d = Counter(r["label"] for r in rows)
    print(f"  {name:<52} total={len(rows):>5}  safe={d[0]:>5}  unsafe={d[1]:>5}")

print("\n=== DISTRIBUTIONS ===")
dist(patch,  "v2.4 patch (new rows only)")
dist(merged, "v2.4 merged (training set)")
dist(gold,   "v2.4 hard gold (eval only)")

sc = Counter(splits.values())
print(f"\n=== SPLITS ===")
print(f"  contexts: train={sc['train']} val={sc['val']} test={sc['test']} total={len(splits)}")
by_split = Counter(splits.get(r["context_id"]) for r in merged)
print(f"  rows:     train={by_split['train']} val={by_split['val']} test={by_split['test']}")

print("\n=== TOP VIOLATION TYPES (patch unsafe) ===")
for k,v in Counter(r.get("violation_type") for r in patch if r["label"]==1).most_common(10):
    print(f"  {v:>3}  {k}")

print("\n=== TOP VIOLATION TYPES (merged unsafe) ===")
for k,v in Counter(r.get("violation_type") for r in merged if r["label"]==1).most_common(12):
    print(f"  {v:>4}  {k}")

print("\n=== 10 SAFE EXAMPLES (patch) ===")
for r in [x for x in patch if x["label"]==0][:10]:
    print(f"\n  [{r['violation_type']}]")
    print(f"  Q: {r['user_query'][:65]}")
    print(f"  A: {r['assistant_draft'][:105]}")

print("\n=== 10 UNSAFE EXAMPLES (patch) ===")
for r in [x for x in patch if x["label"]==1][:10]:
    print(f"\n  [{r['violation_type']}]")
    print(f"  Q: {r['user_query'][:65]}")
    print(f"  A: {r['assistant_draft'][:105]}")

if errors:
    sys.exit(1)
