# Plan: Rewrite RAG Retrieval Evaluation

## Context

The existing `retrieval_experiment.py` evaluates retrieval with chunk-ID ranking metrics (Recall@K, MRR, NDCG). Two problems:

1. **Semantic blindness** — paraphrased chunks score 0 even if correct.
2. **Multi-turn ambiguity** — follow-up queries are ambiguous without conversation context, making retrieval look artificially bad.

The golden set is 1000+ multi-turn sessions. Each session is a full conversation. There are no pre-labeled golden chunk IDs, so the primary metric is **LLM-based Context Recall** (GPT-4o-mini). Ranking metrics are dropped in favor of semantic evaluation.

---

## Golden Set Format (input)

```python
[
  {
    "messages": [
      {"role": "system",    "content": "<system prompt>"},
      {"role": "user",      "content": "<question or context>"},
      {"role": "assistant", "content": "<golden answer>"},
      {"role": "user",      "content": "<follow-up question>"},
      {"role": "assistant", "content": "<golden answer>"},
      ...
    ],
    "metadata": {"week": 5, "topic": "...", "trigger": "homework_paste"}
  },
  ...  # next session
]
```

Each session = one conversation chain. Metadata is per-session, not per-turn.

---

## Step 1: Parse Sessions into Evaluation Units

Each `(user, assistant)` pair becomes one `EvalTurn`. The parser walks each session's message list and emits a turn for every user → assistant pair, recording everything needed to evaluate that retrieval call.

```python
@dataclass
class EvalTurn:
    turn_id: str                    # "{session_idx}_turn_{turn_idx}"
    session_id: str                 # "{session_idx}"
    turn_index: int                 # 0 = first user turn, 1+ = follow-up
    query: str                      # raw user message at this turn
    golden_answer: str              # assistant message at this turn (the label)
    conversation_history: list[dict]  # all messages BEFORE this turn (incl. system)
    contextualized_query: str = ""  # pre-computed standalone rewrite of follow-up
    week: int = 0
    topic: str = ""
    trigger: str = ""
```

**Parser logic:**

```
for each session:
    history = []
    turn_index = 0
    for i, msg in enumerate(messages):
        if msg.role == "system":
            history.append(msg)
        elif msg.role == "user":
            next_msg = messages[i+1] if i+1 < len exists and role=="assistant"
            emit EvalTurn(
                turn_id       = f"{session_idx}_turn_{turn_index}",
                query         = msg.content,
                golden_answer = next_msg.content,
                history       = copy(history),   # snapshot before this turn
                turn_index    = turn_index,
                ...metadata
            )
            history.append(msg)
            history.append(next_msg)
            turn_index += 1
```

`conversation_history` for turn N = all messages up to (but not including) turn N's user message. Turn 0 history = just the system prompt.

---

## Step 2: Query Contextualization (Multi-turn)

Run **once before evaluation** — not inside the retrieval loop — so each configuration uses the same rewritten queries.

```
for each turn where turn_index > 0 and contextualized_query == "":
    GPT-4o-mini prompt:
        "Conversation so far:
         {last 4 messages from conversation_history}
         
         Follow-up question: {turn.query}
         
         Rewrite as a self-contained question with no pronouns that
         require the conversation to resolve. Output only the question."
    → store in turn.contextualized_query
```

**During retrieval:** `query_text = turn.contextualized_query if turn.turn_index > 0 else turn.query`

Cost: ~N_followup calls total, paid once regardless of grid size.

---

## Step 3: Context Recall (LLM) — Primary Metric

For each turn (requires `golden_answer` non-empty):

```
1. Extract claims
   GPT-4o-mini:
     "Break this answer into atomic, self-contained factual claims.
      One per line. No bullets or numbering.
      Answer: {golden_answer}"
   → [claim_1, claim_2, ...]

2. Per-claim attribution
   for each claim:
     GPT-4o-mini:
       "Context:
        {joined retrieved chunk texts, up to 3500 chars}
        
        Claim: {claim}
        
        Is this claim directly supported by the context? Answer yes or no."
     → yes / no

3. Score
   context_recall_llm = count(yes) / len(claims)
   also track: n_claims, n_covered
```

**Model**: `gpt-4o-mini` for all LLM calls.  
**Client**: `openai.OpenAI()` — reads `OPENAI_API_KEY` from env.

---

## Step 4: Two-Level Aggregation

### Level 1 — Turn-level (the atomic unit)

For each turn, record:

```python
{
  "turn_id":            "session_3_turn_1",
  "session_id":         "session_3",
  "turn_index":         1,
  "query":              "...",                 # raw or contextualized
  "context_recall_llm": 0.75,                 # covered_claims / total_claims
  "n_claims":           4,
  "n_covered":          3,
  "week":               5,
  "topic":              "sorting",
}
```

### Level 2 — Session-level (macro)

After all turns in a session are scored, aggregate:

```python
{
  "session_id":          "session_3",
  "n_turns":             4,
  "recall_mean":         0.70,   # how well did RAG do on average across this session?
  "recall_max":          0.90,   # best turn in this session
  "recall_min":          0.33,   # worst turn — where did RAG fail?
  "recall_std":          0.22,   # consistency: low std = uniformly good/bad
  "week":                5,
  "topic":               "sorting",
  "trigger":             "homework_paste",
}
```

A session with **high mean but low min** means RAG is mostly fine but breaks on specific turns (usually ambiguous follow-ups). A session with **low mean and low max** means the corpus isn't covering that topic at all.

### Run-level summary (across all sessions, for MLflow)

| Metric | What it tells you |
|---|---|
| `recall_mean` | Overall retrieval quality |
| `recall_mean_turn0` | Quality on first (standalone) questions |
| `recall_mean_followup` | Quality on follow-up turns specifically |
| `session_recall_mean` | Mean of per-session means (weights sessions equally) |
| `pct_sessions_recall_above_0.7` | How many sessions is RAG "good enough" |
| `n_turns_evaluated` | Coverage |
| `n_sessions` | Coverage |

---

## Multi-Source Support

Two sources, each with its own golden set and corpus loader (both already exist in `retrieval_experiment.py`):

| `--source` | Golden set env var | Corpus loader |
|---|---|---|
| `cs50` | `RAG_EVAL_GOLDEN_CS50_PATH` | `load_harvard_cs50_chunks(RAW_DATA_PATH)` |
| `mit14` | `RAG_EVAL_GOLDEN_MIT14_PATH` | `load_slide_chunks(RAW_DATA_PATH)` |

Dispatcher at the top of `main()`:

```python
SOURCE_CONFIG = {
    "cs50": {
        "golden_path": os.getenv("RAG_EVAL_GOLDEN_CS50_PATH", ""),
        "load_chunks": lambda: load_harvard_cs50_chunks(RAW_DATA_PATH),
    },
    "mit14": {
        "golden_path": os.getenv("RAG_EVAL_GOLDEN_MIT14_PATH", ""),
        "load_chunks": lambda: load_slide_chunks(Path(RAW_DATA_PATH)),
    },
}
config = SOURCE_CONFIG[args.source]
turns = load_golden_sessions(config["golden_path"])
chunks = config["load_chunks"]()
```

MLflow experiment name includes source: `f"rag_retrieval_{args.source}"`.

---

## File Layout

| File | Action |
|---|---|
| `eval_llm.py` | **Create** — new standalone script |
| `retrieval_experiment.py` | **No changes** — import corpus/index/retrieval from it |
| Golden set JSON/JSONL | Already exists — no changes needed to data format |

---

## Key Imports from `retrieval_experiment.py`

```python
from retrieval_experiment import (
    ExpChunk, EMBEDDING_MODELS, TOP_K_VALUES, RERANK_STRATEGIES,
    load_harvard_cs50_chunks, load_slide_chunks,
    build_index, retrieve,
    RAW_DATA_PATH, OUTPUT_PREFIX, _write_json,
)
```

---

## CLI

```bash
export OPENAI_API_KEY="..."
export RAG_EVAL_GOLDEN_CS50_PATH="path/to/cs50_golden.json"
export RAG_EVAL_GOLDEN_MIT14_PATH="path/to/mit14_golden.json"

python eval_llm.py --source cs50  --dry-run
python eval_llm.py --source mit14 --dry-run
python eval_llm.py --source cs50  --llm-eval --quick
python eval_llm.py --source mit14 --llm-eval
```

---

## Verification Checklist

1. `--dry-run` prints session count, total turns, follow-up count — matches expected ~1000+
2. `--quick` (no LLM) runs without OpenAI key; prints retrieval latency per config
3. `--llm-eval --quick` prints `context_recall_llm` per run; values in 0–1 range
4. `context_recall_followup` < `context_recall_standalone` expected (chains are harder)
5. `context_bleed_rate` near 0 when contextualized queries are used; rises if you disable contextualization (sanity check that the metric works)
6. Results written to `OUTPUT_PREFIX/experiment_results_llm_eval.json`
