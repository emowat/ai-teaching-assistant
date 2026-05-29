"""Fine-tune microsoft/codebert-base for binary safety classification.

Designed for free Colab T4 / Kaggle. The script:
    1. Loads classifier_dataset.jsonl + splits.json.
    2. Tokenizes with the shared tokenizer_utils formatter.
    3. Fine-tunes for a small number of epochs with early stopping on
       the val split.
    4. Saves the checkpoint to models/checkpoints/codebert_v2_0/.

Usage on Colab:
    !git clone <this repo>
    %cd ai-teaching-assistant
    !pip install -q transformers datasets torch scikit-learn
    !python -m output_guardrails.models.train_codebert_classifier --epochs 3

Usage locally (CPU; very slow, only for sanity-check):
    python3 -m output_guardrails.models.train_codebert_classifier --epochs 1 --batch-size 4

This script does not run on the local machine in this Capstone — it
exists so a teammate can clone and run it on Colab.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# PKG_ROOT  = .../ai-teaching-assistant/output_guardrails
# REPO_ROOT = .../ai-teaching-assistant
PKG_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PKG_ROOT.parent
sys.path.insert(0, str(REPO_ROOT))

from output_guardrails.models.tokenizer_utils import (
    MODEL_NAME, MAX_TOTAL_TOKENS, encode_with_truncation,
)


DATA_PATH = PKG_ROOT / "classifier_data" / "classifier_dataset.jsonl"
SPLITS_PATH = PKG_ROOT / "classifier_data" / "splits.json"
CHECKPOINT_DIR = PKG_ROOT / "models" / "checkpoints" / "codebert_v2_0"


def load_rows():
    rows = []
    with DATA_PATH.open() as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    splits = json.loads(SPLITS_PATH.read_text())
    train, val, test = [], [], []
    for r in rows:
        s = splits.get(r["scenario_id"], "train")
        if s == "train":
            train.append(r)
        elif s == "val":
            val.append(r)
        else:
            test.append(r)
    return train, val, test


def encode_split(rows, tokenizer):
    encoded = []
    for r in rows:
        feats = encode_with_truncation(
            tokenizer, r["user_query"], r["student_code"], r["assistant_draft"]
        )
        feats["label"] = int(r["label"])
        encoded.append(feats)
    return encoded


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    # Imports here so this file is importable for inspection without
    # transformers installed.
    import torch
    from torch.utils.data import DataLoader, Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        get_linear_schedule_with_warmup,
    )
    from sklearn.metrics import f1_score, precision_score, recall_score

    torch.manual_seed(args.seed)

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    train_rows, val_rows, test_rows = load_rows()
    print(f"train={len(train_rows)}  val={len(val_rows)}  test={len(test_rows)}")

    class JsonlDataset(Dataset):
        def __init__(self, encoded):
            self.encoded = encoded

        def __len__(self):
            return len(self.encoded)

        def __getitem__(self, i):
            return self.encoded[i]

    def collate(batch):
        max_len = max(len(b["input_ids"]) for b in batch)
        ids = []
        masks = []
        labels = []
        for b in batch:
            pad = max_len - len(b["input_ids"])
            ids.append(b["input_ids"] + [tokenizer.pad_token_id] * pad)
            masks.append(b["attention_mask"] + [0] * pad)
            labels.append(b["label"])
        return {
            "input_ids": torch.tensor(ids),
            "attention_mask": torch.tensor(masks),
            "labels": torch.tensor(labels),
        }

    train_loader = DataLoader(
        JsonlDataset(encode_split(train_rows, tokenizer)),
        batch_size=args.batch_size, shuffle=True, collate_fn=collate,
    )
    val_loader = DataLoader(
        JsonlDataset(encode_split(val_rows, tokenizer)),
        batch_size=args.batch_size, shuffle=False, collate_fn=collate,
    )

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr)
    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=int(0.1 * total_steps), num_training_steps=total_steps,
    )

    best_f1 = -1.0
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    for epoch in range(args.epochs):
        model.train()
        for batch in train_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            out = model(**batch)
            out.loss.backward()
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad()

        model.eval()
        preds, labels = [], []
        with torch.no_grad():
            for batch in val_loader:
                batch = {k: v.to(device) for k, v in batch.items()}
                out = model(**{k: v for k, v in batch.items() if k != "labels"})
                pred = out.logits.argmax(dim=-1).cpu().tolist()
                preds.extend(pred)
                labels.extend(batch["labels"].cpu().tolist())
        f1 = f1_score(labels, preds, zero_division=0)
        prec = precision_score(labels, preds, zero_division=0)
        rec = recall_score(labels, preds, zero_division=0)
        print(f"epoch {epoch+1}: val precision={prec:.3f} recall={rec:.3f} f1={f1:.3f}")
        if f1 > best_f1:
            best_f1 = f1
            model.save_pretrained(CHECKPOINT_DIR)
            tokenizer.save_pretrained(CHECKPOINT_DIR)
            print(f"  saved best checkpoint to {CHECKPOINT_DIR}")

    print(f"done. best val f1={best_f1:.3f}")


if __name__ == "__main__":
    main()
