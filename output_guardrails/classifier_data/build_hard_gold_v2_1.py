"""Build hard_gold_test_set_v2_1.jsonl from hard_gold_units_v2_1.json.

This is the v2_1 regression benchmark: it measures whether codebert_v2_1
improves over codebert_v2_0 on the new target categories. Every row is
hand-authored, self-labeled, and human-approved (reviewed=true).

Schema matches the rest of the classifier data plus the v2_1 review
fields. source="hard_gold_v2_1". Writes ONLY
hard_gold_test_set_v2_1.jsonl. Never touches base dataset, gold set,
splits, or the v2_1 extra training file.

Run from ai-teaching-assistant/:
    python -m output_guardrails.classifier_data.build_hard_gold_v2_1
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from output_guardrails.classifier_data.generate_classifier_dataset import (
    context_id_for,
)

DATA_DIR = PKG_ROOT / "classifier_data"
UNITS_PATH = DATA_DIR / "hard_gold_units_v2_1.json"
OUT_PATH = DATA_DIR / "hard_gold_test_set_v2_1.jsonl"

REVIEWER = "human_review_approved_by_ligong"
REVIEW_NOTE = "Hand-authored hard-gold row for v2_1 regression benchmark."


def main():
    units = json.loads(UNITS_PATH.read_text())["rows"]
    rows = []
    for i, u in enumerate(units):
        rows.append({
            "scenario_id": f"hard_gold_v2_1__{u['_vt']}__{i:03d}",
            "context_id": context_id_for(u["user_query"], u["student_code"]),
            "user_query": u["user_query"],
            "student_code": u["student_code"],
            "assistant_draft": u["assistant_draft"],
            "label": u["_label"],
            "violation_type": u["_vt"],
            "source": "hard_gold_v2_1",
            "label_source": "human_authored",
            "topic_style": "normal_cpp",
            "uses_placeholder": False,
            "reviewed": True,
            "reviewed_by": REVIEWER,
            "review_notes": REVIEW_NOTE,
            "id": f"hardgold_v2_1_{i:06d}",
        })

    with OUT_PATH.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"wrote {len(rows)} rows -> {OUT_PATH}")
    print(f"  labels: {dict(Counter(r['label'] for r in rows))} (0=safe,1=unsafe)")
    for k, v in Counter(r["violation_type"] for r in rows).most_common():
        print(f"    {k:<32s} {v}")


if __name__ == "__main__":
    main()
