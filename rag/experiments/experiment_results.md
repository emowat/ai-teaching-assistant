# RAG Retrieval Parameter Tuning

## Step 1 embeddings, top_k

The RAG pipeline retrieves course material and external references (C++ Core
Guidelines, cppreference.com) to ground the TA's responses. This experiment
evaluates retrieval quality across different embedding models and `top_k`
configurations to find the optimal balance of recall, latency, and context size.

### Evaluation sessions

Not all session types require course material retrieval (e.g. `Out-of-Scope`,
`gdb_request`, `terminal_help`). Overall recall is therefore not the target
metric. The metrics that matter:

| Session type          | Retrieval expectation                        | Priority |
|-----------------------|----------------------------------------------|----------|
| `study_assist`        | Should retrieve correct course content consistently | High |
| `homework_api_query`  | Should have very high recall (API/knowledge lookups) | Critical |

### Tie-break rule

Among configurations with similar quality, prefer the smaller `top_k` to reduce
latency and context size sent to the LLM.

---

## Setup

- **Embedding models** evaluated: `BAAI/bge-large-en-v1.5`, `all-MiniLM-L6-v2` ("MiniLM"), `sentence-transformers/multi-qa-mpnet-base-dot-v1` ("BGE-large"), and `text-embedding-3-small`
- **Parameters swept**: `semantic_top_k` (5, 8), `rules_top_k` (3, 5), `guidelines_top_k` (5, 8)
- **Collection**: MIT 6.0013 `course_knowledge` + `cpp_guidelines`
- **Metric**: Mean recall across `homework_api_query` + `study_assist` sessions

---

## Results

### Top configurations

| Rank | Embedding                   | top_k | rules | guidelines | Homework + Study Recall |
|------|-----------------------------|------:|------:|-----------:|------------------------:|
| **1** | **BAAI/bge-large-en-v1.5** | **5** | **3** |      **5** |                **0.527** |
| 2    | MiniLM                      |     8 |     3 |          5 |                    0.517 |
| 3    | BGE-large                   |     8 |     3 |          5 |                    0.509 |
| 4    | BGE-large                   |     5 |     5 |          8 |                    0.502 |
| 5    | BGE-large                   |     8 |     5 |          5 |                    0.496 |

---

## Analysis

### 1. Embedding model

**Winner: `BAAI/bge-large-en-v1.5`**

Per-session recall:

| Model    | Homework API | Study Assist |
|----------|-------------:|-------------:|
| BGE-large (BAAI) | 0.645 | 0.396 |
| MiniLM   | 0.604 | 0.420 |

- MiniLM is slightly better on `study_assist` (+0.024).
- BGE-large is **substantially** better on `homework_api_query` (+0.041), which is the more retrieval-sensitive trigger.
- **Decision**: BGE-large (BAAI).

---

### 2. `semantic_top_k`

Comparing BGE-large at fixed `rules=3, guidelines=5`:

| top_k | Homework + Study Recall |
|------:|------------------------:|
|     5 |                   0.527 |
|     8 |                   0.509 |

Increasing retrieval depth **reduced** performance — more results introduce noise
and dilute the most relevant chunks in the context window.

**Decision**: `semantic_top_k = 5`.

---

### 3. `rules_top_k`

Comparing BGE-large at `top_k=5`:

| rules_top_k | Homework + Study Recall |
|------------:|------------------------:|
|           3 |                   0.527 |
|           5 |                   0.426 |

A large drop (-0.101). Retrieving more strict-rule chunks introduces noise that
pushes useful pedagogical material lower in the context.

**Decision**: `rules_top_k = 3`.

---

### 4. `guidelines_top_k`

Comparing BGE-large at `top_k=5, rules=3`:

| guidelines_top_k | Homework + Study Recall |
|-----------------:|------------------------:|
|                5 |                   0.527 |
|                8 |                   0.484 |

Again, more is worse (-0.043). Fewer, higher-quality guideline chunks outperform
a larger, noisier set.

**Decision**: `guidelines_top_k = 5`.

---

## Best combination results

### Configuration

| Parameter            | Value                       |
|----------------------|-----------------------------|
| `embedding_model`    | `BAAI/bge-large-en-v1.5`    |
| `semantic_top_k`     | `5`                         |
| `rules_top_k`        | `3`                         |
| `guidelines_top_k`   | `5`                         |

### Recall metrics

| Metric                  | Score  |
|-------------------------|-------:|
| `important_recall_mean` | 0.5274 |
| `homework_api_recall`   | 0.6446 |
| `study_assist_recall`   | 0.3955 |

`important_recall_mean` is the combined recall across the two session types that
depend on retrieval quality (`homework_api_query` + `study_assist`). All other
session types (`Out-of-Scope`, `gdb_request`, `terminal_help`) are excluded as
they are expected to retrieve little or no course material.

### Rationale

- **`BAAI/bge-large-en-v1.5`** — highest recall on retrieval-critical sessions.
- **`semantic_top_k = 5`** — no evidence that 8 or 10 improves quality; lower latency and less context.
- **`rules_top_k = 3`** — increasing to 5 consistently hurts retrieval (-0.101).
- **`guidelines_top_k = 5`** — better than 8 while retrieving fewer irrelevant guideline chunks.

---

## Key takeaways

1. **More retrieval is not always better.** Across all three parameters,
   increasing `top_k` reduced recall — additional results act as noise rather
   than supplementary signal. Keeping retrievals tight and high-quality
   outperforms broad, noisy fetches.

2. **Embedding model matters most for API-lookup sessions.**
   `BAAI/bge-large-en-v1.5` outperforms alternatives on the session type where
   retrieval quality is most critical (`homework_api_query`).

3. **Guidelines and rules are best kept minimal.** Both `rules_top_k` and
   `guidelines_top_k` showed diminishing returns past 3–5, likely because these
   collections are smaller and less diverse than the main course material pool.

## Step 2 Rerank strategy
Adding `MMR` to `similarity`
- Helps: when your corpus has many near-duplicate chunks about the same topic. MMR prevents 5 chunks all saying the same thing, and instead surfaces a broader set of claims → better recall.
- Hurts: when the relevant chunks for a question are genuinely similar to each other (e.g., multiple heap management examples all use similar vocabulary). MMR will deprioritize them in favor of diverse-but-irrelevant chunks → worse recall.

| rerank_strategy      | important_recall            |
|----------------------|-----------------------------|
| `similarity`         | 0.4193                      |
| `mmr_0.9`            | 0.3693                      |
| `mmr_0.7`            | 0.3936                      |
| `mmr_0.5`            | 0.3827                      |

## Step 3 Mode Weights
See `best results → s3://codingrabbit-data-dev/prepared/rag/experiments/outputs/eval_results_mit14_mode_v2.json` for details
|	|  |
| Category             | Weight                      |
|----------------------|-----------------------------|
| `Syllabus`           | 1.5                         |
| `Strict_Rules`       | 1.6                         |
| `Pedagogical_Context`| 1.0                         |
| `Guideline`          | 1.2                         |
| `Supplementary`      | 1.5                         |

## Next steps
- rules_threshold and guidelines_threshold
- add overlap=1