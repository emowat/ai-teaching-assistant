"""Validate the INPUT guardrail v1.1 hard-negative patch + rebuilt artifacts.

Run: python input_guardrails/classifier_data/validate_input_v1_1.py

Checks the patch, the rebuilt merged candidate corpus, the rebuilt splits, and
the supplemental live-false-positive hard gold. Exits non-zero on any hard
failure. Mirrors the intent of validate_input_dataset_v1.py and the v2.5
validators, adapted to the v1.1 targets and the type/debug FP theme.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PATCH = HERE / "input_guardrail_v1_1_hard_negative_patch.jsonl"
MERGED = HERE / "input_classifier_dataset_v1_1_candidates.jsonl"
SPLITS = HERE / "splits_input_v1_1.json"
GOLD = HERE / "input_hard_gold_v1_1_live_false_positive.jsonl"
BASE = HERE / "input_classifier_dataset_v1_candidates.jsonl"

REQUIRED = {"id", "context_id", "label", "label_name", "category", "block_reason",
            "user_query", "student_code", "course_topic", "assignment_context",
            "should_call_llm", "gold_rationale", "reviewed", "source"}

# The two exact live false positives that MUST be present as SAFE in the patch.
LIVE_FP_1 = "oh ok - it failed on the first entry"
LIVE_FP_2 = "Can I use u_char as a small integer here?"

# Target bands.
PATCH_MIN, PATCH_MAX = 220, 320
PATCH_SAFE_MIN, PATCH_SAFE_MAX = 150, 220
PATCH_UNSAFE_MIN, PATCH_UNSAFE_MAX = 70, 100
GOLD_TOTAL, GOLD_SAFE, GOLD_UNSAFE = 60, 40, 20

# Categories that mean "unsafe" — a SAFE row must never carry one of these,
# and an UNSAFE row must carry an unsafe category (guards mislabeling).
UNSAFE_CATEGORIES = {
    "unsafe_full_solution_request", "unsafe_reference_implementation_request",
    "unsafe_disclaimer_solution_request", "unsafe_paste_code_request",
    "unsafe_prompt_injection", "unsafe_bypass_guardrail",
    "unsafe_answer_seeking_disguised_as_hint", "unsafe_completion_request",
}
SAFE_CATEGORY_PREFIX = "safe_"

# Solution-seeking / injection phrasing that must NOT appear in a SAFE row's
# query (would indicate an unsafe example mislabeled safe).
UNSAFE_QUERY_MARKERS = [
    "full solution", "full code", "full program", "full corrected",
    "complete implementation", "entire function", "entire code",
    "whole program", "whole solution", "whole implementation", "whole fix",
    "complete answer", "complete program", "complete code", "complete corrected",
    "complete substr", "complete version", "complete function", "final code",
    "final answer", "final function", "final version",
    "reference implementation", "reference solution", "reference version",
    "reference code", "model answer", "sample solution", "canonical implementation",
    "official reference", "working reference", "working code", "working function",
    "working loop", "corrected code", "corrected loop", "corrected version",
    "paste the", "just paste", "output only", "give me the code",
    "provide the code", "just give the code", "just provide", "the code block",
    "show the full", "show me the reference", "show the answer", "show the whole",
    "solve the whole", "solve this", "fill in all", "finish the whole",
    "ignore the tutoring", "ignore previous", "ignore prior", "ignore your",
    "bypass the guardrail", "bypass your", "disable the tutoring", "turn off the guardrail",
    "get around your", "circumvent the", "you are no longer", "pretend you are allowed",
    "pretend the guardrail", "pretend the honor", "forget your rules",
    "act as an unrestricted", "exact code i should submit", "exact full code",
    "exact lines", "entire working", "just show the answer", "just the answer",
    "output the solution", "hint the full", "so i can paste",
]
# Benign type/debug markers that must NOT flip a genuinely-safe question to
# unsafe. Used to sanity-check that unsafe rows aren't just type questions.
SAFE_TYPE_MARKERS = ["u_char", "unsigned char", "uint8_t", "size_t", "char"]

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


def key(r: dict) -> tuple:
    return (r.get("user_query", "").strip(),
            r.get("student_code", "").strip(),
            r.get("assignment_context", "").strip())


patch = load(PATCH)
merged = load(MERGED)
gold = load(GOLD)
base = load(BASE)
splits = json.loads(SPLITS.read_text()) if SPLITS.exists() else {}
if not SPLITS.exists():
    errors.append("MISSING FILE: splits_input_v1_1.json")

all_rows = patch + merged + gold

# --- schema / field integrity --------------------------------------------
err(all(REQUIRED.issubset(r) for r in all_rows), "some rows missing required fields")
err(all(r.get("label") in (0, 1) for r in all_rows), "labels not all in {0,1}")
err(all(r.get("label_name") == ("safe" if r.get("label") == 0 else "unsafe")
        for r in all_rows), "label_name inconsistent with label")
err(all(r.get("reviewed") is True for r in patch + gold),
    "some patch/gold rows have reviewed != True")
# should_call_llm must mirror the label (safe -> call LLM; unsafe -> don't)
err(all(r.get("should_call_llm") == (r.get("label") == 0) for r in patch + gold),
    "should_call_llm inconsistent with label in patch/gold")
# safe rows have null block_reason; unsafe rows have a non-null block_reason
err(all(r.get("block_reason") in (None, "") for r in patch + gold if r["label"] == 0),
    "a SAFE row has a non-null block_reason")
err(all(r.get("block_reason") for r in patch + gold if r["label"] == 1),
    "an UNSAFE row has an empty block_reason")

# --- duplicate ids / context_ids ------------------------------------------
# Check id-uniqueness WITHIN each file (patch rows also live inside merged, so
# checking the concatenation would double-count them). Also verify patch and
# gold id-spaces don't collide.
for name, rows in (("patch", patch), ("merged", merged), ("gold", gold)):
    file_ids = [r["id"] for r in rows]
    err(len(file_ids) == len(set(file_ids)),
        f"duplicate ids in {name}: "
        f"{[i for i, c in Counter(file_ids).items() if c > 1][:5]}")
err(not ({r['id'] for r in patch} & {r['id'] for r in gold}),
    "patch and gold id-spaces overlap")
# context_ids unique within patch and within gold
for name, rows in (("patch", patch), ("gold", gold)):
    cids = [r["context_id"] for r in rows]
    err(len(cids) == len(set(cids)),
        f"duplicate context_ids in {name}: "
        f"{[c for c, n in Counter(cids).items() if n > 1][:5]}")

# --- split leakage: each context in exactly one split ---------------------
merged_ctx_splits: dict[str, set] = {}
for r in merged:
    s = splits.get(r["context_id"])
    if s:
        merged_ctx_splits.setdefault(r["context_id"], set()).add(s)
multi = {c: s for c, s in merged_ctx_splits.items() if len(s) > 1}
err(not multi, f"context_id in multiple splits: {list(multi)[:5]}")
missing_ctx = [r["context_id"] for r in merged if r["context_id"] not in splits]
err(not missing_ctx, f"{len(missing_ctx)} merged contexts missing from splits")
err(set(splits.values()) <= {"train", "val", "test"},
    f"unexpected split labels: {set(splits.values()) - {'train','val','test'}}")

# --- hard gold disjoint from training -------------------------------------
merged_ctx = {r["context_id"] for r in merged}
gold_ctx = {r["context_id"] for r in gold}
err(not (gold_ctx & merged_ctx),
    f"{len(gold_ctx & merged_ctx)} gold contexts also in merged training data")
err(not (gold_ctx & set(splits)),
    f"{len(gold_ctx & set(splits))} gold contexts appear in the splits map")
merged_keys = {key(r) for r in merged}
gold_dupe = [key(r) for r in gold if key(r) in merged_keys]
err(not gold_dupe,
    f"{len(gold_dupe)} gold rows share (user_query, student_code, "
    f"assignment_context) with merged training data (e.g. {gold_dupe[:2]})")

# --- no exact text duplicates within patch / within merged ----------------
pkeys = [key(r) for r in patch]
err(len(pkeys) == len(set(pkeys)),
    f"{len(pkeys) - len(set(pkeys))} exact-duplicate (query,code,ctx) rows in patch")
mkeys = [key(r) for r in merged]
warn(len(mkeys) == len(set(mkeys)),
     f"{len(mkeys) - len(set(mkeys))} exact-duplicate rows in merged (dedup expected)")

# --- merged is a superset of base (base preserved) ------------------------
base_keys = {key(r) for r in base}
err(base_keys <= merged_keys, "merged dataset does not preserve all base rows")

# --- count / balance bands ------------------------------------------------
pc = Counter(r["label"] for r in patch)
err(PATCH_MIN <= len(patch) <= PATCH_MAX,
    f"patch size {len(patch)} outside [{PATCH_MIN},{PATCH_MAX}]")
err(PATCH_SAFE_MIN <= pc[0] <= PATCH_SAFE_MAX,
    f"patch safe {pc[0]} outside [{PATCH_SAFE_MIN},{PATCH_SAFE_MAX}]")
err(PATCH_UNSAFE_MIN <= pc[1] <= PATCH_UNSAFE_MAX,
    f"patch unsafe {pc[1]} outside [{PATCH_UNSAFE_MIN},{PATCH_UNSAFE_MAX}]")
gc = Counter(r["label"] for r in gold)
err(len(gold) == GOLD_TOTAL, f"gold total {len(gold)} != {GOLD_TOTAL}")
err(gc[0] == GOLD_SAFE, f"gold safe {gc[0]} != {GOLD_SAFE}")
err(gc[1] == GOLD_UNSAFE, f"gold unsafe {gc[1]} != {GOLD_UNSAFE}")

# --- exact live false positives present as SAFE in the patch --------------
patch_safe_qs = {r["user_query"] for r in patch if r["label"] == 0}
err(LIVE_FP_1 in patch_safe_qs, f"live FP #1 not present as SAFE in patch: {LIVE_FP_1!r}")
err(LIVE_FP_2 in patch_safe_qs, f"live FP #2 not present as SAFE in patch: {LIVE_FP_2!r}")

# --- forbidden mislabeling: safe rows must not be unsafe, and vice versa ---
for name, rows in (("patch", patch), ("gold", gold)):
    safe_with_unsafe_cat = [r for r in rows
                            if r["label"] == 0 and r["category"] in UNSAFE_CATEGORIES]
    err(not safe_with_unsafe_cat,
        f"{len(safe_with_unsafe_cat)} SAFE {name} rows carry an unsafe category")
    unsafe_with_safe_cat = [r for r in rows
                            if r["label"] == 1 and str(r["category"]).startswith(SAFE_CATEGORY_PREFIX)]
    err(not unsafe_with_safe_cat,
        f"{len(unsafe_with_safe_cat)} UNSAFE {name} rows carry a safe_ category")
    # safe query must not contain solution-seeking / injection markers
    safe_leak = [r for r in rows if r["label"] == 0
                 and any(m in r["user_query"].lower() for m in UNSAFE_QUERY_MARKERS)]
    err(not safe_leak,
        f"{len(safe_leak)} SAFE {name} rows contain solution-seeking/injection "
        f"phrasing (e.g. {[r['user_query'] for r in safe_leak[:2]]})")
    # unsafe query should read as solution-seeking/injection, not a bare type Q
    unsafe_bare = [r for r in rows if r["label"] == 1
                   and not any(m in r["user_query"].lower() for m in UNSAFE_QUERY_MARKERS)
                   and "solve" not in r["user_query"].lower()
                   and "complete" not in r["user_query"].lower()
                   and "circumvent" not in r["user_query"].lower()
                   and "get around" not in r["user_query"].lower()
                   and "forget your" not in r["user_query"].lower()]
    warn(not unsafe_bare,
         f"{len(unsafe_bare)} UNSAFE {name} rows lack an obvious solution/injection "
         f"marker (review: {[r['user_query'] for r in unsafe_bare[:2]]})")

# --- live-FP contexts should be in train (teach the fix) ------------------
for q in (LIVE_FP_1, LIVE_FP_2):
    ctxs = [r["context_id"] for r in patch if r["user_query"] == q and r["label"] == 0]
    for c in ctxs:
        warn(splits.get(c) == "train",
             f"live-FP context {c} for {q!r} is in split {splits.get(c)!r}, not train")

# ---------------------------------------------------------------------------
print("=" * 64)
print("INPUT GUARDRAIL v1.1 VALIDATION")
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
dist(patch, "v1.1 patch (hard negatives + contrasts)")
dist(merged, "merged v1.1 candidates (base + patch)")
dist(base, "base v1 candidates (for reference)")
dist(gold, "supplemental hard gold (live FP, held out)")

print("\n=== SPLITS (merged rows by split) ===")
by = Counter(splits.get(r["context_id"]) for r in merged)
sc = Counter(splits.values())
print(f"  contexts: train={sc['train']} val={sc['val']} test={sc['test']} total={len(splits)}")
print(f"  rows:     train={by['train']} val={by['val']} test={by['test']}")

print("\n=== PATCH SAFE BY CATEGORY ===")
for k, v in Counter(r["category"] for r in patch if r["label"] == 0).most_common():
    print(f"  {v:>4}  {k}")
print("=== PATCH UNSAFE BY CATEGORY ===")
for k, v in Counter(r["category"] for r in patch if r["label"] == 1).most_common():
    print(f"  {v:>4}  {k}")

if errors:
    sys.exit(1)
