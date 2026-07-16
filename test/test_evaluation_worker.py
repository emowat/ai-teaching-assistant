from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from model_eval.evaluation_worker import (
    BedrockJudgeProvider,
    _build_judge_provider,
    load_dataset_records,
    load_worker_settings,
    run_evaluation_job,
)


def test_load_dataset_records_reads_jsonl_and_tracks_counts(tmp_path: Path) -> None:
    dataset = tmp_path / "turn_snapshots.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps({"turn_id": "turn-1", "section_id": "s1"}),
                "not-json",
                json.dumps({"turn_id": "turn-2", "section_id": "s1"}),
            ]
        ),
        encoding="utf-8",
    )

    records, manifest = load_dataset_records(
        str(dataset),
        region="us-east-1",
        profile_name=None,
    )

    assert len(records) == 2
    assert manifest["source_kind"] == "local-file"
    assert manifest["total_rows"] == 3
    assert manifest["usable_rows"] == 2
    assert manifest["skipped_rows"] == 1


def test_load_worker_settings_resolves_default_results_prefix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("S3_DATA_BUCKET", "codingrabbit-data-dev")
    monkeypatch.setenv("EVALUATION_DEFAULT_JUDGE_PROVIDER", "bedrock")
    monkeypatch.setenv("EVALUATION_DEFAULT_JUDGE_MODEL", "anthropic.claude-haiku-4-5")
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://example")

    settings = load_worker_settings(
        [
            "--evaluation-run-id",
            "eval-123",
            "--dataset-s3-uri",
            "s3://codingrabbit-data-dev/eval/input.jsonl",
            "--output-dir",
            str(tmp_path),
        ]
    )

    assert settings.evaluation_run_id == "eval-123"
    assert settings.judge_provider == "bedrock"
    assert settings.judge_model == "anthropic.claude-haiku-4-5"
    assert settings.results_s3_prefix == (
        "s3://codingrabbit-data-dev/evaluation/offline/eval-123"
    )
    assert settings.database_url == "postgresql://example"


def test_build_judge_provider_normalizes_bedrock_model_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("S3_DATA_BUCKET", "codingrabbit-data-dev")
    monkeypatch.setenv("EVALUATION_DEFAULT_JUDGE_PROVIDER", "bedrock")
    monkeypatch.setenv("EVALUATION_DEFAULT_JUDGE_MODEL", "anthropic.claude-haiku-4-5")
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://example")

    settings = load_worker_settings(
        [
            "--evaluation-run-id",
            "eval-456",
            "--dataset-s3-uri",
            "s3://codingrabbit-data-dev/eval/input.jsonl",
            "--output-dir",
            str(tmp_path),
        ]
    )

    provider = _build_judge_provider(settings)

    assert isinstance(provider, BedrockJudgeProvider)
    assert provider._config.model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_run_evaluation_job_calls_ta_effectiveness_ingestion(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """run_evaluation_job() must hand its macro/micro/drift results to the
    TA-effectiveness ingestion module exactly once, without needing a real
    judge model, Aurora connection, or S3 access."""
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("S3_DATA_BUCKET", "codingrabbit-data-dev")
    monkeypatch.setenv("EVALUATION_DEFAULT_JUDGE_PROVIDER", "bedrock")
    monkeypatch.setenv("EVALUATION_DEFAULT_JUDGE_MODEL", "anthropic.claude-haiku-4-5")
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://example")

    dataset = tmp_path / "turn_snapshots.jsonl"
    dataset.write_text(
        json.dumps({"turn_id": "turn-1", "session_id": "session-1"}) + "\n",
        encoding="utf-8",
    )

    settings = load_worker_settings(
        [
            "--evaluation-run-id",
            "eval-789",
            "--dataset-s3-uri",
            str(dataset),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    macro_samples = [{"conversation_id": 0, "session_id": "session-1", "raw_convo": []}]
    micro_samples = [
        {"conversation_id": 0, "session_id": "session-1", "turn_id": "turn-1", "turn_index": 0}
    ]
    macro_results = [
        {
            "conversation_id": 0,
            "session_id": "session-1",
            "mode": "homework",
            "total_ratio_score": 0.9,
            "passed": True,
        }
    ]
    micro_results = [
        {
            "conversation_id": 0,
            "session_id": "session-1",
            "turn_id": "turn-1",
            "turn_index": 0,
            "mode": "homework",
            "total_ratio_score": 0.8,
            "passed": True,
            "direct_code_leakage": 1,
        }
    ]

    monkeypatch.setattr(
        "model_eval.eval_functions.build_Macro_samples", lambda records: macro_samples
    )
    monkeypatch.setattr(
        "model_eval.eval_functions.stratified_sample", lambda samples: samples
    )
    monkeypatch.setattr(
        "model_eval.eval_functions.build_micro_samples", lambda raw_convos: micro_samples
    )
    monkeypatch.setattr(
        "model_eval.eval_functions.run_marco_eval",
        lambda samples, judge_model, prompt: macro_results,
    )
    monkeypatch.setattr(
        "model_eval.eval_functions.run_mirco_eval",
        lambda samples, judge_model, prompt: micro_results,
    )
    monkeypatch.setattr(
        "model_eval.eval_functions.per_metric_pass_rate", lambda df, metrics: {}
    )
    monkeypatch.setattr(
        "model_eval.eval_functions.compare_judge",
        lambda micro, name: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "model_eval.eval_functions.spot_check",
        lambda results, metrics, name: pd.DataFrame(),
    )
    monkeypatch.setattr(
        "model_eval.evaluation_worker._build_judge_provider", lambda settings: object()
    )
    monkeypatch.setattr(
        "model_eval.evaluation_worker._render_charts", lambda **kwargs: []
    )
    monkeypatch.setattr(
        "model_eval.evaluation_worker._upload_directory_to_s3", lambda **kwargs: []
    )

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class _FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def cursor(self):
            return _FakeCursor()

    monkeypatch.setattr(
        "model_eval.evaluation_worker._aurora_connection",
        lambda settings: _FakeConnection(),
    )

    captured: dict[str, object] = {}

    def fake_ingest(
        connection,
        *,
        evaluation_run_id,
        macro_results,
        micro_results,
        drift_results,
        macro_metric_names,
        micro_metric_names,
        scored_at=None,
    ):
        captured["called"] = captured.get("called", 0) + 1
        captured["evaluation_run_id"] = evaluation_run_id
        captured["macro_results"] = macro_results
        captured["micro_results"] = micro_results
        return {
            "sessions_written": 1,
            "turns_written": 1,
            "sessions_skipped_no_session_row": 0,
        }

    monkeypatch.setattr(
        "model_eval.evaluation_worker.ingest_ta_effectiveness_scores", fake_ingest
    )

    summary = run_evaluation_job(settings)

    assert summary.evaluation_run_id == "eval-789"
    assert captured["called"] == 1
    assert captured["evaluation_run_id"] == "eval-789"
    assert captured["macro_results"] == macro_results
    assert captured["micro_results"] == micro_results
