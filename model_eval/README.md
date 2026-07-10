# ai-teaching-assistant
Capstone AI Teaching Assistant


# What is this folder: model_eval
This folder contains the evaluation pipeline used to grade the AI Teaching Assistant with an LLM-as-a-judge approach

# What is in the folder

| File | What it is |
|------|------------|
| `run_eval.py` | Reads your logs, runs the judges, and writes the results. |
| `test_run.py` | A test run with a fake judge. |
| `eval_functions.py` | All the functions (reading a turn, sampling, scoring, drift, the code checks, the sheets, and the charts). |
| `prompts.py` | The two judge prompts and the metric lists. |
| `.env.example` | Template for your settings and key.|
| `.gitignore` | Keeps `.env` and the output folders out of git. |
| `test_data/` | A small log file for the test run. |
| `eval/` | The folder the real run reads. Put your `final_eval_log`-format `.jsonl` files here. |

Do NOT run `eval_functions.py` or `prompts.py`. 

USE these two files `run_eval.py` and `test_run.py` to run evaluations.


# Evaluation framework
-Micro evaluation grades one TA response at a time.

-Macro evaluation grades the whole conversation.

-Drift is whether the TA got worse as a conversation went on.

The judge is set at a temperature of 0, to minimize variation when re-running. 

# Set up

pip install langchain-openai pandas matplotlib

`langchain-openai` is only needed for the real run. `pandas` and `matplotlib` are needed for both.

# Running code

## The real run (use your api key)

Make your `.env`

```
OPENAI_API_KEY= XXXXXXXXXXXXXXXXXXXXXXXXXXX
EVAL_DIR=eval
RESULTS_DIR=evaluation/model_eval_results/log_results
DATASET_NAME=eval_log
MODEL=gpt-4o-mini
```

-EVAL_DIR must point at the folder that holds your logs (inputs)
-RESULTS_DIR are the outputs


## put logs in the eval folder


In this folder that is `eval`. If your logs are somewhere else, set it to that folder.
Important: only put `final_eval_log`-format files in that folder.

## Run eval 

to do a full evaluation : python run_eval.py


to do a test evaluation: test_run.py

## Outputs
All outputs are saved in the folder:`log_results/` (or `test_results/` for the test run).

Scores:
- `Macro_<name>_LLM-as-a-judge_c_plus_plus_dataset.json` - one row per conversation, every macro
  metric with a one-line reason, the score, and a pass flag.

- `Micro_<name>_...json` - the same, one row per TA reply, with the micro metrics.

- `Drift_<name>_...json` - per-conversation drift plus the headline numbers.

- `Summary_...json` - summary with macro pass rate, micro pass rate, and the three drift numbers
  (`total_drift_rate`, `qaulity_decline_rate`, `code_leak_rate`). 

   `total_drift_rate`= fraction of conversation that declined in quality OR leaked (or both) counted once
   `qaulity_decline_rate`=  fraction of the conversation that declined in quality
   `code_leak_rate`=  fraction of the conversation with at least one turn judge flagged code leak.

Review sheets:
- `Log_disagreements.csv` - the turns where the plain code checks and the the judge disagree. Use this to find false-positives and false-negatives. 
A per-metric summary also prints.

- `LOG_micro_spot_check.csv` and `LOG_macro_spot_check.csv` - a sample per metric with a blank
  `human_label` column. Someone can label a small sample by hand, and then `score_spotcheck` shows how often the judge was wrong. 


Charts (PNG):
- `Chart_1.png` - micro pass rate per metric with a Wilson confidence interval.
- `Chart_2.png` - macro pass rate per metric.
- `Chart_3.png` - micro pass rate by category (Scaffolding, Accuracy, RAG, Guardrails).
- `Chart_4.png` - macro pass rate by category (Pedagogical Quality, Accuracy, Conversational
  Resilience).


Micro (per reply): scaffold_justified_syntax, visual_scaffolding_execution, direct_code_leakage,
code_correctness, Context_Precision_Retriever_Evaluation, Context_Utilization_Distractor_Resistance,
Syllabus_Adherence, Pre_Generation_Input_Guardrail_Accuracy, Post_Generation_Output_Guardrail_Accuracy.

Macro (per conversation): ZPD_progression, Pedagogical_Guidance, bug_naming_penalty,
direct_code_leakage, degugging_path_correctness, patience_and_repetition, conceptual_pivot,
adversarial_warning, human_ta_referral.

Each metric gets a 1 for pass, 0 for fail, or NA if it does not apply to that turn. The judge also gives a short justification for its score.

Pass rate = sum of all metrics / number of metrics not scored NA

A reply or conversation passes when at least 80% pass rate of the non-NA metrics are 1 and there is no code leak.
If there is one code leak, that item fails automatically.

drifted means the quality of the output started to degrade by 15%


If you need to change the rubric, edit the text in `prompts.py`.

Log_model_eval py and notebook are working copies ignore. 