# Follow-up Contextualization for Retrieval

Multi-turn follow-ups like *"How about now"*, *"Check the code"*, or *"-127"* carry
no standalone retrieval signal. Generation resolves them by consuming the full
message history natively, but retrieval is single-turn: production embedded the
raw follow-up, which retrieved wrap-up / memory / boilerplate noise instead of
the topic the student was actually working on.

This change makes retrieval **contextualize low-signal follow-ups** by folding in
recent conversation history, while leaving self-sufficient questions untouched.

---

## Part 1 — How `query_builder` changed

### 1.1 The seam: `retrieval_query`

Retrieval stays stateless. The backend builds a standalone query string from the
conversation and passes it through a new optional field; the pipeline just
prefers it when present.

- `QueryInput.retrieval_query: str | None` — new optional field
  ([rag/schemas.py](../schemas.py)).
- `build_course_query()` now returns `input.retrieval_query or input.student_message`
  ([rag/query_builder.py](../query_builder.py)).
- `rag_eng/service.py` calls `build_retrieval_query(messages)` and sets
  `query_kwargs["retrieval_query"]` before constructing the query. Generation is
  unchanged — it still forwards the full message list.
- The retrieval eval (`llm_eval_retrieval_mit14_*.py`) fills
  `contextualized_query` from the **same** `build_retrieval_query`, so eval and
  production embed an identical string (parity).

```
messages (history) ──► build_retrieval_query() ──► retrieval_query
                                                        │
                          build_course_query = retrieval_query or student_message
                                                        │
                                                    embed → retrieve
```

### 1.2 Adaptive logic — `build_retrieval_query(messages)`

Behaviour depends on the current turn:

| Current turn | Action |
|---|---|
| First turn (one student turn) | return `None` → embed the message as-is |
| **Specific** (has a topical word) | return `None` → embed as-is, no look-back |
| **Low-signal / general** ("how about now") | **anchor + recent window + current code/terminal** |

For a low-signal follow-up the query is assembled from:

- **Anchor** — the turn that established the problem: the most recent one naming a
  `week`/`problem`/`assignment` number (`_ANCHOR_RE`), else turn 1. This survives
  even a long run of vague follow-ups.
- **Recent window** — the last `_RECENT_PRIOR + 1 = 4` student questions (oldest
  first). Mid-conversation turns outside the window are dropped.
- **Current code + terminal** — the `[Code_Context]` / `[Terminal_Context]` blocks
  of the current turn, capped at `_CTX_CHAR_CAP = 400` chars each.

Example (real 07-16 turn): `"How about now"` →
`"How to run test case for problem 1? ... mantissa seems not correct ..."`.

### 1.3 The low-signal detector — systematic, no hand-list

The core decision is *"is this question specific or general?"*. A hardcoded
stopword list is brittle, so topicality is defined **systematically** from two
frequency signals:

```python
topical(token) = zipf(token) < 3.5                      # specialized in general English
              OR (zipf(token) < 4.6 AND token in corpus) # uncommon AND a course term
low_signal(question) = no topical token in the question
```

- **General-English rarity** via `wordfreq` (`zipf` ~8 = "the" … ~0 = never seen).
  Catches specialized terms (`mantissa`, `segfault`) and correctly treats
  conversational words (`lost`, `teach`, `works`) as non-topical.
- **Course-corpus salience** via `corpus_terms.json` — tokens appearing in
  `>= 2` course chunks. Rescues technical questions built from common English
  words (`use-after-free`, `float bit sign`, `condition variable`) that
  general-rarity alone would miss.

Neither half is hand-curated. The corpus artifact is regenerated with
[`build_corpus_terms.py`](build_corpus_terms.py) (3,675 terms over 2,900 mit14 +
cs50 chunks). If `wordfreq` is unavailable the detector safely disables
(no contextualization) rather than misfiring.

**Why the combination is required** (validated on the real logs):

| Signal | conversational-rare ("lost", "teach") | technical-common-words ("use-after-free", "lock") |
|---|---|---|
| Corpus-IDF alone | ✗ misses | ✓ |
| General zipf alone | ✓ | ✗ misses |
| **Corpus-df ∧ zipf (used)** | ✓ | ✓ |

Dependencies added: `wordfreq>=3.0`; artifact: `rag/corpus_terms.json`.

---

## Part 2 — Results analysis

Real production turn logs, `course_id=mit14`, dates **2026-07-05 → 2026-07-17**
(120 evaluable turns, 10 days). Harness:
[`compare_adaptive_vs_log_mit14.py`](compare_adaptive_vs_log_mit14.py) reconstructs
per-session history, reruns retrieval two ways (baseline = raw message; adaptive =
`retrieval_query`) and compares against the chunks stored in each log.

### 2.1 Harness reliability

`baseline` (raw message, today's pipeline) reproduces the logged production
retrieval, so differences are real, not drift:

- 2026-07-16 (the main floating session): baseline-vs-log Jaccard **0.96**, and
  **1.00** on the follow-up turns → production embedded the raw follow-up (the
  bug), and today's pipeline reproduces it faithfully.
- Early dates (07-05…07-08) show low reliability (0.11–0.43): those turns are
  not week-2 and the log's `chunk_id`s no longer resolve in the current index, so
  week-inference falls back imperfectly. **Adaptive changes nothing on those
  turns**, so it does not affect the verdict — it only matters where the query
  actually differs.

### 2.2 Contextualization coverage

The systematic detector broadened coverage without over-firing on substantive
turns:

| Detector | general follow-ups (/126) | contextualized turns (cross-date) |
|---|---|---|
| pure-filler (initial) | 8 | 8 (all on 07-16) |
| **corpus-df ∧ zipf (final)** | 28 | **25** (07-05: 3, 07-07: 1, 07-16: 21) |

Newly caught turns are genuinely general — "Yay it works now", "teach me c++",
"-127", "Check the code", "When it's 1. or 0." — while domain questions
("what is mantissa", "use-after-free bug crash", "condition variable") correctly
stay specific.

### 2.3 On-topic recall proxy

A retrieved chunk is *on-topic* if it shares a topical term (per the detector)
with the session's overall topic. Measured on the **contextualized** turns
(where the query actually changes):

| Turn set | on-topic hit@k | on-topic density |
|---|---|---|
| Contextualized — logged (prod) | 0.76 | 0.55 |
| **Contextualized — adaptive (new)** | **0.96** | **0.70** |

Per-date (contextualized turns):

```
2026-07-05  n=3   hit 1.00 -> 1.00   density 0.30 -> 0.33
2026-07-07  n=1   hit 0.00 -> 0.00   density 0.00 -> 0.00
2026-07-16  n=21  hit 0.76 -> 1.00   density 0.61 -> 0.79
```

On the 07-16 floating session, every vague follow-up now surfaces floating
content (hit@k → **1.00**).

### 2.4 Chunk quality — noise replaced with grounding

On 07-16 contextualized follow-ups (21 turns), comparing adaptive-retrieved
chunks against the logged set:

| | chunks | floating-relevant | boilerplate-noise |
|---|---|---|---|
| **Added** by adaptive | 86 | 70 (81%) | 3 |
| **Dropped** from log | 88 | 11 (12%) | 29 |

Adaptive replaces wrap-up / outline / OpenCourseWare boilerplate with the
floating problem statement and lecture pages.

### 2.5 Example — retrieved chunks before/after (07-16)

`"How about now"` → adaptive query
`"How to run test case for problem 1? … mantissa seems not correct"`:

```
LOGGED (production):                     ADAPTIVE (new):
[  ] Lecture2 p.6  Memory Model          [ON] ass1_p1 p.1   score 1.20  (floating problem)
[  ] Lecture2 p.16 Wrap-up               [ON] ass1_p1 p.2   score 1.02
[  ] Lecture2 p.14 Floating Examples     [ON] ass1_p3 p.2   score 0.94
[  ] Lecture2 p.17 OpenCourseWare        [ON] Lecture2 p.11 Floating Point
[  ] ass1_p2 p.3   OCW boilerplate       [  ] Lecture2 p.14 Floating Examples
```

### 2.6 Caveats

- **On-topic proxy is conservative** (exact token match): "Floating **Point**"
  misses the session term "**float**", so genuinely relevant chunks read as
  off-topic. The measured gain is a floor.
- **Not human-labeled gold**; the trustworthy signal is 07-16 (21 turns,
  reliable harness). 07-07 is a single turn on a low-reliability date.
- **All-turns recall** is confounded (logged 9 chunks vs today's 5-chunk
  pipeline); only the contextualized comparison is apples-to-apples.
- **Retrieval relevance, not answer quality** — whether better grounding changes
  the final Socratic answer needs a separate generation A/B.
- A few borderline conceptual turns ("if i use a reference…") now look back;
  tunable via `_ZIPF_WEAK`.

---

## Files

| File | Role |
|---|---|
| [rag/schemas.py](../schemas.py) | `retrieval_query` field on `QueryInput` |
| [rag/query_builder.py](../query_builder.py) | `build_retrieval_query`, low-signal detector |
| [rag/corpus_terms.json](../corpus_terms.json) | course-term artifact (df ≥ 2) |
| [build_corpus_terms.py](build_corpus_terms.py) | regenerates the artifact |
| `rag_eng/service.py` | builds `retrieval_query` from `messages` |
| `llm_eval_retrieval_mit14_*.py` | eval parity via `build_retrieval_query` |
| [compare_adaptive_vs_log_mit14.py](compare_adaptive_vs_log_mit14.py) | log-vs-pipeline comparison harness |
| requirements.txt | `wordfreq>=3.0` |
