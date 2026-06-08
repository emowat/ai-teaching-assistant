"""Generate v2_1 hard-case CANDIDATE rows for the V2 guardrail retrain.

Phase A of the codebert_v2_1 plan. Produces UNREVIEWED candidates only:
every row is written with reviewed=false and empty reviewed_by/review_notes.
A human must confirm label + violation_type against
templates/reviewer_rubric.md and flip reviewed=true before any row is
eligible for the merged training set (plan safeguard #5).

Scope (top-3 unsafe blind spots + safe hard-negatives):
    unfenced_inline_code_leakage   30  unsafe (label 1)
    exact_patch_changed_line       25  unsafe (label 1)
    pseudocode_solution            25  unsafe (label 1)
    safe_gdb_debugging_guidance    25  safe   (label 0)
    safe_socratic_concept (hard)   15  safe   (label 0)
                                  ---
                                  120  rows (80 unsafe / 40 safe)

student_code provenance: the planned source
synthetic-transcripts/synthetic_c_plus_plus_dataset.jsonl NO LONGER EXISTS,
so we draw realistic, bait-free student_code from the existing
classifier_dataset.jsonl (topic_style == "normal_cpp"). Each candidate
pairs a sampled student_code with a draft from category_drafts_v2_1.json.

This generator is deterministic (fixed SEED, round-robin draft cycling)
and makes no LLM API calls at runtime — the "LLM-generated" drafts were
authored offline and curated into category_drafts_v2_1.json. It writes
ONLY classifier_dataset_v2_1_extra.jsonl. It never touches
classifier_dataset.jsonl, gold_test_set.jsonl, or splits.json.

Run from ai-teaching-assistant/:
    python -m output_guardrails.classifier_data.generate_v2_1_candidates
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from itertools import cycle
from pathlib import Path

# PKG_ROOT  = .../ai-teaching-assistant/output_guardrails
# REPO_ROOT = .../ai-teaching-assistant
PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

# Reuse the EXACT context_id hashing the v2_0 generator used so isolation
# checks compare apples to apples.
from output_guardrails.classifier_data.generate_classifier_dataset import (
    context_id_for,
)

SEED = 4201
random.seed(SEED)

DATA_DIR = PKG_ROOT / "classifier_data"
TEMPLATES_DIR = DATA_DIR / "templates"

BASE_DATASET = DATA_DIR / "classifier_dataset.jsonl"
GOLD_SET = DATA_DIR / "gold_test_set.jsonl"
DRAFTS_V2_1 = TEMPLATES_DIR / "category_drafts_v2_1.json"

OUT_EXTRA = DATA_DIR / "classifier_dataset_v2_1_extra.jsonl"

# (draft_pool_key, violation_type, label, count). topic_style/user_query
# are assigned per category below.
CATEGORY_PLAN = [
    ("unfenced_inline_code_leakage_drafts",        "unfenced_inline_code_leakage", 1, 30),
    ("exact_patch_changed_line_drafts",            "exact_patch_changed_line",     1, 25),
    ("pseudocode_solution_drafts",                 "pseudocode_solution",          1, 25),
    ("safe_gdb_debugging_guidance_drafts",         "safe_gdb_debugging_guidance",  0, 25),
    ("safe_socratic_concept_hard_negative_drafts", "safe_concept_explanation",     0, 15),
]

# Per-category user_query pools. Kept generic so the (query, code) pair is
# plausible. The unsafe categories use "fix it" style prompts that an LLM
# might over-comply with; the safe categories use the same so the model
# must learn the distinction from the DRAFT, not the query.
USER_QUERIES = {
    "unfenced_inline_code_leakage": [
        "How do I fix this?",
        "Can you just tell me what to write here?",
        "What should this function actually be?",
        "I'm stuck, what's the correct code?",
    ],
    "exact_patch_changed_line": [
        "Which line is wrong?",
        "What exactly do I change?",
        "Just tell me the line to edit.",
        "Where's the bug and what's the fix?",
    ],
    "pseudocode_solution": [
        "What's the algorithm I need?",
        "Can you outline the whole approach?",
        "How do I solve this assignment?",
        "Walk me through the full solution.",
    ],
    "safe_gdb_debugging_guidance": [
        "Why does this segfault?",
        "How do I figure out where it crashes?",
        "It's giving the wrong answer, how do I debug it?",
        "How can I inspect what's happening at runtime?",
    ],
    "safe_concept_explanation": [
        "I don't understand why this is wrong.",
        "Can you explain the concept here?",
        "What's the difference I'm missing?",
        "Why does it behave like this?",
    ],
}


def load_jsonl(path: Path) -> list:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def make_candidate_row(*, scenario_id, user_query, student_code,
                       assistant_draft, label, violation_type, topic_style):
    """v2_1 candidate row. Mirrors the v2_0 make_row() schema and adds the
    review-tracking fields. reviewed is ALWAYS false here (safeguard #5).
    """
    return {
        "scenario_id": scenario_id,
        "context_id": context_id_for(user_query, student_code),
        "user_query": user_query,
        "student_code": student_code,
        "assistant_draft": assistant_draft,
        "label": label,
        "violation_type": violation_type,
        "source": "llm_generated_v2_1",
        "label_source": "llm_candidate_unreviewed",
        "topic_style": topic_style,
        "uses_placeholder": False,
        "reviewed": False,
        "reviewed_by": "",
        "review_notes": "",
    }


def main():
    rng = random.Random(SEED)

    base_rows = load_jsonl(BASE_DATASET)
    drafts = json.loads(DRAFTS_V2_1.read_text())

    # Realistic, bait-free student_code pool from the existing dataset.
    code_pool = sorted({
        r["student_code"]
        for r in base_rows
        if r.get("topic_style") == "normal_cpp" and r["student_code"].strip()
    })
    if not code_pool:
        print("[error] no normal_cpp student_code found in base dataset")
        return
    rng.shuffle(code_pool)
    code_cycler = cycle(code_pool)

    rows = []
    for pool_key, violation_type, label, count in CATEGORY_PLAN:
        pool = drafts[pool_key]
        draft_cycler = cycle(pool)
        # Shuffle a private copy of the query list per category.
        queries = list(USER_QUERIES[violation_type])
        rng.shuffle(queries)
        query_cycler = cycle(queries)
        topic_style = "normal_cpp"

        for i in range(count):
            rows.append(make_candidate_row(
                scenario_id=f"v2_1__{violation_type}__{i:03d}",
                user_query=next(query_cycler),
                student_code=next(code_cycler),
                assistant_draft=next(draft_cycler),
                label=label,
                violation_type=violation_type,
                topic_style=topic_style,
            ))

    rng.shuffle(rows)
    for i, r in enumerate(rows):
        r["id"] = f"v2_1_{i:06d}"

    with OUT_EXTRA.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    # Console summary.
    print(f"wrote {len(rows)} candidate rows -> {OUT_EXTRA}")
    print(f"  labels: {dict(Counter(r['label'] for r in rows))} (0=safe,1=unsafe)")
    print("  by violation_type:")
    for k, v in Counter(r["violation_type"] for r in rows).most_common():
        print(f"    {k:<32s} {v}")
    print(f"  reviewed=true rows: {sum(1 for r in rows if r['reviewed'])} (must be 0 — all pre-review)")


if __name__ == "__main__":
    main()
