# Retrieval Experiment

Grid search over embedding models, top-k, and rerank strategies to find the best RAG pipeline config for Harvard CS50.

---

## 1. Pipeline

```
golden_labels_cs50.json  →  Qdrant index  →  vector retrieval  →  MMR rerank  →  metrics vs golden
```

| Step | Description |
|------|-------------|
| Golden labels | `labeling_chunks.py` output: `{query_id: [chunk_id, ...]}` |
| Corpus | Harvard CS50 notes (87 chunks) + transcripts (2,477) |
| Index | Qdrant Cloud, one collection per embedding model |
| Retrieval | Pure vector search (cosine distance), no category/week filters |
| Rerank | Optional MMR (Jaccard token diversity) |
| Metrics | Recall@K, Precision@K, F1@K, MRR, NDCG@K vs golden labels |

---

## 2. Hyperparameter Grid

### 2.1 Embedding Models

| Model | Dim | Notes |
|-------|-----|-------|
| `all-MiniLM-L6-v2` | 384 | Lightweight baseline |
| `sentence-transformers/multi-qa-mpnet-base-dot-v1` | 768 | Optimized for semantic search |
| `BAAI/bge-base-en-v1.5` | 768 | Strong general-purpose |

### 2.2 Top-K

`[3, 5, 8, 10, 15]` — how many chunks retrieved per query.

### 2.3 Rerank Strategies

| Strategy | Description |
|----------|-------------|
| `similarity` | No rerank, raw cosine scores |
| `mmr_0.5` | MMR λ=0.5, balanced relevance/diversity |
| `mmr_0.7` | MMR λ=0.7, lean toward relevance |
| `mmr_0.9` | MMR λ=0.9, mostly relevance, slight diversity |

**MMR** (Maximal Marginal Relevance): scores each candidate as `λ × similarity_score - (1-λ) × max_jaccard_overlap_with_selected`. Higher λ = more relevance, lower = more diversity.

When MMR is active, Qdrant fetches `top_k × 4` candidates first, then MMR picks the top-k most diverse subset.

### 2.4 Grid Size

```
3 embeddings × 5 top_k × 4 rerank = 60 runs
```

One Qdrant index rebuild per embedding model (3 total).

---

## 3. Metrics

| Metric | Formula | Meaning |
|--------|---------|---------|
| `recall@K` | `|golden ∩ top-K| / |golden|` | Fraction of golden chunks found in top-K |
| `precision@K` | `|golden ∩ top-K| / K` | Fraction of top-K that are golden |
| `f1@K` | `2 × P × R / (P + R)` | Harmonic mean of precision and recall |
| `mrr` | `1 / rank_of_first_golden` | How early the first golden chunk appears |
| `ndcg@K` | `DCG / IDCG` | Recall weighted by position (earlier = higher score) |

Metrics are computed at K matching the retrieval top-k, then averaged across all queries.

---

## 4. Usage

```bash
# Full grid (60 runs)
python retrieval_experiment.py

# Quick mode (1 model, fewer rerank strategies)
python retrieval_experiment.py --quick

# Dry run (print configs, no indexing)
python retrieval_experiment.py --dry-run
```

Environment variables:

| Variable | Default |
|----------|---------|
| `QDRANT_URL` | (required for cloud) |
| `QDRANT_API_KEY` | (required for cloud) |
| `MLFLOW_TRACKING_URI` | Optional, logs metrics to MLflow |
| `RAG_EXPERIMENT_S3_BUCKET` | `codingrabbit-data-dev` |
| `RAG_EXPERIMENT_RAW_DATA_PATH` | Harvard notes S3 path |
| `RAG_EXPERIMENT_GOLDEN_LABELS_PATH` | `golden_labels_filtered.json` S3 path |

---

## 5. Best Result

Top config (row #28) by F1@8:

See: `s3://codingrabbit-data-dev/prepared/rag/experiments/outputs/experiment_results_cs50.json`

| Parameter | Value |
|-----------|-------|
| Embedding model | `sentence-transformers/multi-qa-mpnet-base-dot-v1` |
| Top-K | 8 |
| Rerank strategy | similarity |
| Rerank lambda | none |
| Fetch multiplier | 1 |
| Num queries | 113 |
| Num chunks | 3,078 |
| Collection | `exp_sentence_transformers_multi_qa_mpnet_base_dot_v1` |

### Metrics (K=8)

| Metric | Value |
|--------|-------|
| Recall@8 | 0.1405 |
| Precision@8 | 0.1040 |
| F1@8 | 0.1153 |
| MRR | 0.2646 |
| NDCG@8 | 0.1421 |

> Metrics at other K values (@3, @5, @10, @15) are not applicable — the experiment evaluates each run only at its configured top_k, so only K=8 metrics carry signal for this config.

---

## 6. Experiment V2 — BM25 + Vector Hybrid

`add_bm25.py` — same pipeline, but retrieval merges BM25 (keyword) and vector (semantic) results.

Grid: 5 top_k × hybrid BM25+vector = 5 runs.

| top_k | recall@K | precision@K | f1@K | mrr | ndcg@K |
|-------|----------|-------------|------|-----|--------|
| 3 | 0.0591 | 0.1298 | 0.0785 | 0.2139 | 0.1300 |
| 5 | 0.0908 | 0.1133 | 0.0967 | 0.2382 | 0.1237 |
| 8 | 0.1371 | 0.1029 | 0.1134 | 0.2525 | 0.1340 |
| **10** | **0.1657** | **0.1000** | **0.1207** | **0.2598** | **0.1460** |
| 15 | 0.2136 | 0.0855 | 0.1187 | 0.2638 | 0.1671 |

### Best by F1@10

| Metric | Value |
|--------|-------|
| Recall@10 | 0.1657 |
| Precision@10 | 0.1000 |
| F1@10 | 0.1207 |
| MRR | 0.2598 |
| NDCG@10 | 0.1460 |

### V1 vs V2 comparison (same mpnet, top_k=8)

| Metric | V1 (vector only) | V2 (BM25+vector) | Delta |
|--------|------------------|-------------------|-------|
| Recall@8 | 0.1405 | 0.1371 | -2.4% |
| F1@8 | 0.1153 | 0.1134 | -1.6% |
| MRR | 0.2646 | 0.2525 | -4.6% |

Hybrid BM25+vector did not improve over pure vector at K=8. BM25 pulls from a different ranking distribution; merging with interleave may dilute the vector signal when golden labels were generated with BM25 (labeling pipeline uses BM25 only, not vector).
