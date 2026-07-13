from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone

from rag_eng.auth.models import CurrentUser
from rag_eng.evaluation_jobs import (
    EvaluationLaunchRuntimeConfig,
    export_turn_snapshots_to_s3,
    get_evaluation_config_payload,
    launch_evaluation_run,
)
from rag_eng.schemas import EvaluationRunCreate, EvaluationRunScope, EvaluationRunSummary


@dataclass
class _FakeS3Client:
    put_objects: list[dict[str, object]]

    def put_object(self, **kwargs):
        self.put_objects.append(kwargs)


class _FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeEcsClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_task(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "tasks": [
                {
                    "taskArn": "arn:aws:ecs:us-east-1:123456789012:task/abc123",
                }
            ],
            "failures": [],
        }


def _runtime() -> EvaluationLaunchRuntimeConfig:
    return EvaluationLaunchRuntimeConfig(
        database_url="postgresql://example",
        connect_timeout_seconds=5,
        aws_region="us-east-1",
        aws_profile="codingrabbit-dev",
        ecs_cluster="codingrabbit-rag-eng",
        ecs_task_definition="codingrabbit-evaluation-worker",
        ecs_container_name="evaluation-worker",
        ecs_launch_type="FARGATE",
        ecs_platform_version="LATEST",
        ecs_assign_public_ip="ENABLED",
        ecs_subnet_ids=("subnet-a", "subnet-b"),
        ecs_security_group_ids=("sg-a",),
        results_bucket="codingrabbit-data-dev",
        results_prefix="evaluation/offline",
        default_judge_provider="bedrock",
        default_judge_model="anthropic.claude-haiku-4-5",
        export_timezone="America/Los_Angeles",
    )


def _summary(run_id: str = "run-123") -> EvaluationRunSummary:
    return EvaluationRunSummary(
        evaluation_run_id=run_id,
        run_label="Nightly eval",
        notes="",
        requested_by_user_id="user-1",
        requested_by_cognito_sub="admin-sub",
        requested_by_email="admin@example.edu",
        judge_provider="bedrock",
        judge_model="anthropic.claude-haiku-4-5",
        input_dataset_s3_uri="s3://codingrabbit-data-dev/evaluation/offline/run-123/input/turn_snapshots.jsonl",
        results_s3_prefix="s3://codingrabbit-data-dev/evaluation/offline/run-123/results",
        course_id="mit14",
        section_id="mit14-fall-001",
        scope_start_date="2026-07-01",
        scope_end_date="2026-07-07",
        scope_metadata={"export_scope": {"course_id": "mit14"}},
        status="running",
        message="Launched.",
        total_rows=10,
        usable_rows=9,
        skipped_rows=1,
        macro_pass_rate=0.8,
        micro_pass_rate=0.75,
        drift_rate=0.1,
        quality_decline_rate=0.05,
        code_leak_rate=0.0,
        summary={"overall": "ok"},
        artifacts=[],
        metrics=[],
        ecs_cluster="codingrabbit-rag-eng",
        ecs_task_definition="codingrabbit-evaluation-worker",
        ecs_container_name="evaluation-worker",
        ecs_task_arn="arn:aws:ecs:us-east-1:123456789012:task/abc123",
        created_at="2026-07-13T00:00:00+00:00",
        updated_at="2026-07-13T00:00:00+00:00",
        started_at="2026-07-13T00:05:00+00:00",
        completed_at=None,
    )


def test_get_evaluation_config_payload_uses_runtime_values() -> None:
    payload = get_evaluation_config_payload(runtime=_runtime())

    assert payload["default_judge_provider"] == "bedrock"
    assert payload["default_judge_model"] == "anthropic.claude-haiku-4-5"
    assert payload["results_bucket"] == "codingrabbit-data-dev"
    assert payload["ecs"]["task_definition"] == "codingrabbit-evaluation-worker"
    assert payload["ecs"]["subnet_ids"] == ["subnet-a", "subnet-b"]


def test_export_turn_snapshots_to_s3_writes_jsonl_and_manifest(monkeypatch) -> None:
    rows = [
        (
            datetime(2026, 7, 2, 15, 30, tzinfo=timezone.utc),
            {
                "trace": {
                    "session_id": "sess-1",
                    "turn_id": "turn-1",
                    "turn_index": 1,
                },
                "message": "one",
            },
        ),
        (
            datetime(2026, 7, 2, 16, 30, tzinfo=timezone.utc),
            {
                "trace": {
                    "session_id": "sess-2",
                    "turn_id": "turn-2",
                    "turn_index": 2,
                },
                "message": "two",
            },
        ),
    ]
    fake_client = _FakeS3Client(put_objects=[])

    monkeypatch.setattr(
        "rag_eng.evaluation_jobs._query_turn_snapshots",
        lambda *_args, **_kwargs: rows,
    )
    monkeypatch.setattr(
        "rag_eng.evaluation_jobs._build_s3_client",
        lambda **_kwargs: fake_client,
    )

    result = export_turn_snapshots_to_s3(
        database_url="postgresql://example",
        bucket="codingrabbit-data-dev",
        prefix="evaluation/offline/run-123/input",
        start_date=date(2026, 7, 2),
        end_date=date(2026, 7, 2),
        profile="codingrabbit-dev",
        region="us-east-1",
    )

    assert result["dataset_s3_uri"].endswith("/turn_snapshots.jsonl")
    assert result["manifest"]["total_rows"] == 2
    assert fake_client.put_objects[0]["Key"] == (
        "evaluation/offline/run-123/input/turn_snapshots.jsonl"
    )
    assert fake_client.put_objects[1]["Key"] == (
        "evaluation/offline/run-123/input/manifest.json"
    )

    exported_rows = [
        json.loads(line)
        for line in fake_client.put_objects[0]["Body"].decode("utf-8").splitlines()
    ]
    assert exported_rows[0]["trace"]["turn_id"] == "turn-1"
    assert exported_rows[1]["trace"]["turn_id"] == "turn-2"


def test_launch_evaluation_run_submits_task_and_returns_summary(monkeypatch) -> None:
    request = EvaluationRunCreate(
        judge_provider="bedrock",
        judge_model="anthropic.claude-haiku-4-5",
        export_scope=EvaluationRunScope(
            course_id="mit14",
            section_id="mit14-fall-001",
            start_date="2026-07-01",
            end_date="2026-07-07",
        ),
        run_label="Nightly eval",
        notes="Section benchmark",
    )
    runtime = _runtime()
    fake_ecs = _FakeEcsClient()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "rag_eng.evaluation_jobs.load_evaluation_launch_runtime_config",
        lambda env=None: runtime,
    )
    monkeypatch.setattr(
        "rag_eng.evaluation_jobs.export_turn_snapshots_to_s3",
        lambda **_kwargs: {
            "dataset_s3_uri": "s3://codingrabbit-data-dev/evaluation/offline/run-123/input/turn_snapshots.jsonl",
            "manifest": {"total_rows": 2, "usable_rows": 2, "skipped_rows": 0},
        },
    )
    monkeypatch.setattr(
        "rag_eng.evaluation_jobs.connect_postgres_with_retry",
        lambda *_args, **_kwargs: _FakeConnection(),
    )
    monkeypatch.setattr(
        "rag_eng.evaluation_jobs._insert_run_row",
        lambda **kwargs: captured.__setitem__("insert", kwargs),
    )
    monkeypatch.setattr(
        "rag_eng.evaluation_jobs._update_run_status",
        lambda **kwargs: captured.setdefault("updates", []).append(kwargs),
    )
    monkeypatch.setattr(
        "rag_eng.evaluation_jobs.sync_application_user",
        lambda current_user: {"user_id": "user-1"} if current_user else None,
    )
    monkeypatch.setattr(
        "rag_eng.evaluation_jobs.get_evaluation_run",
        lambda run_id, runtime=None: _summary(run_id),
    )

    result = launch_evaluation_run(
        request,
        current_user=CurrentUser(
            cognito_sub="admin-sub",
            email="admin@example.edu",
            groups=["Admins"],
            primary_role="admin",
        ),
        ecs_client=fake_ecs,
    )

    assert result.evaluation_run_id == captured["insert"]["run_id"]
    assert captured["insert"]["course_id"] == "mit14"
    assert captured["insert"]["section_id"] == "mit14-fall-001"
    assert captured["updates"][0]["status"] == "running"
    assert fake_ecs.calls[0]["cluster"] == "codingrabbit-rag-eng"
    command = fake_ecs.calls[0]["overrides"]["containerOverrides"][0]["command"]
    assert "--evaluation-run-id" in command
    assert "--judge-provider" in command
    assert "--dataset-s3-uri" in command
