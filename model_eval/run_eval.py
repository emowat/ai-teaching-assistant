# -*- coding: utf-8 -*-
"""
run_eval.py
This is the file that makes the eval. Loads the datasets, sampling from them.

Runs the macro and micro judges, computs drift, and saves the result as a JSON files
plus summary results amd spot check sheets.
"""
import glob
import json
import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv

try:
    from . import eval_functions as ef
    from .prompts import (
        macro_critical,
        macro_judge_prompt,
        macro_metrics,
        micro_critical,
        micro_judge_prompt,
        micro_metrics,
    )
except ImportError:
    import eval_functions as ef
    from prompts import (
        macro_critical,
        macro_judge_prompt,
        macro_metrics,
        micro_critical,
        micro_judge_prompt,
        micro_metrics,
    )

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


def load_env(path: str = ".env") -> None:
    """Load simple KEY=VALUE lines into the process environment."""

    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip('"').strip("'"))


load_env()


EVAL_DIR = os.environ.get("EVAL_DIR", "eval")
RESULTS_DIR = os.environ.get("RESULTS_DIR", "evaluation/model_eval_results/log_results")
DATASET_NAME = os.environ.get("DATASET_NAME", "eval_log")

# pick a judge and model inside env
judge_ = os.environ.get("judge_", "openai").lower()
DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",  # https://developers.openai.com/api/docs/models/gpt-4o-mini
    "cohere": "command-r-08-2024",  # https://docs.cohere.com/docs/command-r
    "google": "gemini-3.1-flash-lite",  # https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite
    "bedrock": "amazon.nova-2-lite-v1:0",  # https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-lite.html
    "bedrock_claude_haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",  # https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-4-5.html
    "bedrock_claude_sonnet": "us.anthropic.claude-sonnet-4-6",  #https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html
}
judge_MODEL_Name = DEFAULT_MODEL.get(judge_)

RESULTS_DIR = os.path.join(RESULTS_DIR, judge_)  # save results in own folder
os.makedirs(RESULTS_DIR, exist_ok=True)


def make_judge(judge_: str, model: str, temperature: float = 0):
    judge_ = judge_.lower()
    if judge_ == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model, temperature=temperature)
    if judge_ == "cohere":
        from langchain_cohere import ChatCohere

        return ChatCohere(
            model=model,
            temperature=temperature,
            cohere_api_key=os.environ.get("COHERE_API_KEY"),
        )
    if judge_ == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            google_api_key=os.environ.get("GOOGLE_API_KEY"),
        )
    if judge_ == "bedrock":
        from langchain_aws import ChatBedrockConverse

        model_id = model if model.split(".", 1)[0] in ("us", "eu", "apac") else "us." + model
        return ChatBedrockConverse(
            model=model_id,
            temperature=temperature,
            provider="amazon",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        )
    if judge_ == "bedrock_claude_haiku":
        from langchain_aws import ChatBedrockConverse

        model_id = model if model.split(".", 1)[0] in ("us", "eu", "apac") else "us." + model
        return ChatBedrockConverse(
            model=model_id,
            temperature=temperature,
            provider="amazon",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        )
    if judge_ == "bedrock_claude_sonnet":
            from langchain_aws import ChatBedrockConverse
    
            model_id = model if model.split(".", 1)[0] in ("us", "eu", "apac") else "us." + model
            return ChatBedrockConverse(
                model=model_id,
                temperature=temperature,
                provider="amazon",
                region_name=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
            )
        
    raise ValueError(f"Unknown judge: {judge_!r}. Use openai, cohere, google, or bedrock")


def load_all_logs(eval_dir):
    rows, files = [], sorted(glob.glob(os.path.join(eval_dir, "**", "*.jsonl"), recursive=True))
    print("found", len(files), "jsonl files under", eval_dir)
    for path in files:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    print("loaded", len(rows), "log turns total")
    return rows


def save_json(obj, name):
    path = os.path.join(RESULTS_DIR, name)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
    print("saved", path)


def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ef.results_dir = RESULTS_DIR

    log_dataset = load_all_logs(EVAL_DIR)
    if not log_dataset:
        print("no log turns found nothing to do")
        return

    print(f"[judge] = {judge_}, model={judge_MODEL_Name}, results_dir={RESULTS_DIR}")
    judge_model = make_judge(judge_, judge_MODEL_Name, temperature=0)

    # build samples
    macro_samples = ef.stratified_sample(ef.build_Macro_samples(log_dataset))
    micro_samples = ef.build_micro_samples([s["raw_convo"] for s in macro_samples])

    # run judge + drift
    macro_results = ef.run_marco_eval(macro_samples, judge_model, macro_judge_prompt)
    micro_results = ef.run_mirco_eval(micro_samples, judge_model, micro_judge_prompt)
    drift = ef.compute_drift(micro_results)

    save_json(macro_results, f"Macro_{DATASET_NAME}_LLM-as-a-judge_c_plus_plus_dataset.json")
    save_json(micro_results, f"Micro_{DATASET_NAME}_LLM-as-a-judge_c_plus_plus_dataset.json")
    save_json(drift, f"Drift_{DATASET_NAME}_LLM-as-a-judge_c_plus_plus_dataset.json")

    macro_df, micro_df = pd.DataFrame(macro_results), pd.DataFrame(micro_results)
    summary = {
        DATASET_NAME: {
            "judge_": judge_,
            "judge_model": judge_MODEL_Name,
            "macro_pass_rate": macro_df["passed"].dropna().mean() if len(macro_df) else None,
            "micro_pass_rate": micro_df["passed"].dropna().mean() if len(micro_df) else None,
            "total_drift_rate": drift.get("total_drift_rate"),
            "qaulity_decline_rate": drift.get("qaulity_decline_rate"),
            "code_leak_rate": drift.get("code_leak_rate"),
        }
    }

    save_json(summary, "Summary_LLM-as-a-judge_c_plus_plus_dataset.json")
    print(json.dumps(summary, indent=2))

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as _plt

        def _savefig(*a, **k):
            _savefig.n += 1
            _plt.savefig(os.path.join(RESULTS_DIR, f"Chart_{_savefig.n}.png"))
            _plt.close()

        _savefig.n = 0
        if ef.plt is not None:
            ef.plt.show = _savefig
        ef.plot_metric_ci(micro_results, micro_metrics, DATASET_NAME + "MICRO PASS RATE (WILSON CI)")
        ef.plot_metric_ci(macro_results, macro_metrics, DATASET_NAME + "MACRO PASS RATE (WILSON CI)")

        ef.plot_cat(micro_results, ef.micro_groups, DATASET_NAME + "MICRO BY Category (WILSON CI)")
        ef.plot_cat(macro_results, ef.macro_groups, DATASET_NAME + "MACRO BY Category (WILSON CI)")
        print("saved", _savefig.n, "chart PNGS to", RESULTS_DIR)
    except Exception as _e:
        print("skipped visual:", _e)

    # determinitic checks FP and FN
    comp = ef.compare_judge(micro_results, DATASET_NAME)
    comp.to_csv(os.path.join(RESULTS_DIR, "Log_disagreements.csv"), index=False)

    print(ef.summary_(comp).to_string(index=False))

    ef.spot_check(micro_results, micro_metrics, DATASET_NAME).to_csv(
        os.path.join(RESULTS_DIR, "LOG_micro_spot_check.csv"),
        index=False,
    )

    ef.spot_check(macro_results, macro_metrics, DATASET_NAME).to_csv(
        os.path.join(RESULTS_DIR, "LOG_macro_spot_check.csv"),
        index=False,
    )

    print("wrote spot-check-sheets")


if __name__ == "__main__":
    main()
