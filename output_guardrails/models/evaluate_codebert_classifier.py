"""Evaluate a trained V2 CodeBERT checkpoint.

Reports the metrics from plan section V2.10:
  - accuracy / precision / recall / F1
  - FPR on safe rows
  - FNR on unsafe_content_embedded_in_code
  - confusion matrix per violation_type
  - the GO/NO-GO check: of the gold rows where V1 returned action="pass"
    but the human label is unsafe, how many does V2 catch?

Usage on Colab or locally with a checkpoint:
    python -m output_guardrails.models.evaluate_codebert_classifier --gold
    python -m output_guardrails.models.evaluate_codebert_classifier --split test
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# PKG_ROOT  = .../ai-teaching-assistant/output_guardrails
# REPO_ROOT = .../ai-teaching-assistant
PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from output_guardrails.models.tokenizer_utils import MODEL_NAME, encode_with_truncation
from output_guardrails import apply_output_guardrails


DATA_PATH = PKG_ROOT / "classifier_data" / "classifier_dataset.jsonl"
GOLD_PATH = PKG_ROOT / "classifier_data" / "gold_test_set.jsonl"
SPLITS_PATH = PKG_ROOT / "classifier_data" / "splits.json"
CHECKPOINT_DIR = PKG_ROOT / "models" / "checkpoints" / "codebert_v2_0"


def load_jsonl(path):
    rows = []
    with path.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def select_split(rows, splits, name):
    return [r for r in rows if splits.get(r["context_id"], "train") == name]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", action="store_true")
    parser.add_argument("--split", choices=["train", "val", "test"], default="test")
    parser.add_argument("--threshold", type=float, default=0.7)
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
    )

    if args.gold:
        rows = load_jsonl(GOLD_PATH)
        title = "gold test set"
    else:
        all_rows = load_jsonl(DATA_PATH)
        splits = json.loads(SPLITS_PATH.read_text())
        rows = select_split(all_rows, splits, args.split)
        title = f"{args.split} split"

    print(f"evaluating on {title}: {len(rows)} rows")

    if not CHECKPOINT_DIR.exists():
        print(f"[error] checkpoint not found at {CHECKPOINT_DIR}")
        print("        train first: python -m models.train_codebert_classifier")
        return

    tokenizer = AutoTokenizer.from_pretrained(CHECKPOINT_DIR)
    model = AutoModelForSequenceClassification.from_pretrained(CHECKPOINT_DIR)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    scores, preds, labels, vtypes = [], [], [], []
    v1_actions = []
    with torch.no_grad():
        for r in rows:
            feats = encode_with_truncation(
                tokenizer, r["user_query"], r["student_code"], r["assistant_draft"]
            )
            input_ids = torch.tensor([feats["input_ids"]]).to(device)
            mask = torch.tensor([feats["attention_mask"]]).to(device)
            logits = model(input_ids=input_ids, attention_mask=mask).logits
            prob_unsafe = torch.softmax(logits, dim=-1)[0, 1].item()
            scores.append(prob_unsafe)
            preds.append(1 if prob_unsafe >= args.threshold else 0)
            labels.append(int(r["label"]))
            vtypes.append(r["violation_type"])
            v1 = apply_output_guardrails(
                r["assistant_draft"], r["user_query"], r["student_code"], []
            )
            v1_actions.append(v1["action"])

    print()
    print(f"=== Metrics @ threshold={args.threshold} ===")
    print(f"accuracy:  {accuracy_score(labels, preds):.3f}")
    print(f"precision: {precision_score(labels, preds, zero_division=0):.3f}")
    print(f"recall:    {recall_score(labels, preds, zero_division=0):.3f}")
    print(f"f1:        {f1_score(labels, preds, zero_division=0):.3f}")
    if len(set(labels)) == 2:
        print(f"roc-auc:   {roc_auc_score(labels, scores):.3f}")

    safe_idx = [i for i, l in enumerate(labels) if l == 0]
    if safe_idx:
        fpr = sum(1 for i in safe_idx if preds[i] == 1) / len(safe_idx)
        print(f"FPR on safe: {fpr:.3f}")

    embed_idx = [i for i, v in enumerate(vtypes) if v == "unsafe_content_embedded_in_code"]
    if embed_idx:
        fnr = sum(1 for i in embed_idx if preds[i] == 0) / len(embed_idx)
        print(f"FNR on unsafe_content_embedded_in_code: {fnr:.3f}")

    print()
    print("=== Confusion by violation_type ===")
    by_vtype = defaultdict(lambda: Counter())
    for v, lab, pr in zip(vtypes, labels, preds):
        key = "TP" if (lab == 1 and pr == 1) else \
              "TN" if (lab == 0 and pr == 0) else \
              "FP" if (lab == 0 and pr == 1) else "FN"
        by_vtype[v][key] += 1
    print(f"{'violation_type':<40s} {'TP':>4s} {'TN':>4s} {'FP':>4s} {'FN':>4s}")
    for v, c in sorted(by_vtype.items()):
        print(f"{v:<40s} {c['TP']:>4d} {c['TN']:>4d} {c['FP']:>4d} {c['FN']:>4d}")

    print()
    print("=== GO/NO-GO: V2 catching V1's misses ===")
    v1_pass_unsafe = [
        i for i in range(len(rows))
        if v1_actions[i] in ("pass", "log_only") and labels[i] == 1
    ]
    if v1_pass_unsafe:
        v2_caught = sum(1 for i in v1_pass_unsafe if preds[i] == 1)
        rate = v2_caught / len(v1_pass_unsafe)
        print(f"V1 passed but human label is unsafe: {len(v1_pass_unsafe)} rows")
        print(f"V2 caught: {v2_caught} ({rate:.1%})")
        print("Target for prototype: ≥50%")
    else:
        print("No rows where V1 passed but label is unsafe — can't run go/no-go.")


if __name__ == "__main__":
    main()
