# Input CodeBERT Guardrail — Dataset (v1)

Training/eval data for the **input** guardrail classifier: a CodeBERT model that
screens the student's raw question **before** RAG/Qwen, so adversarial,
full-solution, off-topic, or inappropriate requests are blocked **pre-LLM**
(saving GPU). This is **separate from `output_guardrails/`**, which screens the
LLM's answer *after* Qwen — no answer/draft/output-guardrail fields appear here.

## Labels
- `label = 1` → **unsafe / BLOCK** (do not send to Qwen)
- `label = 0` → **safe / PASS** (legitimate C++ learning/debugging question)
- `should_call_llm` = `true` for safe, `false` for unsafe.
- `block_reason` is set for unsafe rows (`ERR_PROMPT_INJECTION`,
  `ERR_FULL_SOLUTION_REQUEST`, `ERR_OFF_TOPIC`, `ERR_INAPPROPRIATE_CONTENT`),
  `null` for safe rows.
- **`reviewed = false` on every row** — these are CANDIDATES; human review is
  required before training.

## Files
| File | Purpose |
|---|---|
| `generate_input_dataset_v1.py` | Deterministic generator (SEED=2026). Re-run to reproduce all three files below byte-for-byte. |
| `validate_input_dataset_v1.py` | 15 integrity checks; exits non-zero on failure. |
| `input_classifier_dataset_v1_candidates.jsonl` | ~300 rows for **train/val/test**. |
| `input_hard_gold_v1.jsonl` | 80 rows for **external evaluation only** — NOT in any split. Uses context_ids disjoint from the candidates. |
| `splits_input_v1.json` | `context_id → train/val/test` (candidates only). Split is **by context_id**, so the same code context never crosses splits. |

## Model input (later)
The classifier input will be assembled from `user_query` + `student_code` +
`course_topic`/`assignment_context`. (This dataset stores the fields; it does
not prescribe the exact concatenation.)

## Categories
**Unsafe:** prompt_injection, full_solution_request, subtle_solution_seeking
(labeled `ERR_FULL_SOLUTION_REQUEST`), off_topic, inappropriate_content.
**Safe:** cxx_debugging_question, concept_explanation, hint_request,
compiler_or_runtime_error_question, **hard_safe_negative** (mentions
"solution"/"full code" but explicitly declines it — these protect against
over-blocking legitimate questions).

## Regenerate & validate
```bash
python input_guardrails/classifier_data/generate_input_dataset_v1.py
python input_guardrails/classifier_data/validate_input_dataset_v1.py
```

## Scope
Dataset generation only — no model training. Does not modify
`output_guardrails/`, `semantic_guardrail.py`, `combined.py`, thresholds,
checkpoints, S3, or SageMaker.
