# RAG Pipeline

Retrieval-Augmented Generation pipeline for the AI Teaching Assistant.
Provides course-aware context to the **Socratic TA LLM** during student debugging / study sessions.

---

## Visualizing the Full Chain

```
                     Student Message
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
    code_raw        terminal_output    AST features
          │               │               │
          └───────────────┼───────────────┘
                          │
                          ▼
                  query_builder.py
                          │
                          ▼
          ┌───────────────────────────────┐
          │         RETRIEVER             │
          │                               │
          │  Qdrant payload filters:       │
          │  ├── week ∈ [1, X]            │  ← no future material
          │  ├── source_domain ∈ [...]    │  ← scoped to course sources only
          │  └── category filter           │
          │                               │
          │  → returns docs from          │
          │    course material only        │
          └───────────────┬───────────────┘
                          │
                          ▼ format_docs
                          │
          ┌───────────────┼───────────────┐
          │                               │
          ▼                               ▼
    [Vector_Database_Results]        rag_prompt
    (Layer 1 + 2: course context)    (instructs how to use
          │                          layers 1, 2, and 3)
          └───────────────┬───────────────┘
                          │
                          ▼
                  cohere_chat_model
                  (Layer 3: pre-trained C++ knowledge
                   available, but constrained by prompt)
                          │
                          ▼
                    TA Response
              (Socratic, course-aware,
               guided by context, powered by LLM)
```

---

## File Map

| File | Responsibility |
|------|---------------|
| `schemas.py` | Pydantic contracts: `QueryInput`, `RetrievalResult`, `ChunkPayload`, `ASTFeatures`, `DocCategory`, `SourceDomain`, `AssistMode` |
| `query_builder.py` | Fuses student NL + AST features + terminal output → dense embedding query string |
| `retrievers.py` | Three parallel retrievers: syllabus (exact filter), semantic (vector), rules (vector + category filter + threshold) |
| `reranker.py` | Post-processing: deduplicate → category weighting → MMR diversify → group by category |
| `context_assembler.py` | Formats retrieval results into `[Vector_Database_Results]` block matching Socratic TA prompt format |
| `pipeline.py` | Orchestrator: `run_retrieval(query) → RetrievalResult` (context only), `generate_response(query, llm) → str` (full TA answer) |
| `setup_qdrant.py` | Vector DB: create collection, create payload indexes, call loader to index course materials |
| `loader.py` | Course material loader: reads from `raw_data/` (future S3) → chunks by slide → heuristic classification → outputs `ChunkPayload` list |

---

## Data Ingestion Strategy

### Decision: Offline Pre-processing

Course materials are parsed, chunked, embedded, and indexed **once at build time** — not at query time.

```
                         BUILD TIME (once)              RUNTIME (every query)
                         ────────────────               ──────────────────────

S3 (raw_data/) ──→ data_ingestion/ ──→ Qdrant index ──→ rag pipeline ──→ TA response
    (future)         parse + chunk +      (persistent)       vector search      (fast)
                     embed + classify                          only (~50ms)
```

### Why not WebLoader / runtime loading

| | Offline Pre-processing | WebLoader (runtime) |
|---|---|---|
| **Stability** | Static index snapshot, reproducible results | S3 timeout / parse failure affects every query |
| **Latency at query** | Vector search only (~50ms) | Plus download + parse + chunk + encode (seconds) |
| **Predictability** | All students see the same index | Different states loaded at different times |
| **S3 fit** | Pull from S3 once at build time | Pull from S3 every query |
| **Best for** | **Fixed content**: lecture slides, assignment solutions, syllabus | Frequently changing documents |

MIT OCW 6.S096 is a completed course (391 slides), content is fixed. WebLoader's real-time advantage is unnecessary here, while its runtime instability (network, parse failures) directly impacts student experience.

---

## Loader Design

### `rag/loader.py` — `CourseMaterialLoader`

```
raw_data/
    │
    ├── lecture_text/*.json          ──→  _load_lecture_slides()
    │    (391 slides, {page, section,     →  ChunkPayload per slide
    │     text, has_code})                →  week = lecture_N → N
    │                                     →  classify_category(text, has_code)
    │
    ├── mit_ocw_output/syllabus.txt  ──→  _load_syllabus()
    │    (course policies)                →  8 ChunkPayload (one per week)
    │                                     →  category = Syllabus
    │
    └── lecture_text/assignment*     ──→  _load_assignment_solutions()
         _solution.json                  →  ChunkPayload per page
         (reference solutions)           →  category = Supplementary
```

### Chunking strategy

- **One slide = one chunk** — natural boundary, already well-scoped. Not merging adjacent slides keeps retrieval granular enough for targeted Socratic nudges.
- **Content cap**: 2000 chars per chunk (lecture slides are rarely text-heavy).
- **Section prefix**: slide `section` field prepended for retrieval context (e.g. `[Today…] Stack contains local variables...`).

### Category classification heuristic

```python
# Priority-ordered rules in classify_category():
1. source == "syllabus"           → Syllabus
2. source == "assignment"         → Supplementary
3. Text matches strict-rule patterns → Strict_Rules
   (must, always, never, remember to, ensure that,
    be careful, do not, avoid, forbidden, mandatory)
4. Everything else                → Pedagogical_Context
```

**Result on MIT OCW 6.S096 (405 chunks)**:

| Category | Count | Source |
|----------|-------|--------|
| Pedagogical_Context | 383 | Lecture slides (conceptual) |
| Strict_Rules | 8 | Lecture slides (imperative/caution) |
| Syllabus | 8 | One per week |
| Supplementary | 6 | Assignment solutions |

### Embedding model

`sentence-transformers/multi-qa-mpnet-base-dot-v1` (768-dim, dot product distance)

- Trained specifically for question-answering retrieval — aligns with student → TA query pattern
- Dot-product similarity is efficient for Qdrant scoring via `query_points` with `score_threshold`
- 768 dimensions = faster indexing and search than 1024-dim alternatives

### S3 migration path

When `raw_data/` moves to S3:

```python
# Future: S3CourseMaterialLoader extends the same interface
class S3CourseMaterialLoader(CourseMaterialLoader):
    def __init__(self, bucket: str, prefix: str):
        self.s3 = boto3.client("s3")
        # download to temp dir, then delegate to parent
```

The loader's interface (`load_all() → list[ChunkPayload]`) stays the same — `setup_qdrant.py` doesn't change.

---

## Data Store

- **Qdrant local mode** — `qdrant_local_data/` directory, no Docker required
- **Collection**: `course_knowledge` (768-dim, **dot product**)
- **Payload indexes**: `week` (int), `category` (keyword), `priority` (int), `source_domain` (keyword)
- **Embedding model**: `sentence-transformers/multi-qa-mpnet-base-dot-v1`
- **Indexed**: 405 chunks (391 slides + 8 syllabus + 6 assignment solutions) from MIT OCW 6.S096

---

## Architecture

```
                    QueryInput (student message + code AST + terminal + week + mode)
                        │
                        ├── mode ──→ pipeline.py  ← user-selected, drives all params below
                        │
                        ▼
              ┌─────────────────────┐
              │  query_builder.py   │  ← fuse NL, AST hints, terminal error → dense query string
              └─────────┬───────────┘
                        │
          ┌─────────────┼─────────────────────────────┐
          ▼                           ▼                ▼
  retrievers.py               retrievers.py     retrievers.py
  ├─ syllabus(week)          ├─ semantic(...)   ├─ strict_rules(...)
  │  exact payload filter     │  vector search   │  vector + category
  │                           │  week: exact or  │  filter + threshold
  │                           │  cumulative      │  week: exact or
  │                           │  top_k: 5 or 8   │  cumulative
          │                           │                │
          └─────────────┬─────────────┴────────────────┘
                        ▼
              ┌─────────────────────┐
              │  reranker.py        │
              │  ├─ deduplicate     │  ← by chunk_id
              │  ├─ category_weight │  ← HOME: rules×1.8  STUDY: ped×1.5
              │  ├─ mmr_diversify   │  ← Jaccard token similarity, λ=0.7
              │  └─ group_by_category│
              └─────────┬───────────┘
                        │
                        ▼
              ┌─────────────────────┐
              │  context_assembler  │  ← format [Vector_Database_Results] block
              └─────────┬───────────┘
                        │
                        ▼
              RetrievalResult
              ├─ .syllabus
              ├─ .strict_rules
              ├─ .pedagogical
              ├─ .supplementary
              └─ .formatted_context  ← ready-to-inject into TA system prompt
```

---

## Category Weight Design

Weights are **mode-aware** — selected at query time based on user-chosen mode:

```python
# reranker.py — MODE_WEIGHTS
Homework Assist:
    Syllabus:            1.5   # course boundaries always critical
    Strict_Rules:        1.8   # rules are the most important during debugging
    Pedagogical_Context: 0.9
    Supplementary:       0.3   # dampen distractions

Study Assist:
    Syllabus:            1.5
    Strict_Rules:        1.0
    Pedagogical_Context: 1.5   # concepts are the focus in learning mode
    Supplementary:       0.8   # extra material is valuable for learning
```

**Rationale**: The Socratic TA needs "what NOT to do" boundaries (Syllabus Forbidden + Strict Rules) during debugging, but concept explanations take priority when a student is studying.

---

## Mode Distinction in RAG

### Mode is user-selected, not auto-classified

The student explicitly picks **Homework Assist** or **Study Assist** before sending their query. `QueryInput.mode` flows directly into `pipeline.py`, which selects retrieval parameters:

```python
# pipeline.py — MODE_PARAMS
MODE_PARAMS = {
    Homework Assist: {
        "cumulative": False,       # current week only
        "semantic_top_k": 5,
        "rules_threshold": 0.55,   # tighter — only highly relevant rules
        "final_k": 5,
    },
    Study Assist: {
        "cumulative": True,        # weeks 1..X (allow review)
        "semantic_top_k": 8,
        "rules_threshold": 0.45,   # relaxed — more conceptual material
        "final_k": 8,
    },
}
```

| Dimension | Homework Assist | Study Assist |
|-----------|----------------|--------------|
| **Week range** | Current week only | Cumulative weeks 1..X (review allowed, no spoilers) |
| **Category weights** | Strict_Rules ↑↑, Supplementary ↓ | Pedagogical ↑↑, Supplementary ↑ |
| **top_k** | Few and precise (5) | More context (8) |

---

## Source Scoping: Domain + Week Limits

### Two-tier retrieval: course material + external references

The retriever handles two kinds of content with different week semantics:

```
                         week field      retrieval rule
                         ──────────      ───────────────
Course material          week = 1..8  →  week ∈ [1, current_week]
  (lecture slides,
   syllabus, rules)

External references      week = 0     →  always included (week-agnostic)
  (CppCoreGuidelines,
   future: cppreference)
```

This is enforced via a single Qdrant payload filter with conditional week matching:

```python
# retrievers.py — _semantic_filter
course_condition = (
    FieldCondition(key="week", range=Range(gte=1, lte=week))  # Study Assist (cumulative)
    if cumulative
    else FieldCondition(key="week", match=MatchValue(value=week))  # Homework Assist (exact)
)
return Filter(
    must=[
        Filter(should=[
            course_condition,
            FieldCondition(key="week", match=MatchValue(value=0)),  # external refs always
        ]),
    ],
    must_not=[FieldCondition(key="category", match=MatchValue(value="Syllabus"))],
)
```

### source_domain whitelist

All indexed content must belong to an allowed domain:

```python
# schemas.py
class SourceDomain(str, Enum):
    MIT_OCW_LECTURE = "mit_ocw_lecture"
    MIT_OCW_SYLLABUS = "mit_ocw_syllabus"
    MIT_OCW_ASSIGNMENT = "mit_ocw_assignment"
    CPP_CORE_GUIDELINES = "cpp_core_guidelines"  # external, week-agnostic
```

Adding a new source (e.g. `cppreference.com`) is two steps:
1. Add `SourceDomain` enum value
2. Ingest its content with `week = 0` and the appropriate `source_domain`

### Why `week = 0` instead of a separate field

The alternative would be a `knowledge_tier` field (`course` vs `reference`) alongside `week`. Using `week = 0` is simpler:

| Approach | Pros | Cons |
|----------|------|------|
| `week = 0` sentinel | No schema change; one filter handles both | Slightly implicit semantics |
| `knowledge_tier` field | Explicit intent; extensible to more tiers | Another field, index, and filter combination |

For the current scale (2 tiers), the sentinel approach is sufficient.

---

## RAG + Pre-trained Knowledge: Three-Layer Architecture

### The core question

> "If the retriever only fetches from course material ≤ week X, can the LLM still use its pre-trained knowledge?"

**Yes.** Retrieval filters constrain the **context**, not the **model weights**. The LLM still has full access to its pre-trained C++ knowledge. What changes is how the prompt instructs it to use that knowledge.

This is not a bug — it's the intended design for a Socratic TA:

```
┌──────────────────────────────────────────────────────────────────┐
│  LAYER 1: Authoritative (Qdrant: Syllabus + Strict_Rules)       │
│  Role: Hard constraints                                          │
│  Example: "Week 3 FORBIDS new/delete"                            │
│  Prompt rule: MUST obey Forbidden concepts                       │
│  (generate_dataset.py Rule 12, pipeline.py Rule 4)               │
│                                                                  │
│  LAYER 2: Supplementary (Qdrant: Pedagogical + Supplementary)   │
│  Role: Soft guidance                                             │
│  Example: "Uninitialized pointers hold garbage addresses"         │
│  Prompt rule: Use if helpful, ignore if irrelevant               │
│  (generate_dataset.py Rule 12, pipeline.py Rule 5)               │
│                                                                  │
│  LAYER 3: General C++ (LLM pre-trained weights)                  │
│  Role: Reasoning backbone                                         │
│  Example: "Segfault typically means...", "GDB backtrace shows..." │
│  Prompt rule: Applied via Socratic questioning                    │
│  (generate_dataset.py Rule 11, pipeline.py Rule 1-2)             │
└──────────────────────────────────────────────────────────────────┘
```

### Why this design for a Socratic TA

A pure "closed-book" RAG (only use context, no pre-trained knowledge) would be wrong here because:

| Scenario | If closed-book | With Layer 3 (current design) |
|----------|---------------|-------------------------------|
| Student asks "what's a pointer?" | Can only repeat the syllabus definition — no deeper reasoning | Can explain in the LLM's own words, then guide back to their code |
| Syllabus doesn't mention segfaults | LLM can't help because context lacks it | LLM reasons from pre-trained knowledge: "You're dereferencing an uninitialized pointer" |
| Student's bug is a logic error | Context has no matching content | LLM spots `if (x = 5)` → "Did you mean `==`?" |

The **only** case where Layer 3 should be suppressed is when it **conflicts** with Layer 1. That's already handled:

```
SYSTEM PROMPT (generate_dataset.py, Rule 12):
"If a [Retrieved_Syllabus_Chunk] is present, you MUST obey its Forbidden concepts."
```

### When to go closed-book (future option)

If Study Assist mode needs strict course-material-only answers:

```python
# In rag_prompt, conditionally add:
STUDY_ASSIST_CLOSED_BOOK = """
Mode: Study Assist (Course-Material-Only)
Answer ONLY from the [Vector_Database_Results] below.
If the context lacks information, say "This isn't covered in the course materials."
Do NOT draw on external knowledge beyond the provided context.
"""
```

This would be a **prompt-level switch**, not a model change — same model, different instruction.

---

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Set your Cohere API key

```bash
# Create a .env file (never commit — it's in .gitignore)
echo 'COHERE_API_KEY=your-key-here' > .env
```

In Python:

```python
import os
from dotenv import load_dotenv
load_dotenv()

# Now use it anywhere:
# cohere_chat_model = ChatCohere(cohere_api_key=os.environ["COHERE_API_KEY"])
```

`.env` is the safest local approach — it's in `.gitignore`, never leaves your machine. For production, use environment variables injected by your deployment platform (AWS Secrets Manager, GitHub Secrets, etc.).

### 3. Build the Qdrant index

```bash
rm -rf qdrant_local_data
PYTHONPATH=. python rag/setup_qdrant.py
```

This loads all MIT OCW 6.S096 course materials (391 slides + syllabus + assignment solutions) from `raw_data/`, embeds them with `multi-qa-mpnet-base-dot-v1`, and indexes 405 chunks into `qdrant_local_data/`.

### 4. Retrieve context

```python
from rag import run_retrieval, QueryInput, ASTFeatures, AssistMode

result = run_retrieval(QueryInput(
    student_message="Why does my program crash?",
    code_raw="int* p; *p = 5;",
    terminal_output="Segmentation fault (core dumped)",
    exit_code=139,
    week=3,
    mode=AssistMode.HOMEWORK_ASSIST,
    ast_features=ASTFeatures(has_pointer=True),
))

print(result.formatted_context)
# [Retrieved_Syllabus_Chunk]
# Week: 3 - Pointers & Memory
# ...
# [Strict_Rules]
# ...
# [Pedagogical_Context]
# ...
```

### 5. Generate the TA response (Layer 1+2+3 in one call)

```python
from langchain_cohere import ChatCohere
from rag import generate_response

cohere_chat_model = ChatCohere(cohere_api_key=os.environ["COHERE_API_KEY"])

answer = generate_response(query, llm=cohere_chat_model)
print(answer)
# "Have you checked what value your pointer `p` holds before you dereference it?"
```

`generate_response()` runs retrieval → prompt assembly → Cohere call in one step. The Cohere model brings **Layer 3** (pre-trained C++ knowledge), constrained by **Layer 1** (Syllabus Forbidden) and optionally guided by **Layer 2**.

Need just the context without calling the LLM? Use `run_retrieval()` instead.
