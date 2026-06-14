# Retrieval Experiment Design

## Flowchart

### Phase 1–5: Overall Experiment Pipeline

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                          │
│  ┌─────────────────────┐   ┌─────────────────────┐   ┌─────────────────────┐             │
│  │      Phase 1        │   │      Phase 2        │   │      Phase 3        │             │
│  │                     │   │                     │   │                     │             │
│  │  Generate golden    │   │  Embedding model    │   │  Chunking variant   │             │
│  │  labels             │   │  sweep              │   │  experiment         │             │
│  │                     │   │                     │   │                     │             │
│  │  LLM dual-provider  │──▶│  Recall@K           │──▶│  slide + overlap    │             │
│  │  + cross-encoder    │   │  MRR, NDCG          │   │  → sentence-window  │             │
│  │                     │   │                     │   │                     │             │
│  │  → golden_labels    │   │  Metric: hit rate   │   │  Metric: best       │             │
│  │     .json            │   │  of golden labels   │   │  chunking strategy  │             │
│  └─────────────────────┘   └─────────────────────┘   └─────────────────────┘             │
│                                                                                          │
│  ┌─────────────────────┐   ┌─────────────────────────────────────────────────────┐       │
│  │      Phase 4        │   │                    Phase 5                          │       │
│  │                     │   │                                                     │       │
│  │  Retriever type     │   │  Full combination validation                        │       │
│  │  + Top-K            │──▶│                                                     │       │
│  │  grid search        │   │  Best (model, chunking, retriever, k)               │       │
│  │                     │   │  + cost & latency analysis                          │       │
│  │  Metric: Recall@K,  │   │                                                     │       │
│  │  MRR, NDCG          │   │  Final recommendation for production RAG pipeline   │       │
│  └─────────────────────┘   └─────────────────────────────────────────────────────┘       │
│                                                                                          │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### Phase 1 Detail: Golden Label Generation

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     1. Load Eval Dataset                                    │
│  1,351 synthetic student-TA conversations from                              │
│  synthetic_c_plus_plus_dataset.jsonl                                        │
│  Exclude Out-of-Scope triggers (~51 records)                                │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     2. Sample 80–100 Queries                                 │
│  Stratified by: week (min 5 per week), mode (Homework ~75%, Study ~25%)     │
│  → eval_queries.jsonl                                                        │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   3. Build Candidate Pool per Query                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Tier 1: Full Presentation                                           │    │
│  │  Week W (all chunks)  +  Week 0 (shared reference)                   │    │
│  │  (~35-55 chunks, full content shown)                                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                     │                                        │
│  ┌─────────────────────────────────▼───────────────────────────────────┐    │
│  │  Tier 2: Hybrid Expansion (weeks 1..W-1)                             │    │
│  │  BM25 Top-Kw  ∪  Embedding Top-Kw  →  Dedup  →  Neighbor ±1         │    │
│  │  (~10-48 chunks, three complementary signals)                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                     │                                        │
│  Total pool: ~40-103 chunks per query (varies by week)                       │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   4. LLM Labeling (Dual-Provider)                            │
│  ┌──────────────────────────┐    ┌──────────────────────────┐               │
│  │  Cohere command-r-plus    │    │  OpenAI GPT-5 mini        │               │
│  │  temp=0.0                │    │  temp=0.0                │               │
│  │  Input: student Q +      │    │  Input: student Q +      │               │
│  │  golden answer +         │    │  golden answer +         │               │
│  │  candidate chunks        │    │  candidate chunks        │               │
│  └────────────┬─────────────┘    └────────────┬─────────────┘               │
│               │                               │                              │
│               └───────────┬───────────────────┘                              │
│                           │                                                  │
│                           ▼                                                  │
│               ┌───────────────────────┐                                      │
│               │  Union =             │                                      │
│               │  golden labels       │                                      │
│               │  (Jaccard < 0.6 →    │                                      │
│               │   manual review)     │                                      │
│               └───────────────────────┘                                      │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  5. Cross-Encoder Validation                                 │
│  Model: BAAI/bge-reranker-v2-m3 (local, free)                               │
│  Score each (query, chunk) pair → threshold at 0.5                          │
│  Compute agreement (Jaccard) with LLM labels                                │
│  > 0.7: reliable  |  0.4-0.7: spot-check  |  < 0.4: manual review          │
│  → ce_scores.json  +  agreement_report.json                                  │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  6. Output: Golden Labels Finalized                          │
│  golden_labels.json: {query_id → [chunk_id, ...]}                           │
│  Ready for Phase 2–5 retrieval experiments                                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

> **Goal**: Select the optimal combination of (embedding model, chunking
> strategy, overlap, retriever type, top-k) for the RAG pipeline by
> systematically comparing retrieval quality on a labeled query set.

---

## 1. Current Chunking Method

### 1.1 Data Sources

| Source | Path | Format |
|--------|------|--------|
| Lecture slides | `raw_data/lecture_text/0[1-8]_lecture_*.json` | List of `{page, section, text, has_code}` |
| Syllabus | `raw_data/mit_ocw_output/syllabus.txt` | Plain text + `SYLLABUS_MATRIX` (Python dict) |
| Assignment solutions | `raw_data/lecture_text/assignment*_solution.json` | Same slide format as lectures |

> **Note**: Textbooks may be added later. The chunking approach will need to be
> revisited when long-form continuous prose is introduced (see §6).

### 1.2 Current Chunking Strategy

**Slide-based chunking: one slide = one chunk** (no overlap, no sliding window).

Implemented in `rag/loader.py`:

1. **Lecture slides**: Each slide JSON object becomes one chunk.
   - Content is formatted as `[{section}] {text}` (section name prepended for
     retrieval context).
   - Content capped at 2000 characters.
   - Week number derived from filename via `_LECTURE_WEEK_MAP`.

2. **Syllabus**: One chunk per week (8 total), each containing the week's
   allowed/forbidden matrix + a 500-char course description prefix.

3. **Assignment solutions**: Each slide becomes one chunk (same as lectures),
   assigned to week 4 (mid-course).

### 1.3 Chunk-level Metadata (Payload Fields)

Every chunk carries these fields in the Qdrant payload:

| Field | Type | Source |
|-------|------|--------|
| `chunk_id` | UUID5 (deterministic) | `_stable_chunk_id()` |
| `content` | str (≤2000 chars) | Slide text |
| `week` | int (1-8) | Filename → `_LECTURE_WEEK_MAP` |
| `category` | `DocCategory` enum | Heuristic classifier |
| `topic` | str | Slide section name |
| `priority` | int (1-3) | Based on `DocCategory` |
| `source_domain` | `SourceDomain` enum | Source type |
| `source_type` | str | `"lecture_slide"`, `"assignment_solution"`, `"syllabus_page"` |
| `page_number` | int or None | Slide page number |
| `parent_chunk_id` | UUID or None | Reserved for future parent-child linking |

### 1.4 Chunk Category Classification

Heuristic (`classify_category()` in `rag/loader.py`):

| Priority | Condition | → Category |
|----------|-----------|------------|
| 1 | Source is `"syllabus"` | `Syllabus` |
| 2 | Source is `"assignment_solution"` | `Supplementary` |
| 3 | Text matches strict-rule keywords (`must`, `always`, `never`, `do not`, `avoid`, `forbidden`, `mandatory`, etc.) | `Strict_Rules` |
| 4 | Everything else | `Pedagogical_Context` |

**Priority mapping** (for reranking):
- Syllabus = 1, Strict_Rules = 1, Pedagogical_Context = 2, Supplementary = 3

### 1.5 Chunk ID Determinism

Chunk IDs use UUID5 with a fixed namespace (`58dbf568-...`) and stable input
parts (filename, page, section, content prefix). This means:

- Re-running the loader produces the **same chunk IDs**.
- Qdrant upsert replaces records in-place (no duplicates).
- Re-indexing after changing **only embedding model** preserves IDs — vectors
  change but the chunk identity remains stable.

### 1.6 What Changes Under Different Chunking Strategies

| Chunking Variable | Impact on Loader | Impact on Index |
|-------------------|------------------|-----------------|
| Slide-level with overlap (e.g. include adjacent slide content) | Minimal: modify `_parse_lecture_json` to append neighbor text | Chunk IDs change → full rebuild needed |
| Sentence-level sliding window | Major: new chunker class needed, different ID scheme | Full rebuild |
| Semantic chunking | Major: embedding-based splitting, different boundaries | Full rebuild |

---


