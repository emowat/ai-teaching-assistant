"""Evaluate a trained V2 CodeBERT checkpoint.

Reports:
  - accuracy / precision / recall / F1 / ROC-AUC
  - 2x2 confusion matrix (TN/FP/FN/TP) + explicit FP and FN row lists
  - FPR on safe rows
  - FNR on unsafe_content_embedded_in_code
  - per-violation_type confusion (TP/TN/FP/FN)
  - threshold analysis at 0.50 / 0.60 / 0.70 / 0.80 (recall + FPR + F1)
  - the GO/NO-GO check: of the rows where V1 returned action="pass"/"log_only"
    but the human label is unsafe, how many does V2 catch?

Paths default to the v2_0 checkpoint and original gold/splits so existing
behavior is unchanged. The production decision threshold stays 0.70.

Usage (defaults reproduce v2_0-on-original-gold):
    # v2_0 on original gold
    python -m output_guardrails.models.evaluate_codebert_classifier --gold

    # v2_0 on the v2_1 hard gold set
    python -m output_guardrails.models.evaluate_codebert_classifier \\
        --gold-path output_guardrails/classifier_data/hard_gold_test_set_v2_1.jsonl

    # v2_1 on original gold
    python -m output_guardrails.models.evaluate_codebert_classifier --gold \\
        --checkpoint-path output_guardrails/models/checkpoints/codebert_v2_1

    # v2_1 on the v2_1 hard gold set
    python -m output_guardrails.models.evaluate_codebert_classifier \\
        --gold-path output_guardrails/classifier_data/hard_gold_test_set_v2_1.jsonl \\
        --checkpoint-path output_guardrails/models/checkpoints/codebert_v2_1

    # a split of a training dataset
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


# Defaults reproduce v2_0 on the original gold/splits.
DEFAULT_DATA_PATH = PKG_ROOT / "classifier_data" / "classifier_dataset.jsonl"
DEFAULT_GOLD_PATH = PKG_ROOT / "classifier_data" / "gold_test_set.jsonl"
DEFAULT_SPLITS_PATH = PKG_ROOT / "classifier_data" / "splits.json"
DEFAULT_CHECKPOINT_PATH = PKG_ROOT / "models" / "checkpoints" / "codebert_v2_0"

THRESHOLD_SWEEP = [0.50, 0.60, 0.70, 0.80]


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
    parser.add_argument("--gold", action="store_true",
                        help="evaluate on a gold set (see --gold-path)")
    parser.add_argument("--split", choices=["train", "val", "test"], default="test",
                        help="when not --gold, which split of --data-path to use")
    parser.add_argument("--threshold", type=float, default=0.7,
                        help="primary decision threshold (production = 0.70)")
    parser.add_argument("--data-path", type=Path, default=DEFAULT_DATA_PATH,
                        help="dataset jsonl for --split mode")
    parser.add_argument("--gold-path", type=Path, default=DEFAULT_GOLD_PATH,
                        help="gold jsonl for --gold mode (e.g. hard_gold_test_set_v2_1.jsonl)")
    parser.add_argument("--splits-path", type=Path, default=DEFAULT_SPLITS_PATH,
                        help="splits.json for --split mode")
    parser.add_argument("--checkpoint-path", type=Path, default=DEFAULT_CHECKPOINT_PATH,
                        help="checkpoint dir to load (default: codebert_v2_0)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score, roc_auc_score,
    )

    torch.manual_seed(args.seed)

    # --gold-path implies gold mode even if --gold wasn't passed, so the
    # hard-gold command line stays short.
    use_gold = args.gold or (args.gold_path != DEFAULT_GOLD_PATH)
    if use_gold:
        rows = load_jsonl(args.gold_path)
        title = f"gold set ({args.gold_path.name})"
    else:
        all_rows = load_jsonl(args.data_path)
        splits = json.loads(args.splits_path.read_text())
        rows = select_split(all_rows, splits, args.split)
        title = f"{args.split} split ({args.data_path.name})"

    checkpoint_dir = args.checkpoint_path
    print(f"checkpoint:  {checkpoint_dir}")
    print(f"evaluating on {title}: {len(rows)} rows")

    if not checkpoint_dir.exists():
        print(f"[error] checkpoint not found at {checkpoint_dir}")
        print("        train first: python -m output_guardrails.models.train_codebert_classifier")
        return

    tokenizer = AutoTokenizer.from_pretrained(checkpoint_dir)
    model = AutoModelForSequenceClassification.from_pretrained(checkpoint_dir)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    scores, preds, labels, vtypes, ids = [], [], [], [], []
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
            ids.append(r.get("id", r.get("scenario_id", "?")))
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

    # 2x2 confusion matrix at the primary threshold.
    tp = sum(1 for l, p in zip(labels, preds) if l == 1 and p == 1)
    tn = sum(1 for l, p in zip(labels, preds) if l == 0 and p == 0)
    fp = sum(1 for l, p in zip(labels, preds) if l == 0 and p == 1)
    fn = sum(1 for l, p in zip(labels, preds) if l == 1 and p == 0)
    print()
    print("=== Confusion matrix (rows=actual, cols=pred) ===")
    print(f"{'':>14s} {'pred safe':>10s} {'pred unsafe':>12s}")
    print(f"{'actual safe':>14s} {tn:>10d} {fp:>12d}")
    print(f"{'actual unsafe':>14s} {fn:>10d} {tp:>12d}")

    safe_idx = [i for i, l in enumerate(labels) if l == 0]
    if safe_idx:
        fpr = sum(1 for i in safe_idx if preds[i] == 1) / len(safe_idx)
        print(f"FPR on safe: {fpr:.3f}")

    embed_idx = [i for i, v in enumerate(vtypes) if v == "unsafe_content_embedded_in_code"]
    if embed_idx:
        fnr = sum(1 for i in embed_idx if preds[i] == 0) / len(embed_idx)
        print(f"FNR on unsafe_content_embedded_in_code: {fnr:.3f}")

    # Explicit FP / FN row lists (id, violation_type, score) so failures
    # are inspectable, not just counted.
    fp_rows = [(ids[i], vtypes[i], scores[i]) for i in range(len(rows))
               if labels[i] == 0 and preds[i] == 1]
    fn_rows = [(ids[i], vtypes[i], scores[i]) for i in range(len(rows))
               if labels[i] == 1 and preds[i] == 0]
    print()
    print(f"=== False positives ({len(fp_rows)}) — safe rows flagged unsafe ===")
    for rid, vt, sc in fp_rows:
        print(f"  {rid:<22s} {vt:<32s} score={sc:.3f}")
    print(f"=== False negatives ({len(fn_rows)}) — unsafe rows missed ===")
    for rid, vt, sc in fn_rows:
        print(f"  {rid:<22s} {vt:<32s} score={sc:.3f}")

    # Threshold sweep: recall (catch rate on unsafe) and FPR (over-block on
    # safe) at each candidate cutoff. Production stays 0.70 — this is
    # diagnostic only and does NOT change the runtime threshold.
    print()
    print("=== Threshold analysis (production threshold stays 0.70) ===")
    print(f"{'thresh':>7s} {'recall':>8s} {'FPR':>8s} {'precision':>10s} {'f1':>7s}")
    n_unsafe = sum(1 for l in labels if l == 1)
    n_safe = sum(1 for l in labels if l == 0)
    for t in THRESHOLD_SWEEP:
        sweep_preds = [1 if s >= t else 0 for s in scores]
        rec = (sum(1 for l, p in zip(labels, sweep_preds) if l == 1 and p == 1) / n_unsafe) if n_unsafe else 0.0
        fpr_t = (sum(1 for l, p in zip(labels, sweep_preds) if l == 0 and p == 1) / n_safe) if n_safe else 0.0
        prec_t = precision_score(labels, sweep_preds, zero_division=0)
        f1_t = f1_score(labels, sweep_preds, zero_division=0)
        marker = "  <- production" if abs(t - 0.70) < 1e-9 else ""
        print(f"{t:>7.2f} {rec:>8.3f} {fpr_t:>8.3f} {prec_t:>10.3f} {f1_t:>7.3f}{marker}")

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
