#!/usr/bin/env python3
"""
add_bm25.py  —  BM25 + Vector Hybrid Retrieval Experiment

Imports the reusable pipeline from retrieval_experiment.py and adds a
hybrid retrieval strategy: BM25 (keyword) + vector (semantic), merged.

Grid: top_k [3, 5, 8, 10, 15]
Fixed: mpnet embedding, similarity rerank, no MMR.

Usage:
  export QDRANT_URL="https://..." QDRANT_API_KEY="..."
  export MLFLOW_TRACKING_URI="https://..."
  python add_bm25.py
  python add_bm25.py --dry-run
"""

from __future__ import annotations

import math
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

# Import reusable pipeline
experiments_dir = Path(__file__).resolve().parent
if str(experiments_dir) not in sys.path:
    sys.path.insert(0, str(experiments_dir))

from retrieval_experiment import (
    GOLDEN_LABELS_PATH,
    OUTPUT_PREFIX,
    RAW_DATA_PATH,
    ExpChunk,
    GoldenQuery,
    _NoopContext,
    _write_json,
    build_index,
    compute_metrics,
    load_golden_queries,
    load_harvard_cs50_chunks,
    run_experiment,
)

# ---------------------------------------------------------------------------
# BM25 Index
# ---------------------------------------------------------------------------

class BM25Index:
    """Minimal BM25 index over chunk corpus for keyword retrieval."""

    def __init__(self, chunks: list[ExpChunk]):
        self.chunks = chunks
        self.N = len(chunks)
        self.doc_freq: dict[str, int] = defaultdict(int)
        self.doc_tokens: list[set[str]] = []
        self._build()

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())

    def _build(self) -> None:
        for c in self.chunks:
            tokens = set(self._tokenize(c.content))
            self.doc_tokens.append(tokens)
            for t in tokens:
                self.doc_freq[t] += 1

    def search(self, query_text: str, top_k: int) -> list[tuple[str, float]]:
        """Return (chunk_id, score) sorted descending."""
        query_tokens = set(self._tokenize(query_text))
        if not query_tokens:
            return [(c.chunk_id, 0.0) for c in self.chunks[:top_k]]

        N = self.N
        idf = {
            t: math.log((N - df + 0.5) / (df + 0.5) + 1.0)
            for t, df in self.doc_freq.items()
        }
        avgdl = max(1.0, sum(len(t) for t in self.doc_tokens) / N)

        scored: list[tuple[str, float]] = []
        for i, c in enumerate(self.chunks):
            doc_tokens = self.doc_tokens[i]
            score = sum(idf.get(t, 0.0) for t in (query_tokens & doc_tokens))
            dl = max(1, len(doc_tokens))
            score /= 1.0 + 0.5 * (dl / avgdl)  # BM25 length norm
            scored.append((c.chunk_id, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ---------------------------------------------------------------------------
# Hybrid Retrieval
# ---------------------------------------------------------------------------

def retrieve_hybrid(
    client: Any,
    model: Any,
    query_text: str,
    query_week: int,
    collection_name: str,
    top_k: int,
    rerank_strategy: str,
    bm25: BM25Index | None = None,
) -> list[str]:
    """BM25 + vector hybrid: run both, merge, return deduped top_k."""

    # Vector search
    query_vector = model.encode(query_text, normalize_embeddings=True).tolist()

    from qdrant_client.models import FieldCondition, Filter, Range
    week_filter = Filter(
        must=[FieldCondition(key="week", range=Range(lte=query_week))]
    )

    hits = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=week_filter,
        limit=top_k,
    ).points

    vector_ids = [(str(h.id), h.score) for h in hits]

    # BM25 search (matches labeling pipeline's keyword retrieval)
    bm25_ids = []
    if bm25 is not None:
        eligible = [c for c in bm25.chunks if c.week <= query_week]
        temp_index = BM25Index(eligible) if eligible != bm25.chunks else bm25
        bm25_ids = temp_index.search(query_text, top_k)

    # Merge: interleave vector and BM25, dedup by chunk_id
    seen: set[str] = set()
    merged: list[str] = []
    max_len = max(len(vector_ids), len(bm25_ids))
    for i in range(max_len):
        for source in (vector_ids, bm25_ids):
            if i < len(source):
                cid = source[i][0]
                if cid not in seen:
                    seen.add(cid)
                    merged.append(cid)
                    if len(merged) >= top_k:
                        return merged
    return merged


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    import collections

    try:
        import mlflow
    except ImportError:
        print("WARNING: mlflow not installed.")
        mlflow = None

    parser = argparse.ArgumentParser(description="BM25+vector hybrid retrieval experiment")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # MLflow
    mlflow_active = False
    if mlflow:
        try:
            tracking_uri = os.getenv("MLFLOW_TRACKING_URI", "")
            if tracking_uri:
                mlflow.set_tracking_uri(tracking_uri)
            mlflow.set_experiment("rag_retrieval_hybrid")
            print(f"MLflow tracking: {mlflow.get_tracking_uri()}")
            mlflow_active = True
        except Exception as e:
            print(f"WARNING: MLflow setup failed: {e}")

    # Load golden queries
    print(f"\nLoading golden labels from {GOLDEN_LABELS_PATH} ...")
    golden_queries = load_golden_queries(GOLDEN_LABELS_PATH)
    print(f"  Loaded {len(golden_queries)} golden queries.")
    weeks = collections.Counter(q.week for q in golden_queries)
    print(f"  Week distribution: {dict(sorted(weeks.items()))}")

    # Load chunks + build BM25
    print(f"\nLoading chunks from {RAW_DATA_PATH} ...")
    chunks = load_harvard_cs50_chunks(RAW_DATA_PATH)
    print(f"  {len(chunks)} chunks total")
    bm25 = BM25Index(chunks)

    # Embedding model (fixed)
    emb_model = "sentence-transformers/multi-qa-mpnet-base-dot-v1"
    safe_name = emb_model.replace("/", "_").replace("-", "_")
    collection_name = f"exp_{safe_name}"

    # Build Qdrant index
    client, model = build_index(chunks, emb_model, collection_name)

    # Top-k grid
    top_ks = [3, 5, 8, 10, 15]
    total_runs = len(top_ks)
    print(f"\nGrid: {len(top_ks)} top_k x hybrid BM25+vector = {total_runs} runs")

    if args.dry_run:
        print("\n[DRY RUN] Configs that would be tested:")
        for k in top_ks:
            print(f"  top_k={k}  hybrid BM25+vector")
        return

    # Run
    print(f"\n  {'top_k':<6} {'recall@K':<10} {'precision@K':<12} {'f1@K':<10} "
          f"{'mrr':<10} {'ndcg@K':<10} {'latency'}")
    print(f"  {'-'*6} {'-'*10} {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

    all_results = []
    for top_k in top_ks:
        run_name = f"hybrid_bm25_vector_k{top_k}"
        with mlflow.start_run(run_name=run_name) if mlflow_active else _NoopContext():
            result = run_experiment(
                golden_queries=golden_queries,
                chunks=chunks,
                embedding_model_name=emb_model,
                top_k=top_k,
                collection_name=collection_name,
                client=client,
                model=model,
                rerank_strategy="similarity",
                retrieve_fn=lambda *a, **kw: retrieve_hybrid(*a, **kw, bm25=bm25),
                mlflow_active=mlflow_active,
            )
            all_results.append(result)

    # Cleanup
    try:
        client.delete_collection(collection_name)
    except Exception:
        pass
    try:
        client.close()
    except Exception:
        pass

    # Final report
    if all_results:
        print(f"\n{'=' * 60}")
        print(f"Experiment complete. {len(all_results)} runs.")
        print(f"{'=' * 60}")

        best = max(all_results, key=lambda r: r["metrics"].get(
            f"f1@{r['params']['top_k']}", 0))
        p = best["params"]
        m = best["metrics"]
        k = p["top_k"]
        print(f"\nBest by F1@{k}:")
        print(f"  top_k={k}")
        print(f"  recall@{k}={m[f'recall@{k}']:.4f}  "
              f"precision@{k}={m[f'precision@{k}']:.4f}  "
              f"f1@{k}={m[f'f1@{k}']:.4f}  "
              f"mrr={m['mrr']:.4f}  ndcg@{k}={m[f'ndcg@{k}']:.4f}")

        # Save to S3/local
        results_path = OUTPUT_PREFIX.rstrip("/") + "/experiment_results_hybrid_cs50.json"
        _write_json(results_path, all_results)
        print(f"\nResults saved -> {results_path}")


if __name__ == "__main__":
    main()
