from __future__ import annotations

from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.auth.models import CurrentUser
from rag_eng.schemas import EvaluationRunSummary


def _client() -> TestClient:
    return TestClient(create_app())


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


def test_admin_evaluations_config_allows_authorized_request(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.get_evaluation_config_payload",
        lambda: {
            "default_judge_provider": "bedrock",
            "default_judge_model": "anthropic.claude-haiku-4-5",
            "supported_judge_providers": ["openai", "bedrock"],
        },
    )

    client = _client()
    response = client.get(
        "/api/admin/evaluations/config",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()["default_judge_provider"] == "bedrock"


def test_admin_evaluations_runs_launches_with_static_token(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    captured: dict[str, object] = {}

    def fake_launch(payload, current_user=None):
        captured["payload"] = payload
        captured["current_user"] = current_user
        return _summary()

    monkeypatch.setattr("rag_eng.api.launch_evaluation_run", fake_launch)

    client = _client()
    response = client.post(
        "/api/admin/evaluations/runs",
        headers={"X-Admin-Token": "expected-token"},
        json={
            "judge_provider": "bedrock",
            "judge_model": "anthropic.claude-haiku-4-5",
            "dataset_s3_uri": "s3://codingrabbit-data-dev/evaluation/offline/run-123/input/turn_snapshots.jsonl",
            "run_label": "Nightly eval",
        },
    )

    assert response.status_code == 200
    assert response.json()["evaluation_run_id"] == "run-123"
    assert captured["current_user"] is None


def test_admin_evaluations_runs_launches_with_cognito_admin(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    captured: dict[str, object] = {}

    def fake_launch(payload, current_user=None):
        captured["payload"] = payload
        captured["current_user"] = current_user
        return _summary()

    monkeypatch.setattr("rag_eng.api.launch_evaluation_run", fake_launch)
    monkeypatch.setattr(
        "rag_eng.api.verify_cognito_access_token",
        lambda token, settings: CurrentUser(
            cognito_sub="admin-sub",
            email="admin@example.edu",
            groups=["Admins"],
            primary_role="admin",
        ),
    )

    client = _client()
    response = client.post(
        "/api/admin/evaluations/runs",
        headers={"Authorization": "Bearer admin-token"},
        json={
            "judge_provider": "bedrock",
            "judge_model": "anthropic.claude-haiku-4-5",
            "dataset_s3_uri": "s3://codingrabbit-data-dev/evaluation/offline/run-123/input/turn_snapshots.jsonl",
            "run_label": "Nightly eval",
        },
    )

    assert response.status_code == 200
    assert response.json()["evaluation_run_id"] == "run-123"
    assert isinstance(captured["current_user"], CurrentUser)
    assert captured["current_user"].primary_role == "admin"


def test_admin_evaluations_runs_listing_and_detail_are_available(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    summary = _summary()
    monkeypatch.setattr(
        "rag_eng.api.list_evaluation_runs",
        lambda limit=25, status=None: [summary],
    )
    monkeypatch.setattr(
        "rag_eng.api.get_evaluation_run",
        lambda run_id: summary.model_copy(update={"evaluation_run_id": run_id}),
    )
    monkeypatch.setattr(
        "rag_eng.api.get_evaluation_overview",
        lambda limit=25: {
            "total_runs": 1,
            "active_runs": 1,
            "status_counts": {"running": 1},
            "recent_runs": [summary.model_dump(mode="json")],
        },
    )

    client = _client()

    list_response = client.get(
        "/api/admin/evaluations/runs",
        headers={"X-Admin-Token": "expected-token"},
    )
    detail_response = client.get(
        "/api/admin/evaluations/runs/run-999",
        headers={"X-Admin-Token": "expected-token"},
    )
    overview_response = client.get(
        "/api/admin/evaluations/overview",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert list_response.status_code == 200
    assert list_response.json()[0]["evaluation_run_id"] == "run-123"
    assert detail_response.status_code == 200
    assert detail_response.json()["evaluation_run_id"] == "run-999"
    assert overview_response.status_code == 200
    assert overview_response.json()["total_runs"] == 1
