# Input CodeBERT Guardrail — train / evaluate

Scripts to fine-tune and evaluate a **CodeBERT classifier for the INPUT
guardrail** — it screens the student's raw question *before* RAG/Qwen and
classifies it safe (PASS) vs unsafe (BLOCK).

This is **separate from `output_guardrails/`** (which screens the LLM answer).
Nothing here modifies the output guardrail, its CodeBERT checkpoints,
`semantic_guardrail.py`, `combined.py`, thresholds, S3, or SageMaker.

## Labels
- `label = 1` → unsafe / BLOCK / `should_call_llm = false`
- `label = 0` → safe / PASS / `should_call_llm = true`

## Data
- **Train:** `classifier_data/input_classifier_dataset_v1_candidates.jsonl`,
  split by `context_id` via `classifier_data/splits_input_v1.json`.
- **External eval only:** `classifier_data/input_hard_gold_v1.jsonl` —
  **never** loaded for training; disjoint context_ids from candidates.
- Splits are by `context_id`; the trainer asserts no context leaks across
  train/val/test.

## Model input format (identical in train & eval — `data_utils.format_example`)
```
[USER_QUERY]
{user_query}

[STUDENT_CODE]
{student_code}

[COURSE_TOPIC]
{course_topic}

[ASSIGNMENT_CONTEXT]
{assignment_context}
```

## Files
| File | Purpose |
|---|---|
| `data_utils.py` | stdlib-only: load JSONL, format input, apply splits, leakage check, counts |
| `train_input_codebert_classifier.py` | fine-tune `microsoft/codebert-base` (num_labels=2); `--dry-run` does data-only prep |
| `evaluate_input_codebert_classifier.py` | metrics, confusion, ROC-AUC, FP/FN listing, threshold sweep; internal-split or hard-gold |

## Dry run (data only — no model download/train)
```bash
python -m input_guardrails.models.train_input_codebert_classifier \
  --train-path input_guardrails/classifier_data/input_classifier_dataset_v1_candidates.jsonl \
  --splits-path input_guardrails/classifier_data/splits_input_v1.json \
  --checkpoint-name input_codebert_v1 --dry-run
```

## Train (requires torch + transformers; run only when approved)
```bash
python -m input_guardrails.models.train_input_codebert_classifier \
  --train-path input_guardrails/classifier_data/input_classifier_dataset_v1_candidates.jsonl \
  --splits-path input_guardrails/classifier_data/splits_input_v1.json \
  --checkpoint-name input_codebert_v1
```
Writes the best checkpoint + tokenizer + `train_metrics.json` to
`input_guardrails/models/checkpoints/input_codebert_v1/`.

## Evaluate
```bash
# internal test split
python -m input_guardrails.models.evaluate_input_codebert_classifier \
  --checkpoint-path input_guardrails/models/checkpoints/input_codebert_v1 \
  --eval-path input_guardrails/classifier_data/input_classifier_dataset_v1_candidates.jsonl \
  --splits-path input_guardrails/classifier_data/splits_input_v1.json --split test --threshold-sweep

# external hard gold
python -m input_guardrails.models.evaluate_input_codebert_classifier \
  --checkpoint-path input_guardrails/models/checkpoints/input_codebert_v1 \
  --eval-path input_guardrails/classifier_data/input_hard_gold_v1.jsonl --threshold-sweep
```

## CLI flags
**train:** `--train-path --splits-path --model-name --checkpoint-name
--output-dir --epochs --batch-size --max-length --learning-rate
--weight-decay --seed --require-reviewed --dry-run`
**evaluate:** `--checkpoint-path --eval-path --splits-path --split
--max-length --threshold --threshold-sweep --output-json`

`--require-reviewed` (train) defaults off so current `reviewed=false`
candidates run for dry-run validation; turn it on once rows are human-reviewed.
