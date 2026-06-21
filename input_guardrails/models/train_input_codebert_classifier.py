"""
Fine-tune microsoft/codebert-base as the INPUT guardrail classifier.

Binary classification of the student's RAW question (before RAG/Qwen):
    label = 1  -> unsafe / BLOCK (do not call the LLM)
    label = 0  -> safe   / PASS

Isolated from output_guardrails/ — this trains a SEPARATE input model and does
not touch the output CodeBERT, semantic_guardrail.py, thresholds, S3, etc.

The hard gold set is NEVER loaded here (evaluation only). Training data is the
candidate JSONL, split by context_id via splits_input_v1.json.

Usage (data-only dry run — no model download/train):
    python -m input_guardrails.models.train_input_codebert_classifier \
        --train-path input_guardrails/classifier_data/input_classifier_dataset_v1_candidates.jsonl \
        --splits-path input_guardrails/classifier_data/splits_input_v1.json \
        --checkpoint-name input_codebert_v1 --dry-run

Full training (only when explicitly approved):
    (drop --dry-run; requires torch + transformers)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# data_utils is stdlib-only, safe to import at top level.
_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from input_guardrails.models.data_utils import (
    apply_splits,
    assert_no_context_leakage,
    format_example,
    label_distribution,
    load_jsonl,
    load_splits,
    split_report,
)

DEFAULT_MODEL = "microsoft/codebert-base"
DEFAULT_OUTPUT_DIR = _HERE / "checkpoints"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Train the input CodeBERT guardrail classifier.")
    p.add_argument("--train-path", required=True, help="candidate JSONL")
    p.add_argument("--splits-path", required=True, help="splits_input_v1.json")
    p.add_argument("--model-name", default=DEFAULT_MODEL)
    p.add_argument("--checkpoint-name", default="input_codebert_v1")
    p.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--max-length", type=int, default=512)
    p.add_argument("--learning-rate", type=float, default=2e-5)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--seed", type=int, default=2026)
    p.add_argument("--require-reviewed", action="store_true", default=False,
                   help="only train on rows with reviewed=true")
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="load + split + preview only; no model download/train")
    return p.parse_args(argv)


def load_and_split(args):
    """Shared data-prep: load candidate rows, split by context_id, verify no
    leakage. Returns (buckets, unassigned)."""
    rows = load_jsonl(args.train_path)
    splits = load_splits(args.splits_path)
    buckets, unassigned = apply_splits(
        rows, splits, require_reviewed=args.require_reviewed
    )
    assert_no_context_leakage(buckets)
    return rows, buckets, unassigned


def run_dry_run(args):
    rows, buckets, unassigned = load_and_split(args)
    print("=== DRY RUN (data only; no model download/train) ===")
    print(f"candidate rows loaded: {len(rows)}"
          + (f"  (reviewed-only filter ON)" if args.require_reviewed else ""))
    print("split-by-context_id, leakage check: PASSED")
    print(split_report(buckets))
    if unassigned:
        print(f"  [warn] {len(unassigned)} rows had no split entry (excluded)")

    # Preview a few formatted examples (one safe, one unsafe if available).
    preview = []
    for split_rows in buckets.values():
        for r in split_rows:
            preview.append(r)
            if len(preview) >= 2:
                break
        if len(preview) >= 2:
            break
    print("\n=== sample formatted input(s) ===")
    for r in preview[:2]:
        print(f"\n--- id={r.get('id')} label={r['label']} category={r.get('category')} ---")
        print(format_example(r))

    print("\nDry run complete. No model was downloaded or trained.")
    return 0


def _compute_metrics_fn():
    """Build a HF Trainer compute_metrics callback (imports sklearn lazily)."""
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support

    def compute_metrics(eval_pred):
        import numpy as np
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        acc = accuracy_score(labels, preds)
        prec, rec, f1, _ = precision_recall_fscore_support(
            labels, preds, average="binary", zero_division=0
        )
        return {"accuracy": acc, "precision": prec, "recall": rec, "f1": f1}

    return compute_metrics


def run_train(args):
    # Heavy imports deferred so dry-run/tests need no ML deps.
    import numpy as np  # noqa: F401
    import torch
    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    set_seed(args.seed)
    rows, buckets, unassigned = load_and_split(args)
    print(f"loaded {len(rows)} candidate rows; splits:")
    print(split_report(buckets))
    if not buckets["train"]:
        print("[error] empty train split — nothing to train on.")
        return 1

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)

    def to_dataset(split_rows):
        texts = [format_example(r) for r in split_rows]
        labels = [int(r["label"]) for r in split_rows]
        enc = tokenizer(texts, truncation=True, max_length=args.max_length,
                        padding="max_length")
        enc["labels"] = labels
        return Dataset.from_dict(enc)

    train_ds = to_dataset(buckets["train"])
    val_ds = to_dataset(buckets["val"])

    model = AutoModelForSequenceClassification.from_pretrained(
        args.model_name, num_labels=2
    )

    ckpt_dir = Path(args.output_dir) / args.checkpoint_name
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(ckpt_dir / "_hf_trainer"),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        weight_decay=args.weight_decay,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="f1",
        greater_is_better=True,
        seed=args.seed,
        logging_steps=10,
        report_to=[],
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        compute_metrics=_compute_metrics_fn(),
    )

    print(f"\ntraining {args.model_name} -> {ckpt_dir}")
    trainer.train()

    # Per-epoch val metrics were printed by the Trainer; capture final + history.
    final_metrics = trainer.evaluate()
    print("\nfinal validation metrics:")
    for k, v in final_metrics.items():
        print(f"  {k}: {v}")

    # Save best model + tokenizer to the checkpoint dir.
    trainer.save_model(str(ckpt_dir))
    tokenizer.save_pretrained(str(ckpt_dir))

    metrics_out = {
        "checkpoint_name": args.checkpoint_name,
        "model_name": args.model_name,
        "epochs": args.epochs,
        "seed": args.seed,
        "max_length": args.max_length,
        "train_size": len(buckets["train"]),
        "val_size": len(buckets["val"]),
        "test_size": len(buckets["test"]),
        "train_label_dist": label_distribution(buckets["train"]),
        "val_label_dist": label_distribution(buckets["val"]),
        "final_val_metrics": {k: float(v) for k, v in final_metrics.items()
                              if isinstance(v, (int, float))},
        "log_history": trainer.state.log_history,
    }
    (ckpt_dir / "train_metrics.json").write_text(
        json.dumps(metrics_out, indent=2), encoding="utf-8"
    )
    print(f"\nsaved checkpoint + tokenizer + train_metrics.json to {ckpt_dir}")
    return 0


def main(argv=None):
    args = parse_args(argv)
    return run_dry_run(args) if args.dry_run else run_train(args)


if __name__ == "__main__":
    raise SystemExit(main())
