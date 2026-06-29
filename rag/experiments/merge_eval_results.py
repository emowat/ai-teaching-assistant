#!/usr/bin/env python3
"""
Merge multiple eval_results_*topk_embeddings*.json files into one.

Each file is a JSON array of run dicts:
    [{"params": {...}, "run_metrics": {...}, "session_summaries": [...]}, ...]

The merge is a simple array concatenation.  If dedup is enabled, runs are
deduplicated by their params dict (JSON-serialised as a stable key) so the
same (embedding_model, top_k, rerank_strategy, rules_top_k, guidelines_top_k)
combination keeps only the *last* occurrence across the input files.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

EXPERIMENTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENTS_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from rag.experiments.retrieval_experiment import _read_text, _write_json, S3_BUCKET

# ---------------------------------------------------------------------------
# Config – edit these as needed
# ---------------------------------------------------------------------------
INPUT_FILES = [
    f"s3://{S3_BUCKET}/prepared/rag/experiments/outputs/eval_results_mit14_topk_embeddings.json",
    f"s3://{S3_BUCKET}/prepared/rag/experiments/outputs/eval_results_mit14_topk_embeddings_v2.json",
    f"s3://{S3_BUCKET}/prepared/rag/experiments/outputs/eval_results_mit14_topk_embeddings_v3.json",
]

OUTPUT_FILE = f"s3://{S3_BUCKET}/prepared/rag/experiments/outputs/eval_results_mit14_topk_embeddings_merged.json"

DEDUP_BY_PARAMS = os.environ.get("MERGE_DEDUP", "1") not in ("0", "false", "False")


def merge(input_paths: list[str], output_path: str, dedup: bool = True) -> list[dict]:
    merged: list[dict] = []

    for path in input_paths:
        print(f"Reading {path} ...")
        data = json.loads(_read_text(path))
        if not isinstance(data, list):
            raise ValueError(f"Expected a JSON array, got {type(data).__name__}: {path}")
        print(f"  {len(data)} runs")
        merged.extend(data)

    print(f"Total before dedup: {len(merged)} runs")

    if dedup:
        seen: dict[str, dict] = {}
        for run in merged:
            key = json.dumps(run.get("params", {}), sort_keys=True, default=str)
            seen[key] = run  # last write wins
        merged = list(seen.values())
        print(f"Total after dedup:  {len(merged)} runs")

    _write_json(output_path, merged)
    print(f"Written -> {output_path}")
    return merged


if __name__ == "__main__":
    merge(INPUT_FILES, OUTPUT_FILE, dedup=DEDUP_BY_PARAMS)
