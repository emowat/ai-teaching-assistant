"""
Evaluate a trained INPUT CodeBERT guardrail checkpoint.

Evaluates on EITHER:
  - the internal test split of the candidate dataset (--eval-path candidates
    + --splits-path + --split test), OR
  - the EXTERNAL hard gold set (--eval-path input_hard_gold_v1.jsonl).

The hard gold set is external evaluation only; its use is clearly labeled in
the output. Uses the SAME format_example() as training.

Threshold semantics: score = P(unsafe). pred = unsafe(1) if score >= threshold.
Default threshold 0.70 mirrors the project's block cutoff.

Isolated from output_guardrails/ — evaluates the input model only.

Usage:
    python -m input_guardrails.models.evaluate_input_codebert_classifier \
        --checkpoint-path input_guardrails/models/checkpoints/input_codebert_v1 \
        --eval-path input_guardrails/classifier_data/input_hard_gold_v1.jsonl \
        --threshold-sweep
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from input_guardrails.models.data_utils import (
    apply_splits,
    format_example,
    load_jsonl,
    load_splits,
)

SWEEP_THRESHOLDS = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Evaluate the input CodeBERT guardrail.")
    p.add_argument("--checkpoint-path", required=True)
    p.add_argument("--eval-path", required=True, help="candidate or hard-gold JSONL")
    p.add_argument("--splits-path", default=None, help="needed only with --split")
    p.add_argument("--split", default=None, choices=["train", "val", "test"],
                   help="if set, restrict eval-path rows to this split")
    p.add_argument("--max-length", type=int, default=512)
    p.add_argument("--threshold", type=float, default=0.70)
    p.add_argument("--threshold-sweep", action="store_true", default=False)
    p.add_argument("--output-json", default=None)
    return p.parse_args(argv)


def _select_rows(args):
    rows = load_jsonl(args.eval_path)
    is_hard_gold = "hard_gold" in Path(args.eval_path).name.lower()
    if args.split:
        if not args.splits_path:
            raise SystemExit("ERROR: --split requires --splits-path")
        splits = load_splits(args.splits_path)
        buckets, _ = apply_splits(rows, splits)
        rows = buckets[args.split]
    return rows, is_hard_gold


def _metrics_at(scores, labels, threshold):
    """Confusion counts + derived metrics at a given threshold."""
    tp = tn = fp = fn = 0
    for s, y in zip(scores, labels):
        pred = 1 if s >= threshold else 0
        if y == 1 and pred == 1:
            tp += 1
        elif y == 0 and pred == 0:
            tn += 1
        elif y == 0 and pred == 1:
            fp += 1
        else:
            fn += 1
    acc = (tp + tn) / max(1, tp + tn + fp + fn)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    fpr = fp / max(1, fp + tn)
    return {"threshold": threshold, "tp": tp, "tn": tn, "fp": fp, "fn": fn,
            "accuracy": acc, "precision": prec, "recall": rec, "f1": f1, "fpr": fpr}


def main(argv=None):
    args = parse_args(argv)

    # Heavy imports deferred.
    import numpy as np
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    ckpt = Path(args.checkpoint_path)
    if not ckpt.exists():
        raise SystemExit(f"ERROR: checkpoint not found: {ckpt}")

    rows, is_hard_gold = _select_rows(args)
    src = "EXTERNAL HARD GOLD" if is_hard_gold else f"internal ({args.split or 'all'})"
    print(f"=== Input-guardrail evaluation ===")
    print(f"checkpoint: {ckpt}")
    print(f"eval set:   {args.eval_path}  [{src}]  rows={len(rows)}")
    if is_hard_gold:
        print("NOTE: hard gold is EXTERNAL EVALUATION ONLY (never used in training).")
    if not rows:
        raise SystemExit("ERROR: no rows to evaluate.")

    tokenizer = AutoTokenizer.from_pretrained(str(ckpt))
    model = AutoModelForSequenceClassification.from_pretrained(str(ckpt))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    scores, labels = [], []
    with torch.no_grad():
        for r in rows:
            enc = tokenizer(format_example(r), truncation=True,
                            max_length=args.max_length, return_tensors="pt").to(device)
            logits = model(**enc).logits
            p_unsafe = torch.softmax(logits, dim=-1)[0, 1].item()
            scores.append(p_unsafe)
            labels.append(int(r["label"]))

    # Primary metrics at the chosen threshold.
    m = _metrics_at(scores, labels, args.threshold)
    print(f"\n=== Metrics @ threshold={args.threshold} ===")
    for k in ("accuracy", "precision", "recall", "f1", "fpr"):
        print(f"  {k}: {m[k]:.3f}")
    print(f"  confusion: TP={m['tp']} TN={m['tn']} FP={m['fp']} FN={m['fn']}")
    print("  confusion matrix (rows=actual, cols=pred):")
    print(f"           pred_safe  pred_unsafe")
    print(f"    safe   {m['tn']:>9} {m['fp']:>12}")
    print(f"    unsafe {m['fn']:>9} {m['tp']:>12}")

    # ROC-AUC if possible.
    roc_auc = None
    if len(set(labels)) == 2:
        try:
            from sklearn.metrics import roc_auc_score
            roc_auc = float(roc_auc_score(labels, scores))
            print(f"  roc-auc: {roc_auc:.3f}")
        except Exception:  # noqa: BLE001
            print("  roc-auc: (sklearn unavailable)")

    # FP / FN listing.
    print("\n=== False positives (safe rows predicted unsafe) ===")
    for r, s in zip(rows, scores):
        if int(r["label"]) == 0 and s >= args.threshold:
            print(f"  id={r.get('id')} cat={r.get('category')} score={s:.3f} "
                  f"label={r['label']} topic={r.get('course_topic')!r} q={r.get('user_query')[:60]!r}")
    print("=== False negatives (unsafe rows predicted safe) ===")
    for r, s in zip(rows, scores):
        if int(r["label"]) == 1 and s < args.threshold:
            print(f"  id={r.get('id')} cat={r.get('category')} score={s:.3f} "
                  f"label={r['label']} topic={r.get('course_topic')!r} q={r.get('user_query')[:60]!r}")

    sweep = None
    if args.threshold_sweep:
        print("\n=== Threshold sweep ===")
        print(f"{'thr':>5} {'acc':>6} {'prec':>6} {'rec':>6} {'f1':>6} {'fpr':>6}")
        sweep = [_metrics_at(scores, labels, t) for t in SWEEP_THRESHOLDS]
        for s in sweep:
            mark = "  <- default" if abs(s["threshold"] - 0.70) < 1e-9 else ""
            print(f"{s['threshold']:>5.2f} {s['accuracy']:>6.3f} {s['precision']:>6.3f} "
                  f"{s['recall']:>6.3f} {s['f1']:>6.3f} {s['fpr']:>6.3f}{mark}")

    if args.output_json:
        out = {
            "checkpoint": str(ckpt),
            "eval_path": args.eval_path,
            "is_hard_gold_external": is_hard_gold,
            "split": args.split,
            "n_rows": len(rows),
            "threshold": args.threshold,
            "metrics": m,
            "roc_auc": roc_auc,
            "sweep": sweep,
        }
        Path(args.output_json).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nwrote {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
