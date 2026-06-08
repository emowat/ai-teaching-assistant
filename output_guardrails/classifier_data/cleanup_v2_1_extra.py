"""Cleanup pass: rebuild classifier_dataset_v2_1_extra.jsonl from matched
problem units so every assistant_draft addresses its own student_code.

Why a rebuild instead of in-place edits: the original generator cycled
GENERIC drafts over RANDOM student_code, so drafts rarely matched the
code, 45 rows shared drafts, and the "normal_cpp" pool contained
non-C++ junk ([None - Study Assist Active], an HTML form, placeholder
"buggy snippet here"). v2_1's goal is subtle SOLUTION leakage on the
student's ACTUAL code, so draft<->code relevance is mandatory.

This reads problem_units_v2_1.json (hand-authored, each unit = one real
C++ bug + drafts written for THAT bug) and emits the target distribution:

    unfenced_inline_code_leakage  30  unsafe (label 1)
    exact_patch_changed_line      25  unsafe (label 1)
    pseudocode_solution           25  unsafe (label 1)
    safe_gdb_debugging_guidance   25  safe   (label 0)
    safe_concept_explanation      15  safe   (label 0)   [Socratic hints]
                                 ---
                                 120  rows (80 unsafe / 40 safe)

All rows stay reviewed=false, source="llm_generated_v2_1", with
reviewed_by/review_notes preserved. Writes ONLY
classifier_dataset_v2_1_extra.jsonl. Never touches the base dataset,
gold set, or splits.

Run from ai-teaching-assistant/:
    python -m output_guardrails.classifier_data.cleanup_v2_1_extra
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

from output_guardrails.classifier_data.generate_classifier_dataset import (
    context_id_for,
)

SEED = 4211
DATA_DIR = PKG_ROOT / "classifier_data"
UNITS_PATH = DATA_DIR / "problem_units_v2_1.json"
OUT_EXTRA = DATA_DIR / "classifier_dataset_v2_1_extra.jsonl"

# kind -> (violation_type, label, target_count)
KIND_PLAN = {
    "unfenced_inline": ("unfenced_inline_code_leakage", 1, 30),
    "exact_patch":     ("exact_patch_changed_line",     1, 25),
    "pseudocode":      ("pseudocode_solution",          1, 25),
    "gdb":             ("safe_gdb_debugging_guidance",  0, 25),
    "socratic":        ("safe_concept_explanation",     0, 15),
}


def make_row(*, scenario_id, user_query, student_code, assistant_draft,
             label, violation_type):
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
        "topic_style": "normal_cpp",
        "uses_placeholder": False,
        "reviewed": False,
        "reviewed_by": "",
        "review_notes": "",
    }


def build_kind(rng, units, kind):
    """Produce target_count rows for one kind, spreading across units and
    using each unit's draft variants before repeating, to minimize
    duplicate assistant_draft values.
    """
    violation_type, label, target = KIND_PLAN[kind]

    # Flatten (unit, draft_variant) pairs, variant-major so we exhaust the
    # distinct wordings across units before any draft repeats.
    pairs = []
    max_variants = max(len(u[kind]) for u in units)
    for v_idx in range(max_variants):
        for u in units:
            variants = u[kind]
            if v_idx < len(variants):
                pairs.append((u, variants[v_idx]))

    rows = []
    seen_drafts = set()
    # First pass: only unique drafts.
    for u, draft in pairs:
        if len(rows) >= target:
            break
        if draft in seen_drafts:
            continue
        seen_drafts.add(draft)
        rows.append(make_row(
            scenario_id=f"v2_1__{violation_type}__{u['uid']}__{len(rows):03d}",
            user_query=u["user_query"],
            student_code=u["student_code"],
            assistant_draft=draft,
            label=label,
            violation_type=violation_type,
        ))

    # Second pass (only if we ran out of unique drafts): allow reuse,
    # cycling pairs so repeats are spread evenly.
    i = 0
    while len(rows) < target:
        u, draft = pairs[i % len(pairs)]
        i += 1
        rows.append(make_row(
            scenario_id=f"v2_1__{violation_type}__{u['uid']}__{len(rows):03d}",
            user_query=u["user_query"],
            student_code=u["student_code"],
            assistant_draft=draft,
            label=label,
            violation_type=violation_type,
        ))
    return rows


def main():
    rng = random.Random(SEED)
    units = json.loads(UNITS_PATH.read_text())["units"]

    all_rows = []
    for kind in KIND_PLAN:
        all_rows.extend(build_kind(rng, units, kind))

    rng.shuffle(all_rows)
    for i, r in enumerate(all_rows):
        r["id"] = f"v2_1_{i:06d}"

    with OUT_EXTRA.open("w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")

    print(f"wrote {len(all_rows)} rows -> {OUT_EXTRA}")
    print(f"  labels: {dict(Counter(r['label'] for r in all_rows))} (0=safe,1=unsafe)")
    for k, v in Counter(r["violation_type"] for r in all_rows).most_common():
        print(f"    {k:<32s} {v}")
    drafts = Counter(r["assistant_draft"] for r in all_rows)
    print(f"  distinct drafts: {len(drafts)} of {len(all_rows)}; reused >1x: {sum(1 for c in drafts.values() if c>1)}")


if __name__ == "__main__":
    main()
