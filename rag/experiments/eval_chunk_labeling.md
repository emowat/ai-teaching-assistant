# Chunk Labeling for RAG Evaluation

`labeling_chunks.py` — GPT-5-mini golden chunk labeling for retrieval experiments.

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

Only **weeks 1 and 5** are sampled. Other weeks are excluded because their topics (Scratch, Python, web) are less relevant to the C++-focused synthetic query dataset.

| Week | Queries | Topic |
|------|---------|-------|
| 1 | 40 | C Basics |
| 5 | ~20 | Data Structures |
| **Total** | **60** | |

```python
sample_queries(records, target=60, seed=42):
    week 1 → random.sample 40
    week 5 → random.sample ~20  # fill to target
```

Default `--sample-size 60`. Override with `--sample-size N`.

---

## 3. Candidate Pool

Flat BM25 retrieval over all ~2,764 chunks. No embedding model dependency.

| Query type | pool size |
|------------|-----------|
| Standard | 50 |
| AST query (`AST_Metadata:` present) | 80 |

Retrieval query: `[Student_Question]` tag extraction + golden answer (first 1500 chars).

---

## 4. GPT-5-mini Labeling

| Parameter | Value |
|-----------|-------|
| Model | `gpt-5-mini` |
| Temperature | 1 |
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

AST queries additionally include: "Rewrite this question using the accompanying AST data as a query for C++ reference material."

### Output Parsing

Multi-layer fallback in `_parse_label_output`:

1. Parse entire string as JSON array
2. Regex-extract embedded `[...]` array from text, then parse
3. UUID regex fallback (`[a-f0-9]{8}-...`)
4. Return empty `[]` + print WARNING with raw output prefix

---

## 5. Labels per Query

| Query | Pool | Typical labels |
|-------|------|----------------|
| Week 1, standard | 50 | 2-10 |
| Week 5, AST | 80 | 2-10 |

Most queries return 2-10 relevant chunks, depending on how many sources the golden answer references.

---

## 6. Output Files

| File | Content |
|------|---------|
| `eval_queries.jsonl` | 60 sampled queries |
| `golden_labels.json` | `{query_id: [chunk_id, ...]}` |
| `labeling_report.json` | Per-query stats (pool_size, golden_ratio, labels_openai) |

---

## 7. Usage

```bash
python labeling_chunks.py                    # full run (60 queries, weeks 1+5)
python labeling_chunks.py --dry-run           # pool construction only, skip LLM
python labeling_chunks.py --course mit        # MIT course mode
python labeling_chunks.py --sample-size 30    # custom sample size
```
