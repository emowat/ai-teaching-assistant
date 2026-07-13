from __future__ import annotations

import json
from pathlib import Path

from model_eval.evaluation_worker import (
    BedrockJudgeProvider,
    _build_judge_provider,
    load_dataset_records,
    load_worker_settings,
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
