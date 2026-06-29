# RAG Pipeline

Retrieval-Augmented Generation pipeline for the AI Teaching Assistant.
Provides course-aware context to the **CodingRabbit LLM** during student debugging / study sessions.

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
              (CodingRabbit, course-aware,
               guided by context, powered by LLM)
```

---
## Experimentation 
See `/rag/experiments/experiment_results.md` for details

## File Map

| File | Responsibility |
|------|---------------|
| `schemas.py` | Pydantic contracts: `QueryInput`, `RetrievalResult`, `ChunkPayload`, `ASTFeatures`, `DocCategory`, `SourceDomain`, `CourseSource`, `AssistMode` |
| `query_builder.py` | Fuses student NL + AST features + terminal output → dense embedding query string |
| `retrievers.py` | Five parallel retrievers: syllabus (exact), semantic (vector), rules (vector+filter), guidelines (separate collection), CS50 (separate collection, week-filtered) |
| `reranker.py` | Post-processing: deduplicate → category weighting → MMR diversify → group by category |
| `context_assembler.py` | Formats retrieval results into `[Vector_Database_Results]` block matching CodingRabbit prompt format |
| `pipeline.py` | Orchestrator: `run_retrieval(query) → RetrievalResult` (context only), `generate_response(query, llm) → str` (full TA answer). Routes to MIT14, CS50, or MIT13 collection based on `course_source` |
| `setup_qdrant.py` | Vector DB: create collections, create payload indexes, call loaders to index course materials. Supports Qdrant Cloud (`QDRANT_URL`) or local-on-disk |
| `loader.py` | Loaders: `MIT14Loader` (MIT 6.0014), `CourseMaterialLoader` (MIT 6.0013, legacy), `HarvardNotesLoader` + `HarvardTranscriptsLoader` (CS50), `CppGuidelinesLoader` + `CppReferenceLoader` (C++ knowledge) |
| `runtime.py` | Runtime configuration: Qdrant connection (local/cloud), collection names, embedding model — all driven by environment variables |

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

MIT 6.0014 and Harvard CS50 are completed courses with fixed content. WebLoader's real-time advantage is unnecessary here, while its runtime instability (network, parse failures) directly impacts student experience.

---

## Loader Design

### `rag/loader.py` — Primary loaders

#### `MIT14Loader` — MIT 6.0014 (IAP 2014)

```
raw_data/MIT_2014/
    │
    ├── Lecture*__pdf.json            ──→  _parse_lecture_json()
    │    (parsed PDF blocks, {text,         →  ChunkPayload per block
    │     page_number, has_code})           →  week: Lecture1 → 1, Lecture2 → 2, ...
    │                                       →  classify_category(text, has_code)
    │                                       →  ~11 lecture files, 8 weeks
    │
    ├── ass*__pdf.json                ──→  _parse_assignment_json()
    │    (assignment solutions)             →  category = Supplementary
    │                                       →  week: ass1 → 2, ass2 → 4, ass3 → 6
    │
    └── syllabus__txt.json            ──→  _load_syllabus()
         (or syllabus.txt)                 →  8 ChunkPayload (one per week)
                                           →  category = Syllabus
```

#### `HarvardNotesLoader` + `HarvardTranscriptsLoader` — Harvard CS50

```
raw_data/Harvard/
    │
    ├── cs50_output/notes_json/notes_*.json  ──→  HarvardNotesLoader
    │    (lecture notes, one chunk per           →  ChunkPayload per section
    │     section {heading, text, has_code})     →  week: 0-5
    │                                            →  category: Pedagogical_Context / Strict_Rules
    │
    └── cs50_transcripts/lecture*.json      ──→  HarvardTranscriptsLoader
         (lecture transcripts, one chunk        →  ChunkPayload per paragraph
          per paragraph)                        →  category: Pedagogical_Context
                                                →  min 50 chars, max 3000 chars
```

#### `CourseMaterialLoader` — MIT 6.0013 (legacy)

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

#### MIT 2014 course materials (parsed PDF blocks)

- **One block = one chunk** — parsed from PDF/TXT files in `raw_data/MIT_2014/`. Each block is a natural unit (page/slide equivalent).
- **Content cap**: 2000 chars per chunk.
- **Source prefix**: file label and page number prepended (e.g. `[Lecture1 p.5] Stack contains local variables...`).
- **Week mapping**: `Lecture1` → week 1, `Lecture2` → 2, `Lecture3A`/`Lecture3S` → 3, etc.; `ass1` → week 2, `ass2` → 4, `ass3` → 6.
- **Category**: Same heuristic as MIT 6.0013 — imperative keywords → `Strict_Rules`, assignments → `Supplementary`, syllabus → `Syllabus`, everything else → `Pedagogical_Context`.

#### Course materials (MIT 6.0013 lecture slides, legacy)

- **One slide = one chunk** — natural boundary, already well-scoped. Not merging adjacent slides keeps retrieval granular enough for targeted CodingRabbit nudges.
- **Content cap**: 2000 chars per chunk (lecture slides are rarely text-heavy).
- **Section prefix**: slide `section` field prepended for retrieval context (e.g. `[Today…] Stack contains local variables...`).

#### C++ Core Guidelines

Two chunk types per h3-level rule, matching the embedding window constraint (~512 tokens):

| Chunk type | Fields assembled | ~Tokens | Answers queries like |
|---|---|---|---|
| `rule` | Section + rule_number + title + reason | 80–200 | "Should I use raw pointers?" |
| `rule_example` | Section + rule_number + title + code example | 100–400 | "Show me how to pass parameters correctly" |

Each `rule_example` references its parent `rule` via `parent_chunk_id`, enabling expansion retrieval (fetch the rule summary when a code example matches).

#### C++ Reference (cppreference.com)

Four chunk types per API entry, all fitting within the 512-token embedding window:

| Chunk type | Fields assembled | ~Tokens | Answers queries like |
|---|---|---|---|
| `summary` | name + header + declarations + description | 150–400 | "What is `std::vector`?" |
| `section` | name + section_name + section_content | 80–300 | "What is the complexity of `std::find`?" |
| `example` | name + code example | 100–500 | "Show me an example of `std::sort`" |
| `member` | `parent_name::member_name` + description | 50–150 | "What does `vector::push_back` do?" |

**Why not chunk the full `content` field?** The raw page text (`content`) can be 5–15K tokens — too large for embedding. Splitting into typed sub-chunks means a query about complexity hits the Complexity section directly, while a query about usage hits the summary + example. No overlap, no noise.

**Metadata** on every chunk: `source_domain=CPP_REFERENCE`, `category=GUIDELINE`, `source_type` (summary|section|example|member), `topic` (e.g. `cppref::container::cpp/container/vector::complexity`), `parent_chunk_id` (links sections/examples/members back to their summary).

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

**Example result on MIT 6.0013 (405 chunks, legacy)**:

| Category | Count | Source |
|----------|-------|--------|
| Pedagogical_Context | 383 | Lecture slides (conceptual) |
| Strict_Rules | 8 | Lecture slides (imperative/caution) |
| Syllabus | 8 | One per week |
| Supplementary | 6 | Assignment solutions |

MIT14 and CS50 use the same classification heuristic applied to their respective content formats (PDF blocks for MIT14, markdown sections for CS50).

### Embedding model

`BAAI/bge-large-en-v1.5` (1024-dim, dot product distance)

- Strong retrieval performance in the MIT14/CS50 evaluation runs
- Dot-product similarity is efficient for Qdrant scoring via `query_points` with `score_threshold`
- 1024 dimensions; rebuild Qdrant collections when switching from earlier 768-dim embeddings

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

### One Qdrant instance, three collections (Qdrant Cloud or local-on-disk)

Collection names are configured via environment variables in `rag/runtime.py` (`QDRANT_COLLECTION_MIT14`, `QDRANT_COLLECTION_CS50`, `QDRANT_COLLECTION_GUIDELINES`) with sensible defaults. When `QDRANT_URL` is set, the pipeline connects to Qdrant Cloud (gRPC, port 6334); otherwise it uses local disk-backed Qdrant.

```
Qdrant (single instance, local-on-disk or Qdrant Cloud)
│
├── Collection: mit14_course                  (768-dim, Dot product)
│   ├── Source: MIT 6.0014 (IAP 2014)
│   ├── Content: lecture blocks, syllabus, assignment solutions
│   ├── ~1,500+ chunks (parsed from ~11 lecture PDFs + assignments + syllabus)
│   ├── Payload indexes: week (int), category (keyword),
│   │   priority (int), source_domain (keyword)
│   └── Week range: 1-8, filtered per query
│
├── Collection: cs50_course                   (768-dim, Dot product)
│   ├── Source: Harvard CS50 (2025 Fall)
│   ├── Content: lecture notes (one chunk per section) + transcripts (one chunk per paragraph)
│   ├── Payload indexes: week (int), category (keyword),
│   │   source_domain (keyword)
│   └── Week range: 0-5, filtered per query
│
└── Collection: cpp_knowledge                 (768-dim, Dot product)
    ├── Source: C++ Core Guidelines + cppreference.com (offline HTML book, ~6K pages)
    ├── Content: guidelines rules/examples + API reference (summary, section, example, member)
    ├── ~25,000+ chunks total
    ├── Payload indexes: source_domain (keyword)
    └── Week: always 0 (global, week-agnostic)

Legacy (not currently indexed by default):
  └── Collection: mit13_course — MIT 6.0013 (6.S096), ~405 chunks
```

### Retrieval routing

Each query hits **exactly two collections** — one course collection (MIT14 or CS50) + C++ knowledge. The course collection is selected by `CourseSource`, and the actual Qdrant collection name is resolved at runtime via `rag.runtime` (supporting both local and Qdrant Cloud):

```python
# pipeline.py — run_retrieval()

guidelines = retrieve_guidelines(dense_query)       # → cpp_knowledge (always)

if query.course_source == CourseSource.MIT_14:       # default
    syllabus = retrieve_syllabus(week)               # → mit14_course
    semantic = retrieve_semantic(dense_query, week)  # → mit14_course
    rules    = retrieve_strict_rules(dense_query, week)
elif query.course_source == CourseSource.CS50:
    semantic = retrieve_harvard(dense_query, week)   # → cs50_course
    rules    = retrieve_harvard_rules(dense_query, week)
    syllabus = retrieve_syllabus(week)               # → cs50_course
else:  # CourseSource.MIT_13 (legacy)
    syllabus = retrieve_syllabus(week)               # → mit13_course
    semantic = retrieve_semantic(dense_query, week)  # → mit13_course
    rules    = retrieve_strict_rules(dense_query, week)
```

Results from both collections are merged, weighted, diversified, and formatted into a single `[Vector_Database_Results]` block.

### Qdrant Cloud integration

Collection names are configurable, not hardcoded. `rag/runtime.py` reads environment variables to determine both **where** to connect (local vs. cloud) and **which collections** to query:

```bash
# .env — Qdrant Cloud
QDRANT_URL=https://your-cluster.qdrant.cloud
QDRANT_API_KEY=your-api-key
QDRANT_COLLECTION_MIT14=mit14_course        # optional override
QDRANT_COLLECTION_CS50=cs50_course          # optional override
QDRANT_COLLECTION_GUIDELINES=cpp_knowledge  # optional override
```

When `QDRANT_URL` is set, `create_qdrant_client()` uses gRPC (port 6334) with keepalive; otherwise it falls back to local disk-backed Qdrant at `QDRANT_PATH`.

### Collection independence

- Each collection has its own **vector space**, **HNSW index**, and **payload storage** — no cross-contamination
- Concurrent queries to different collections have **no interference**
- Embedding is computed **once per query** — the same 768-dim vector is used to search both the course and C++ knowledge collections
- GUIDELINES and REFERENCE are stored together in `cpp_knowledge` (week = 0, source_domain distinguishes them)
- Collection names are resolved via `rag.runtime.get_runtime_config()` at query time, not hardcoded — switching between local and Qdrant Cloud requires only environment variables

---

## Architecture

```
                    QueryInput (student message + code AST + terminal + week + mode + course_source)
                        │
                        ├── mode ──→ pipeline.py  ← user-selected, drives all params below
                        ├── course_source ──→ MIT_14 (default), CS50, or MIT_13 (legacy)
                        │
                        ▼
              ┌─────────────────────┐
              │  query_builder.py   │  ← fuse NL, AST hints, terminal error → dense query string
              └─────────┬───────────┘
                        │
                        │     course_source ──→ MIT_14 (default) ───────┐
                        │     course_source ──→ CS50 ───────────────────┐│
                        │     course_source ──→ MIT_13 (legacy) ───────┐││
                        │                                              │││
          ┌─────────────┼──────────────────────────────┐               │││
          ▼                           ▼                 ▼              │││
  retrievers.py               retrievers.py      retrievers.py        │││
  ├─ syllabus(week)          ├─ semantic(...)    ├─ strict_rules(...)  │││
  │  exact payload filter     │  vector search    │  vector + category │││
  │  (all courses)           │  week: exact or   │  filter + threshold│││
  │                          │  cumulative       │  week: exact or    │││
  │                          │  top_k: 8         │  cumulative        │││
  │                          │                   │                    │││
  │     ┌────────────────────┼───────────────────┼────────────────────┘││
  │     │                    │                   │                     ││
  │     │    collection:     │  mit14_course     │  (default)          ││
  │     │                    │                   │                     ││
  │     └────────────────────┼───────────────────┼──────────────────────┘│
  │                          │                   │                      │
  │     ┌────────────────────┼───────────────────┼──────────────────────┐│
  │     │                    │                   │                      ││
  │     │    collection:     │  cs50_course      │  (or mit13_course)   ││
  │     │    retrievers:     │  harvard + harvard_rules                 ││
  │     └────────────────────┼───────────────────┼──────────────────────┘│
  │                          │                   │                      │
  │     ┌────────────────────┼───────────────────┼──────────────────────┐│
  │     │                    │                   │                      ││
  │     │    collection:     │  cpp_knowledge    │  (always queried)    ││
  │     │                    │  week-agnostic    │  guidelines + ref    ││
  │     └────────────────────┴───────────────────┴──────────────────────┘│
  │                                                                     │
          ┌─────────────┴──────────────────────────────┐                │
          ▼                           ▼                 ▼               │
              ┌─────────────────────┐
              │  reranker.py        │
              │  ├─ deduplicate     │  ← by chunk_id
              │  ├─ category_weight │  ← syllabus×1.5  rules×1.6  ped×1.0  guidelines×1.2  supp×1.5
              │  ├─ mmr_diversify   │  ← similarity rerank, λ=1.0
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
              ├─ .guidelines
              ├─ .harvard
              └─ .formatted_context  ← ready-to-inject into TA system prompt
```

---

## Category Weight Design

A single set of weights is applied to all queries regardless of mode:

```python
# reranker.py — CATEGORY_WEIGHTS (default)
Syllabus:            1.5   # course boundaries always critical
Strict_Rules:        1.6
Pedagogical_Context: 1.0
Guideline:           1.2
Supplementary:       1.5
```

### C++-focused weight set

When the query suggests C++ STL/reference material is relevant (determined by
`should_search_cpp()`), the pipeline can route through `CATEGORY_WEIGHTS_CPP`.
The current final tuning keeps that set identical to `CATEGORY_WEIGHTS`:

```python
# reranker.py — CATEGORY_WEIGHTS_CPP
Syllabus:            1.5
Strict_Rules:        1.6
Pedagogical_Context: 1.0
Guideline:           1.2
Supplementary:       1.5
```

### should_search_cpp() trigger

```python
# reranker.py
def should_search_cpp(query_text: str, *, code_raw: str = "") -> bool:
    if "std::" in query_text or "std::" in code_raw:
        return True
    return False
```

In `pipeline.py`, the decision is combined with AST features from the IDE:

```python
search_cpp = (
    should_search_cpp(dense_query, code_raw=query.code_raw)
    or any([query.ast_features.has_pointer, query.ast_features.has_reference,
            query.ast_features.has_new, query.ast_features.has_delete])
)
weights = CATEGORY_WEIGHTS_CPP if search_cpp else CATEGORY_WEIGHTS
```

**Rationale**: Syllabus and Strict Rules form the hard boundaries (Layer 1),
while Pedagogical Context, Guidelines, and Supplementary material remain
competitive enough to survive the final similarity-ranked context when they
directly match the student query. The mode distinction (Homework vs. Study) is
handled through retrieval parameters (`top_k`, `cumulative`, `threshold`)
rather than weights.

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
        "rules_top_k": 3,
        "rules_threshold": 0.55,   # tighter — only highly relevant rules
        "guidelines_top_k": 5,
        "final_k": 5,
    },
    Study Assist: {
        "cumulative": True,        # weeks 1..X (allow review)
        "semantic_top_k": 5,
        "rules_top_k": 3,
        "rules_threshold": 0.45,   # relaxed — more conceptual material
        "guidelines_top_k": 5,
        "final_k": 5,
    },
}
```

| Dimension | Homework Assist | Study Assist |
|-----------|----------------|--------------|
| **Week range** | Current week only | Cumulative weeks 1..X (review allowed, no spoilers) |
| **top_k** | Few and precise (5) | Cumulative but still capped (5) |

---

## Source Scoping: Domain + Week Limits + Course Routing

### Two-tier retrieval: course material + external references

The retriever handles two kinds of content with different week semantics:

```
                         week field      retrieval rule
                         ──────────      ───────────────
Course material          week = 1..8  →  week ∈ [1, current_week]
  (MIT14 lecture blocks, week = 0..5  →  week ∈ [0, current_week]
   CS50 notes/transcripts,
   syllabus, rules)

External references      week = 0     →  always included (week-agnostic)
  (CppCoreGuidelines,
   cppreference)
```

### Course routing: `CourseSource` enum

MIT14 and CS50 are **parallel, mutually exclusive** course sources. MIT13 is a legacy option. The `course_source` field in `QueryInput` determines which course collection is queried:

```python
class CourseSource(str, Enum):
    MIT_13 = "mit13"    # MIT 6.0013 — legacy
    MIT_14 = "mit14"    # MIT 6.0014 (IAP 2014) — default
    CS50 = "cs50"       # Harvard CS50
```

```python
# Default: MIT 2014
result = run_retrieval(QueryInput(..., week=3))
# → queries mit14_course + cpp_knowledge

# Explicit Harvard CS50
result = run_retrieval(QueryInput(..., week=2, course_source=CourseSource.CS50))
# → queries cs50_course + cpp_knowledge

# Legacy MIT 6.0013
result = run_retrieval(QueryInput(..., week=3, course_source=CourseSource.MIT_13))
# → queries mit13_course + cpp_knowledge
```

### Why separate collections instead of a single shared one

| Approach | Pros | Cons |
|----------|------|------|
| **Single collection** with `source_domain` filter | Simpler code, one index | Week semantics conflict (MIT14 1-8 vs CS50 0-5); cross-contamination risk; harder to rebuild independently |
| **Separate collections** (current) | Clean isolation; independent lifecycle (rebuild, delete); no cross-contamination; different payload index strategies | Slightly more code (but mostly mechanical) |

For multiple courses with different syllabi, week structures, and content domains, separate collections provide cleaner separation. The `CourseSource` enum makes the routing explicit and extensible (add `STANFORD`, `BERKELEY`, etc. by adding an enum value + collection + loader + retriever + runtime config).

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
    CPP_REFERENCE = "cpp_reference"               # cppreference.com API reference, week-agnostic
    HARVARD_CS50 = "harvard_cs50"                  # Harvard CS50, parallel to MIT

class CourseSource(str, Enum):
    MIT_13 = "mit13"    # MIT 6.0013 (6.S096) — legacy
    MIT_14 = "mit14"    # MIT 6.0014 (IAP 2014) — default
    CS50 = "cs50"       # Harvard CS50
```

Adding a new course source (e.g. `STANFORD_CS107`) is five steps:
1. Add `SourceDomain` enum value
2. Add `CourseSource` enum value
3. Write a loader (implement `load_all() → list[ChunkPayload]`)
4. Add ensure/upsert functions for the new collection in `setup_qdrant.py`
5. Add collection to `rag/runtime.py` (`RagRuntimeConfig` + `collection_for()`)
6. Add retriever functions + route in `pipeline.py`

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

This is not a bug — it's the intended design for a CodingRabbit:

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
│  Prompt rule: Applied via CodingRabbit questioning                    │
│  (generate_dataset.py Rule 11, pipeline.py Rule 1-2)             │
└──────────────────────────────────────────────────────────────────┘
```

### Why this design for a CodingRabbit

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
# Local disk-backed Qdrant
rm -rf qdrant_local_data
PYTHONPATH=. python rag/setup_qdrant.py

# Index a specific course only
PYTHONPATH=. python rag/setup_qdrant.py --course mit14   # MIT 2014 only
PYTHONPATH=. python rag/setup_qdrant.py --course cs50    # CS50 only
PYTHONPATH=. python rag/setup_qdrant.py --course cpp     # C++ knowledge only

# Qdrant Cloud (set env vars first)
QDRANT_URL=https://your-cluster.qdrant.cloud \
QDRANT_API_KEY=your-key \
PYTHONPATH=. python rag/setup_qdrant.py
```

This loads all course materials from `raw_data/` (MIT 2014 + Harvard CS50 + C++ knowledge), embeds them with `BAAI/bge-large-en-v1.5`, and indexes into three Qdrant collections (configurable via `rag/runtime.py`).

### 4. Retrieve context

```python
from rag import run_retrieval, QueryInput, ASTFeatures, AssistMode, CourseSource

# MIT 2014 (default)
result = run_retrieval(QueryInput(
    student_message="Why does my program crash?",
    code_raw="int* p; *p = 5;",
    terminal_output="Segmentation fault (core dumped)",
    exit_code=139,
    week=3,
    mode=AssistMode.HOMEWORK_ASSIST,
    ast_features=ASTFeatures(has_pointer=True),
    # course_source defaults to CourseSource.MIT_14
))

# Harvard CS50 (explicit)
result = run_retrieval(QueryInput(
    student_message="Why does my program crash?",
    code_raw="int* p; *p = 5;",
    terminal_output="Segmentation fault (core dumped)",
    exit_code=139,
    week=2,
    mode=AssistMode.HOMEWORK_ASSIST,
    course_source=CourseSource.CS50,
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
