"""Validate the INPUT guardrail v1.1.1 targeted patch + rebuilt artifacts.

Run: python input_guardrails/classifier_data/validate_input_v1_1_1.py

Hard checks (exit 1 on any failure):
  - all required files exist and are valid JSONL / JSON
  - 14-field schema consistency across patch, merged, gold
  - labels only in {0,1}; label_name / should_call_llm / block_reason consistent
  - reviewed=true on patch + gold
  - unique ids within each file; patch and gold id-spaces disjoint
  - no context leakage (each context_id in exactly one split; gold disjoint)
  - no normalized-duplicate questions within patch; within gold
  - NO training overlap with either held-out hard-gold file (normalized query,
    and full formatted input); the two gold files are never merged into training
  - the new gold is disjoint (contexts + normalized text) from merged training
  - all existing v1.1 rows remain present in the merged set, with unchanged
    split assignments
  - expected distribution bands
Prints counts by split, label, and category.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "input_guardrail_v1_1_1_targeted_patch.jsonl"
MERGED = HERE / "input_classifier_dataset_v1_1_1_candidates.jsonl"
SPLITS = HERE / "splits_input_v1_1_1.json"
GOLD = HERE / "input_hard_gold_v1_1_1_targeted.jsonl"
# prior artifacts
V11_MERGED = HERE / "input_classifier_dataset_v1_1_candidates.jsonl"
V11_SPLITS = HERE / "splits_input_v1_1.json"
GOLD_V1 = HERE / "input_hard_gold_v1.jsonl"
GOLD_V11 = HERE / "input_hard_gold_v1_1_live_false_positive.jsonl"

REQUIRED = {"id", "context_id", "label", "label_name", "category", "block_reason",
            "user_query", "student_code", "course_topic", "assignment_context",
            "should_call_llm", "gold_rationale", "reviewed", "source"}

UNSAFE_CATEGORY_PREFIX = "unsafe_"
SAFE_CATEGORY_PREFIX = "safe_"

# Distribution bands (approximate targets from the spec).
PATCH_MIN, PATCH_MAX = 85, 115
PATCH_SAFE_MIN, PATCH_SAFE_MAX = 45, 65
PATCH_UNSAFE_MIN, PATCH_UNSAFE_MAX = 38, 55
GOLD_TOTAL = 40
GOLD_SAFE_MIN, GOLD_SAFE_MAX = 22, 28
GOLD_UNSAFE_MIN, GOLD_UNSAFE_MAX = 12, 18

errors: list[str] = []
warns: list[str] = []


def err(cond, msg):
    if not cond:
        errors.append(msg)


def warn(cond, msg):
    if not cond:
        warns.append(msg)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def full_key(r: dict) -> str:
    return f"{norm(r.get('user_query',''))}||{norm(r.get('student_code',''))}||" \
           f"{norm(r.get('assignment_context',''))}"


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


# ---- required files exist ----
for p in (PATCH, MERGED, SPLITS, GOLD, V11_MERGED, V11_SPLITS, GOLD_V1, GOLD_V11):
    err(p.exists(), f"required file missing: {p.name}")

patch = load(PATCH)
merged = load(MERGED)
gold = load(GOLD)
v11 = load(V11_MERGED)
gold_v1 = load(GOLD_V1)
gold_v11 = load(GOLD_V11)
splits = json.loads(SPLITS.read_text()) if SPLITS.exists() else {}
v11_splits = json.loads(V11_SPLITS.read_text()) if V11_SPLITS.exists() else {}

# ---- schema / field integrity ----
for name, rows in (("patch", patch), ("merged", merged), ("gold", gold)):
    err(all(REQUIRED.issubset(r) for r in rows), f"{name}: some rows missing required fields")
    err(all(set(r.keys()) == REQUIRED for r in rows), f"{name}: rows have unexpected extra/missing keys")
    err(all(r.get("label") in (0, 1) for r in rows), f"{name}: labels not all in {{0,1}}")
    err(all(r.get("label_name") == ("safe" if r["label"] == 0 else "unsafe") for r in rows),
        f"{name}: label_name inconsistent with label")

for name, rows in (("patch", patch), ("gold", gold)):
    err(all(r.get("reviewed") is True for r in rows), f"{name}: reviewed != True on some rows")
    err(all(r.get("should_call_llm") == (r["label"] == 0) for r in rows),
        f"{name}: should_call_llm inconsistent with label")
    err(all(r.get("block_reason") in (None, "") for r in rows if r["label"] == 0),
        f"{name}: a SAFE row has a non-null block_reason")
    err(all(r.get("block_reason") for r in rows if r["label"] == 1),
        f"{name}: an UNSAFE row has an empty block_reason")
    err(not [r for r in rows if r["label"] == 0 and str(r["category"]).startswith(UNSAFE_CATEGORY_PREFIX)],
        f"{name}: a SAFE row carries an unsafe_ category")
    err(not [r for r in rows if r["label"] == 1 and str(r["category"]).startswith(SAFE_CATEGORY_PREFIX)],
        f"{name}: an UNSAFE row carries a safe_ category")

# ---- unique ids ----
for name, rows in (("patch", patch), ("merged", merged), ("gold", gold)):
    ids = [r["id"] for r in rows]
    err(len(ids) == len(set(ids)),
        f"{name}: duplicate ids {[i for i, c in Counter(ids).items() if c > 1][:5]}")
err(not ({r['id'] for r in patch} & {r['id'] for r in gold}), "patch/gold id-spaces overlap")

# ---- context uniqueness within patch / gold ----
for name, rows in (("patch", patch), ("gold", gold)):
    cids = [r["context_id"] for r in rows]
    err(len(cids) == len(set(cids)),
        f"{name}: duplicate context_ids {[c for c, n in Counter(cids).items() if n > 1][:5]}")

# ---- no context leakage across splits ----
ctx_splits: dict[str, set] = {}
for r in merged:
    s = splits.get(r["context_id"])
    if s:
        ctx_splits.setdefault(r["context_id"], set()).add(s)
multi = {c: s for c, s in ctx_splits.items() if len(s) > 1}
err(not multi, f"context_id in multiple splits: {list(multi)[:5]}")
missing = [r["context_id"] for r in merged if r["context_id"] not in splits]
err(not missing, f"{len(missing)} merged contexts missing from splits")
err(set(splits.values()) <= {"train", "val", "test"},
    f"unexpected split labels: {set(splits.values()) - {'train','val','test'}}")

# ---- no normalized duplicate questions within patch / within gold ----
for name, rows in (("patch", patch), ("gold", gold)):
    nq = [norm(r["user_query"]) for r in rows]
    err(len(nq) == len(set(nq)),
        f"{name}: normalized-duplicate questions "
        f"{[q for q, c in Counter(nq).items() if c > 1][:3]}")
    fk = [full_key(r) for r in rows]
    err(len(fk) == len(set(fk)), f"{name}: duplicate full formatted inputs")

# ---- NO training overlap with either held-out gold file ----
gold_held_norm = {norm(r["user_query"]) for r in gold_v1 + gold_v11}
gold_held_full = {full_key(r) for r in gold_v1 + gold_v11}
patch_norm = {norm(r["user_query"]) for r in patch}
patch_full = {full_key(r) for r in patch}
overlap_norm = patch_norm & gold_held_norm
err(not overlap_norm,
    f"{len(overlap_norm)} patch questions overlap held-out gold (e.g. {list(overlap_norm)[:3]})")
overlap_full = patch_full & gold_held_full
err(not overlap_full, f"{len(overlap_full)} patch full-inputs overlap held-out gold")

# held-out gold rows must NOT appear in the merged training set
gold_held_ids = {r["id"] for r in gold_v1 + gold_v11}
merged_ids = {r["id"] for r in merged}
err(not (gold_held_ids & merged_ids),
    f"{len(gold_held_ids & merged_ids)} held-out gold ids present in merged training set")
merged_full = {full_key(r) for r in merged}
held_full_in_merged = gold_held_full & merged_full
# NOTE: a pre-existing v1.1 row may legitimately coincide with a gold row; flag
# only NEW patch contributions to such overlap.
new_overlap = patch_full & gold_held_full
err(not new_overlap, "v1.1.1 patch introduced a full-input overlap with held-out gold")

# ---- new gold disjoint from merged training (contexts + text) ----
gold_ctx = {r["context_id"] for r in gold}
err(not (gold_ctx & set(splits)), f"{len(gold_ctx & set(splits))} new-gold contexts appear in splits")
err(not (gold_ctx & {r['context_id'] for r in merged}),
    "new-gold contexts appear in merged training data")
gold_norm = {norm(r["user_query"]) for r in gold}
err(not (gold_norm & patch_norm), "new-gold questions overlap the patch")
gold_full = {full_key(r) for r in gold}
err(not (gold_full & merged_full), "new-gold full-inputs overlap merged training")
# new gold also must not duplicate the older held-out gold verbatim
err(not (gold_norm & gold_held_norm), "new-gold questions duplicate older hard-gold verbatim")

# ---- existing v1.1 rows preserved (rows + split assignments) ----
v11_ids = {r["id"] for r in v11}
err(v11_ids <= merged_ids, f"{len(v11_ids - merged_ids)} v1.1 rows missing from merged")
v11_by_id = {r["id"]: r for r in v11}
merged_by_id = {r["id"]: r for r in merged}
changed = [i for i in v11_ids
           if full_key(v11_by_id[i]) != full_key(merged_by_id.get(i, {}))]
err(not changed, f"{len(changed)} preserved v1.1 rows were altered (e.g. {changed[:3]})")
split_changed = [c for c, s in v11_splits.items() if splits.get(c) != s]
err(not split_changed,
    f"{len(split_changed)} v1.1 context split assignments changed (e.g. {split_changed[:3]})")
# merged = exactly v1.1 + patch
err(len(merged) == len(v11) + len(patch),
    f"merged size {len(merged)} != v1.1 {len(v11)} + patch {len(patch)}")

# ---- distribution bands ----
pc = Counter(r["label"] for r in patch)
err(PATCH_MIN <= len(patch) <= PATCH_MAX, f"patch size {len(patch)} outside [{PATCH_MIN},{PATCH_MAX}]")
err(PATCH_SAFE_MIN <= pc[0] <= PATCH_SAFE_MAX, f"patch safe {pc[0]} outside [{PATCH_SAFE_MIN},{PATCH_SAFE_MAX}]")
err(PATCH_UNSAFE_MIN <= pc[1] <= PATCH_UNSAFE_MAX, f"patch unsafe {pc[1]} outside [{PATCH_UNSAFE_MIN},{PATCH_UNSAFE_MAX}]")
gc = Counter(r["label"] for r in gold)
err(len(gold) == GOLD_TOTAL, f"gold total {len(gold)} != {GOLD_TOTAL}")
err(GOLD_SAFE_MIN <= gc[0] <= GOLD_SAFE_MAX, f"gold safe {gc[0]} outside [{GOLD_SAFE_MIN},{GOLD_SAFE_MAX}]")
err(GOLD_UNSAFE_MIN <= gc[1] <= GOLD_UNSAFE_MAX, f"gold unsafe {gc[1]} outside [{GOLD_UNSAFE_MIN},{GOLD_UNSAFE_MAX}]")

# ---------------------------------------------------------------------------
print("=" * 64)
print("INPUT GUARDRAIL v1.1.1 VALIDATION")
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
    print(f"  {name:<42} total={len(rows):>5}  safe={d[0]:>5}  unsafe={d[1]:>5}")


print("\n=== DISTRIBUTIONS ===")
dist(patch, "v1.1.1 targeted patch")
dist(merged, "merged v1.1.1 candidates")
dist(v11, "v1.1 candidates (preserved baseline)")
dist(gold, "supplemental hard gold (held out)")

print("\n=== MERGED ROWS BY SPLIT / LABEL ===")
for sp in ("train", "val", "test"):
    rows = [r for r in merged if splits.get(r["context_id"]) == sp]
    d = Counter(r["label"] for r in rows)
    print(f"  {sp:<6} rows={len(rows):>4}  safe={d[0]:>4}  unsafe={d[1]:>4}  "
          f"contexts={len({r['context_id'] for r in rows})}")
sc = Counter(splits.values())
print(f"  splits ctx: train={sc['train']} val={sc['val']} test={sc['test']} total={len(splits)}")

print("\n=== PATCH BY SPLIT ===")
print(f"  {dict(Counter(splits.get(r['context_id']) for r in patch))}")

print("\n=== PATCH SAFE BY CATEGORY ===")
for k, v in Counter(r["category"] for r in patch if r["label"] == 0).most_common():
    print(f"  {v:>4}  {k}")
print("=== PATCH UNSAFE BY CATEGORY ===")
for k, v in Counter(r["category"] for r in patch if r["label"] == 1).most_common():
    print(f"  {v:>4}  {k}")
print("=== GOLD BY CATEGORY ===")
for k, v in Counter(r["category"] for r in gold).most_common():
    lbl = "safe" if k.startswith("safe_") else "unsafe"
    print(f"  {v:>4}  [{lbl}] {k}")

if errors:
    sys.exit(1)
