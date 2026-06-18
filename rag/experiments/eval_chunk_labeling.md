# Chunk Labeling for RAG Evaluation

`labeling_chunks.py` — GPT-5-mini golden chunk labeling for retrieval experiments (Harvard CS50).

---

## 1. Data Sources

| Source | Chunks | Weeks | Loader |
|--------|--------|-------|--------|
| Harvard CS50 Notes | 87 | 0-5 | `load_harvard_notes` |
| Harvard Transcripts | 2,477 | 1-5 | `load_harvard_transcripts` |
| C++ Core Guidelines | ~200 | 0 | `load_cpp_guidelines` |
| **Total** | **~2,764** | | |

---

## 2. Query Sampling

**Weeks 1-5 evenly stratified**, target 200 queries (40 per week). If a week has fewer records than the per-week quota, it caps at available.

```python
# Weeks 1-5, evenly split, target=200
by_week[w] → random.sample(40) per active week
```

Default `--sample-size 200`. Override with `--sample-size N`.

---

## 3. Candidate Pool — Week-Priority

BM25 retrieval with a **two-tier split** to guarantee current-week coverage:

### Non-AST queries (standard)

| Tier | Source | top_k |
|------|--------|-------|
| Tier 1 | Current week (`week == query.week`) | 30 |
| Tier 2 | History (`week < query.week`, incl. week 0 guidelines) | 30 |
| **Total** | | **~60** |

### AST queries (`AST_Metadata:` present)

| Tier | Source | top_k |
|------|--------|-------|
| Tier 1 | Week 0 (C++ Core Guidelines) | **40** |
| Tier 2 | Weeks 1..query.week (notes + transcripts) | 20 |
| **Total** | | **~60** |

AST queries give guidelines heavy weight for rule lookup. Non-AST splits evenly between current and history.

### Week filtering

Only chunks with `week <= query.week` are eligible — future material is excluded.

Retrieval query: extracts `[Student_Question]` tag if present, otherwise uses first 500 chars of student message + first 1500 chars of golden answer.

---

## 4. GPT-5-mini Labeling

| Parameter | Value |
|-----------|-------|
| Model | `gpt-5-mini` |
| Seed | 42 |
| Max completion tokens | 2000 |

### Prompt (abbreviated)

```
You are labeling which course documents are relevant...

## Student Question
{query}

## Expected TA Response (Golden Answer)
{golden}

## Candidate Document Chunks
[chunk_id] [Week W, category] {content_first_300_chars}

## Task
Return a JSON array of chunk IDs...

Guidelines:
- Include chunks whose content is directly referenced or implied by the golden answer.
- Include chunks that provide necessary conceptual background.
- Prefer recall over precision. When uncertain, INCLUDE the chunk.

Output ONLY a JSON array with no other text. Do not explain your reasoning.
Format: ["chunk_id_1", "chunk_id_2", ...]
```

### Output Parsing

Multi-layer fallback in `_parse_label_output`:

1. Parse entire string as JSON array
2. Regex-extract embedded `[...]` array, then parse
3. UUID regex fallback (`[a-f0-9]{8}-...`)
4. Return empty `[]` + print WARNING with raw output prefix

---

## 5. Output Files

| File | Content |
|------|---------|
| `eval_queries_cs50.jsonl` | 200 sampled queries (weeks 1-5) |
| `golden_labels_cs50.json` | `{query_id: [chunk_id, ...]}` |
| `labeling_report_cs50.json` | Per-query stats (pool_size, golden_ratio) |
| `outputs/` | All local under `rag/experiments/outputs/` |

---

## 6. Usage

```bash
python labeling_chunks.py                      # full run (200 queries, weeks 1-5)
python labeling_chunks.py --dry-run             # pool construction only, skip LLM
python labeling_chunks.py --sample-size 100     # custom sample size
```
