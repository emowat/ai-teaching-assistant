# -*- coding: utf-8 -*-
"""
run_eval.py
This is the file that makes the eval. Loads the datasets, sampling from them.

Runs the macro and micro judges, computs drift, and saves the result as a JSON files
plus summary results amd spot check sheets.


"""

import os
import sys
import json
import glob
import subprocess
import pandas as pd
try:
    from . import eval_functions as ef
    from .prompts import (
        macro_judge_prompt,
        micro_judge_prompt,
        micro_metrics,
        macro_metrics,
        macro_critical,
        micro_critical,
    )
except ImportError:
    import eval_functions as ef
    from prompts import (
        macro_judge_prompt,
        micro_judge_prompt,
        micro_metrics,
        macro_metrics,
        macro_critical,
        micro_critical,
    )
from concurrent.futures import ThreadPoolExecutor, as_completed


from pathlib import Path
from dotenv import load_dotenv
ROOT_DIR= Path(__file__).resolve().parent
load_dotenv(ROOT_DIR/".env")
# No ANTHROPIC_API_KEY needed: the judge shells out to the `claude` CLI (headless/print
# mode) using the local Claude Code subscription login. Same approach as
# rag/experiments/llm_eval_retrieval_mit14_claude.py.

#reuse the shared S3 writer (transparently handles s3:// vs local), same as
#rag/experiments/llm_eval_retrieval_mit14_claude.py. Only stdlib+numpy load at
#import time; boto3 loads lazily inside the helper.
REPO_ROOT= ROOT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "rag" / "experiments"))
from retrieval_experiment import _write_json


#load scecret form .env file
def load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            
            line= line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip('"').strip("'"))
load_env()




#config (override with enviroment variabels)

EVAL_DIR= os.environ.get("EVAL_DIR", "eval")
RESULTS_DIR= os.environ.get("RESULTS_DIR", "evaluation/model_eval_results/log_results")
#S3 checkpoint prefix for the JSON results; set to "" to disable and stay local-only
RESULTS_S3_PREFIX= os.environ.get(
    "RESULTS_S3_PREFIX",
    "s3://codingrabbit-data-dev/evaluation/model_eval_results/results_claude_as_judge/",
)
DATASET_NAME= os.environ.get("DATASET_NAME", "eval_log")
model_=os.environ.get("MODEL", "claude-sonnet-4-6")           #CLI model alias ("sonnet") or full id
CLAUDE_CLI_TIMEOUT= int(os.environ.get("CLAUDE_JUDGE_TIMEOUT_SECONDS", "300"))       #per-call timeout
CLAUDE_CLI_MAX_CONCURRENCY= int(os.environ.get("CLAUDE_JUDGE_MAX_CONCURRENCY", "4")) #parallel `claude` procs


class _CLIResponse:
    """Mimic a LangChain message so eval_functions can read `.content`."""
    __slots__= ("content",)
    def __init__(self, content):
        self.content= content


class ClaudeCLIJudge:
    """Drop-in judge that shells out to the `claude` CLI in headless/print mode.

    Uses the local Claude Code subscription login instead of an ANTHROPIC_API_KEY.
    Exposes only the slice of the LangChain Runnable interface eval_functions uses:
    `.batch(prompts, config, return_exceptions)` -> list of objects with `.content`.
    """
    def __init__(self, model, timeout= CLAUDE_CLI_TIMEOUT, max_concurrency= CLAUDE_CLI_MAX_CONCURRENCY):
        self.model= model
        self.timeout= timeout
        self.max_concurrency= max_concurrency

    def _invoke_one(self, prompt):
        #prompt goes on stdin (not argv) so large judge prompts don't hit ARG_MAX
        cmd= ["claude", "-p", "--model", self.model, "--output-format", "json", "--allowed-tools", ""]
        result= subprocess.run(cmd, input= prompt, capture_output= True, text= True, timeout= self.timeout)
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI failed (exit {result.returncode}): {result.stderr[:500]}")
        data= json.loads(result.stdout)
        if data.get("is_error"):
            raise RuntimeError(f"claude CLI returned an error: {str(data)[:500]}")
        return _CLIResponse(data["result"])   #judge's raw text; eval_functions parses the JSON out of it

    def batch(self, prompts, config= None, return_exceptions= False):
        #honor eval_functions' max_concurrency but cap it to avoid tripping subscription rate limits
        workers= max(1, min(self.max_concurrency, (config or {}).get("max_concurrency", self.max_concurrency)))
        results= [None] * len(prompts)
        with ThreadPoolExecutor(max_workers= workers) as pool:
            future_to_idx= {pool.submit(self._invoke_one, p): i for i, p in enumerate(prompts)}
            for future in as_completed(future_to_idx):
                i= future_to_idx[future]
                try:
                    results[i]= future.result()
                except Exception as e:
                    if return_exceptions:
                        results[i]= e
                    else:
                        raise
        return results

def load_all_logs(eval_dir):
    rows, files= [], sorted(glob.glob(os.path.join(eval_dir, "**", "*.jsonl"), recursive= True))
    print("found", len(files), "jsonl files under", eval_dir)
    for path in files:
        with open(path) as f:
            for line in f:
                line=line.strip()
                if line:
                    rows.append(json.loads(line))
    print("loaded" , len(rows), "log turns total")
    return rows

def save_json(obj, name):
    #primary destination: checkpoint straight to S3
    if RESULTS_S3_PREFIX:
        s3_uri= RESULTS_S3_PREFIX.rstrip("/") + "/" + name
        try:
            _write_json(s3_uri, obj)
            print("checkpointed", s3_uri)
        except Exception as e:
            print("S3 write FAILED for", s3_uri, "->", e, "(keeping local backup below)")
    #local backup copy: stable fallback, and the charts/spot-check steps read RESULTS_DIR
    path= os.path.join(RESULTS_DIR, name)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    print( "backed up", path)

def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ef.results_dir= RESULTS_DIR
    
    log_dataset= load_all_logs(EVAL_DIR)
    if not log_dataset:
        print("no log turns found nothing to do"); return
    judge_model= ClaudeCLIJudge(model=model_)

    #optional subset: cap homework/study sessions (adversarial are always kept in full).
    #Defaults keep every session; e.g. EVAL_HOMEWORK_N=30 EVAL_STUDY_N=15 for a quick run.
    ef.homework_number= int(os.environ.get("EVAL_HOMEWORK_N", ef.homework_number))
    ef.study_number= int(os.environ.get("EVAL_STUDY_N", ef.study_number))
    print(f"sampling caps: homework<= {ef.homework_number}, study<= {ef.study_number} (adversarial: all)")

    #build samples
    macro_samples= ef.stratified_sample(ef.build_Macro_samples(log_dataset))
    micro_samples= ef.build_micro_samples([s["raw_convo"] for s in macro_samples])
    
    #run judge + drift
    
    macro_results= ef.run_marco_eval( macro_samples, judge_model, macro_judge_prompt)
    micro_results= ef.run_mirco_eval(micro_samples, judge_model , micro_judge_prompt)
    drift= ef.compute_drift(micro_results)
    
    save_json(macro_results, f"Macro_{DATASET_NAME}_LLM-as-a-judge_c_plus_plus_dataset.json")
    save_json(micro_results, f"Micro_{DATASET_NAME}_LLM-as-a-judge_c_plus_plus_dataset.json")
    save_json(drift, f"Drift_{DATASET_NAME}_LLM-as-a-judge_c_plus_plus_dataset.json")
    
    macro_df, micro_df= pd.DataFrame(macro_results), pd.DataFrame(micro_results)
    summary= {DATASET_NAME: {
        "macro_pass_rate":macro_df["passed"].dropna().mean() if len(macro_df) else None,
        "micro_pass_rate":micro_df["passed"].dropna().mean() if len(micro_df) else None,
        "total_drift_rate": drift.get("total_drift_rate"),
        "qaulity_decline_rate": drift.get("qaulity_decline_rate"),
        "code_leak_rate": drift.get("code_leak_rate"),
        }}
    
    save_json(summary, "Summary_LLM-as-a-judge_c_plus_plus_dataset.json")
    print(json.dumps(summary, indent=2))
    
    try:
        import  matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt
        def _savefig(*a, **k):
            _savefig.n += 1
            _plt.savefig(os.path.join(RESULTS_DIR, F'Chart_{_savefig.n}.png')); _plt.close()
        _savefig.n=0
        if ef.plt is not None: ef.plt.show= _savefig
        ef.plot_metric_ci(micro_results, micro_metrics, DATASET_NAME + "MICRO PASS RATE (WILSON CI)")
        ef.plot_metric_ci(macro_results, macro_metrics, DATASET_NAME + "MACRO PASS RATE (WILSON CI)" )
        
        ef.plot_cat(micro_results, ef.micro_groups, DATASET_NAME + "MICRO BY Category (WILSON CI)")
        ef.plot_cat(macro_results, ef.macro_groups, DATASET_NAME + "MACRO BY Category (WILSON CI)")
        print("saved", _savefig.n, "chart PNGS to", RESULTS_DIR)
    except Exception as _e:
        print("skipped visual:", _e)
    
    
    #determinitic checks FP and FN
    comp= ef.compare_judge(micro_results, DATASET_NAME)
    comp.to_csv(os.path.join(RESULTS_DIR, "Log_disagreements.csv"), index=False)
    
    print(ef.summary_(comp).to_string(index=False))
    
    ef.spot_check(micro_results, micro_metrics, DATASET_NAME).to_csv( os.path.join(RESULTS_DIR, "LOG_micro_spot_check.csv"), index= False)
    
    ef.spot_check(macro_results, macro_metrics, DATASET_NAME).to_csv( os.path.join(RESULTS_DIR, "LOG_macro_spot_check.csv"), index= False)
    
    print("wrote spot-check-sheets")
    
if __name__== "__main__":
    main()
