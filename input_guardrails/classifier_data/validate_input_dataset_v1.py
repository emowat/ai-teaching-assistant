"""
Validate the v1 input-guardrail classifier dataset.

Runs 15 integrity checks over the candidate dataset, the hard gold set, and
the splits file. Exits non-zero if any check fails. Read-only.

Run from repo root:
    python input_guardrails/classifier_data/validate_input_dataset_v1.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CANDIDATES = HERE / "input_classifier_dataset_v1_candidates.jsonl"
GOLD = HERE / "input_hard_gold_v1.jsonl"
SPLITS = HERE / "splits_input_v1.json"

REQUIRED_FIELDS = {
    "id", "context_id", "label", "label_name", "category", "block_reason",
    "user_query", "student_code", "course_topic", "assignment_context",
    "should_call_llm", "gold_rationale", "reviewed", "source",
}
# Fields that must NOT appear (output-guardrail-only).
FORBIDDEN_FIELDS = {
    "draft_answer", "llm_generation", "answer", "assistant_draft",
    "final_answer", "v2_score", "output_guardrail",
}

UNSAFE_CATS = {"prompt_injection", "full_solution_request",
               "subtle_solution_seeking", "off_topic", "inappropriate_content"}
SAFE_CATS = {"cxx_debugging_question", "concept_explanation", "hint_request",
             "compiler_or_runtime_error_question", "hard_safe_negative"}

CANDIDATE_TARGETS = {
    "prompt_injection": 45, "full_solution_request": 55,
    "subtle_solution_seeking": 30, "off_topic": 20, "inappropriate_content": 10,
    "cxx_debugging_question": 40, "concept_explanation": 35, "hint_request": 30,
    "compiler_or_runtime_error_question": 20, "hard_safe_negative": 45,
}

# Heuristic: a plausible C++ snippet shows at least one of these signals.
_CPP_SIGNAL = re.compile(
    r"(#include|std::|int main|->|\bclass\b|\bstruct\b|nullptr|cout|cin|"
    r"\bvector\b|\breturn\b|\bfor\b|\bwhile\b|\bif\b|new |delete )")
_PLACEHOLDER = re.compile(r"TODO_ONLY|FIXME_PLACEHOLDER|<placeholder>|lorem ipsum", re.I)

# --- check 16: query-topic alignment for SAFE rows ---------------------------
# Distinctive topic markers that, if present in a SAFE query, imply a specific
# topic family. A safe row is flagged as MISALIGNED if its query carries a
# marker for a family that the code context clearly does NOT belong to.
# (Unsafe rows are exempt: "ignore your rules" is unsafe regardless of code.)
TOPIC_MARKERS = {
    "recursion": ["recursion", "recursive", "base case", "fibonacci", "factorial"],
    "pointer": ["pointer", "dereferenc", "null pointer", "dangling"],
    "vector": ["vector", "push_back"],
    "matrix": ["matrix", "matrices"],
    "file_io": ["file", "ifstream", "getline", "stream open"],
    "class": ["destructor", "constructor", "copy constructor", "virtual", "member", "class"],
    "string": ["string", "substr", "palindrome", "char array", "null terminator"],
    "sorting": ["bubble sort", "sort "],
    "searching": ["binary search"],
    "loop": ["loop", "while loop", "for loop", "iteration"],
}


def _context_families(course_topic: str, code: str) -> set:
    """Coarse family set a context plausibly belongs to (from topic + code)."""
    blob = (course_topic + " " + code).lower()
    fams = set()
    for fam, kws in TOPIC_MARKERS.items():
        if any(k in blob for k in kws):
            fams.add(fam)
    return fams


def _query_families(query: str) -> set:
    q = query.lower()
    fams = set()
    for fam, kws in TOPIC_MARKERS.items():
        if any(k in q for k in kws):
            fams.add(fam)
    return fams


def _load(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def main():
    errors = []
    warnings = []

    def check(cond, msg):
        if not cond:
            errors.append(msg)

    # ---- load (check 1: valid JSONL) ----
    try:
        cand = _load(CANDIDATES)
        gold = _load(GOLD)
        splits = json.loads(SPLITS.read_text())
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] check 1 — JSONL/JSON parse error: {e}")
        sys.exit(1)
    print(f"[ok]  check 1  — JSONL valid (candidates={len(cand)}, gold={len(gold)})")

    all_rows = cand + gold

    # ---- check 2: required fields ----
    bad = [r.get("id", "?") for r in all_rows if set(r) - {"id"} | {"id"} and not REQUIRED_FIELDS.issubset(r)]
    check(not bad, f"check 2 — rows missing required fields: {bad[:5]}")
    if not bad:
        print("[ok]  check 2  — all required fields present")

    # ---- check 3: label 0/1 ----
    check(all(r["label"] in (0, 1) for r in all_rows), "check 3 — label not in {0,1}")
    # ---- check 4: label_name matches label ----
    check(all((r["label"] == 1) == (r["label_name"] == "unsafe") for r in all_rows),
          "check 4 — label_name does not match label")
    # ---- check 5: unsafe rows have block_reason ----
    check(all(r["block_reason"] for r in all_rows if r["label"] == 1),
          "check 5 — an unsafe row has empty block_reason")
    # ---- check 6: safe rows have block_reason null ----
    check(all(r["block_reason"] is None for r in all_rows if r["label"] == 0),
          "check 6 — a safe row has non-null block_reason")
    # ---- check 7: should_call_llm matches label ----
    check(all(r["should_call_llm"] == (r["label"] == 0) for r in all_rows),
          "check 7 — should_call_llm inconsistent with label")
    for n in (3, 4, 5, 6, 7):
        if not any(e.startswith(f"check {n} ") for e in errors):
            print(f"[ok]  check {n}  — passed")

    # ---- check 8: no duplicate ids ----
    ids = [r["id"] for r in all_rows]
    check(len(ids) == len(set(ids)), "check 8 — duplicate ids present")
    # ---- check 9: no duplicate (user_query, student_code) ----
    pairs = [(r["user_query"], r["student_code"]) for r in all_rows]
    dups = [p for p, c in Counter(pairs).items() if c > 1]
    check(not dups, f"check 9 — {len(dups)} duplicate (user_query, student_code) pairs")
    for n in (8, 9):
        if not any(e.startswith(f"check {n} ") for e in errors):
            print(f"[ok]  check {n}  — passed")

    # ---- check 10: category counts match candidate targets ----
    cand_cats = Counter(r["category"] for r in cand)
    mismatch = {c: (cand_cats.get(c, 0), t) for c, t in CANDIDATE_TARGETS.items() if cand_cats.get(c, 0) != t}
    check(not mismatch, f"check 10 — candidate category counts off: {mismatch}")
    if not mismatch:
        print("[ok]  check 10 — candidate category distribution matches targets")

    # ---- check 11: candidate vs gold context_id disjoint ----
    cand_ctx = {r["context_id"] for r in cand}
    gold_ctx = {r["context_id"] for r in gold}
    overlap = cand_ctx & gold_ctx
    check(not overlap, f"check 11 — candidate/gold context_id overlap: {overlap}")
    if not overlap:
        print("[ok]  check 11 — candidate & gold contexts disjoint")

    # ---- check 12: splits by context_id, no leakage ----
    # every candidate context has a split; gold contexts not in splits
    missing = cand_ctx - set(splits)
    check(not missing, f"check 12 — candidate contexts missing from splits: {missing}")
    gold_in_splits = gold_ctx & set(splits)
    check(not gold_in_splits, f"check 12 — gold contexts leaked into splits: {gold_in_splits}")
    # a context maps to exactly one split (dict guarantees) AND no row's context spans splits
    row_ctx_split = {}
    leak = False
    for r in cand:
        s = splits.get(r["context_id"])
        prev = row_ctx_split.setdefault(r["context_id"], s)
        if prev != s:
            leak = True
    check(not leak, "check 12 — a context_id maps to >1 split")
    if not (missing or gold_in_splits or leak):
        print("[ok]  check 12 — splits are context-clean, no leakage")

    # ---- check 13: no forbidden output-guardrail fields ----
    present_forbidden = set()
    for r in all_rows:
        present_forbidden |= (set(r) & FORBIDDEN_FIELDS)
    check(not present_forbidden, f"check 13 — forbidden output-guardrail fields present: {present_forbidden}")
    if not present_forbidden:
        print("[ok]  check 13 — no output-guardrail-only fields")

    # ---- check 14: no placeholder / non-C++ code ----
    bad_code = []
    for r in all_rows:
        code = r["student_code"]
        if _PLACEHOLDER.search(code) or not _CPP_SIGNAL.search(code):
            bad_code.append(r["id"])
    check(not bad_code, f"check 14 — placeholder/non-C++ student_code: {bad_code[:5]}")
    if not bad_code:
        print("[ok]  check 14 — all student_code looks like plausible C++")

    # ---- check 16: SAFE rows — query topic must align with code context ----
    # Map fine families to broad DOMAINS; related concepts (pointer/class/memory;
    # vector/searching/sorting/loop) share a domain so legitimately-overlapping
    # questions are not falsely flagged. Flag only when the query's domains and
    # the context's domains are entirely disjoint (the real v1 bug: e.g. a matrix
    # question on file-IO code).
    # Broad concept domains. Iteration/algorithm/container families all share
    # "logic" (loops legitimately iterate vectors, binary search uses a vector,
    # etc.). memory / text / io are kept distinct. This still catches the real
    # v1 mismatches (matrix question on dynamic-memory code -> logic vs memory;
    # virtual-function question on loop code -> memory vs logic).
    fam_domain = {
        "recursion": "logic", "loop": "logic", "sorting": "logic",
        "searching": "logic", "vector": "logic", "matrix": "logic",
        "string": "text", "file_io": "io", "pointer": "memory",
        "class": "memory",
    }

    def _domains(fams):
        return {fam_domain.get(f, f) for f in fams}

    misaligned = []
    for r in all_rows:
        if r["label"] != 0:
            continue
        qfams = _query_families(r["user_query"])
        if not qfams:
            continue  # generic query (e.g. "give me a hint") — nothing to align
        cfams = _context_families(r["course_topic"], r["student_code"])
        if not cfams:
            continue
        if _domains(qfams).isdisjoint(_domains(cfams)):
            misaligned.append((r["id"], sorted(qfams), sorted(cfams), r["user_query"][:60]))
    check(not misaligned, f"check 16 — {len(misaligned)} safe rows with query/topic mismatch")
    if not misaligned:
        print("[ok]  check 16 — safe-row query/topic alignment OK")
    else:
        for mid, qf, cf, q in misaligned[:8]:
            print(f"        MISALIGN {mid}: query{qf} vs context{cf} :: {q}")

    # ---- check 15/report ----
    print("\n=== Validation report ===")
    print(f"candidates: {len(cand)} | labels {dict(Counter(r['label'] for r in cand))}")
    print(f"gold:       {len(gold)} | labels {dict(Counter(r['label'] for r in gold))}")
    print(f"splits:     {dict(Counter(splits.values()))} over {len(splits)} contexts")
    print(f"reviewed=false rows: {sum(1 for r in all_rows if r['reviewed'] is False)}/{len(all_rows)}")

    if errors:
        print(f"\n❌ {len(errors)} CHECK(S) FAILED:")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)
    print("\n✅ All 16 checks passed.")


if __name__ == "__main__":
    main()
