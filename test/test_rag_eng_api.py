from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag.schemas import QueryInput, RetrievalResult
from rag_eng.api import create_app
from rag_eng.auth.models import CurrentUser
from rag_eng.schemas import (
    IngestionJobResponse,
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
    QueryResponse,
)


@pytest.fixture()
def client() -> TestClient:
    """Create a fresh FastAPI test client for each API test."""
    return TestClient(create_app())


def _base_query_payload() -> dict:
    """Return the smallest valid payload for the query route."""
    return QueryInput(
        student_message="Why does this crash?",
        week=3,
    ).model_dump()


def test_health_endpoint_returns_service_state(monkeypatch, client: TestClient) -> None:
    monkeypatch.setattr(
        "rag_eng.api.get_health",
        lambda: HealthResponse(
            ready=True,
            qdrant_configured=True,
            cohere_configured=True,
            qdrant_reachable=True,
            cohere_reachable=True,
            message="Ready.",
        ),
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["message"] == "Ready."


def test_query_endpoint_uses_default_result_count(
    monkeypatch, client: TestClient
) -> None:
    captured: dict[str, object] = {}

    def fake_run_query(payload):
        captured["result_count"] = payload.result_count
        captured["rerank_strategy"] = payload.rerank_strategy
        return QueryResponse(
            answer="Check the pointer before dereferencing it.",
            retrieval_result=RetrievalResult(
                formatted_context="[Pedagogical_Context]\nPointers"
            ),
            formatted_context="[Pedagogical_Context]\nPointers",
        )

    monkeypatch.setattr("rag_eng.api.run_query", fake_run_query)

    response = client.post("/query", json=_base_query_payload())

    assert response.status_code == 200
    assert captured["result_count"] == 8
    assert captured["rerank_strategy"] == "similarity"
    assert response.json()["answer"]
    assert response.json()["formatted_context"]


def test_query_endpoint_forwards_explicit_result_count(
    monkeypatch, client: TestClient
) -> None:
    captured: dict[str, object] = {}

    def fake_run_query(payload):
        captured["result_count"] = payload.result_count
        captured["rerank_strategy"] = payload.rerank_strategy
        return QueryResponse(
            answer="Check the pointer before dereferencing it.",
            retrieval_result=RetrievalResult(
                formatted_context="[Pedagogical_Context]\nPointers"
            ),
            formatted_context="[Pedagogical_Context]\nPointers",
        )

    monkeypatch.setattr("rag_eng.api.run_query", fake_run_query)

    response = client.post(
        "/query",
        json=_base_query_payload() | {
            "result_count": 7,
            "rerank_strategy": "mmr_0.7",
        },
    )

    assert response.status_code == 200
    assert captured["result_count"] == 7
    assert captured["rerank_strategy"] == "mmr_0.7"


def test_query_endpoint_rejects_invalid_result_count(client: TestClient) -> None:
    response = client.post("/query", json=_base_query_payload() | {"result_count": 0})

    assert response.status_code == 422


def test_query_endpoint_returns_500_on_service_exception(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setattr(
        "rag_eng.api.run_query",
        lambda payload: (_ for _ in ()).throw(ValueError("boom")),
    )

    response = client.post("/query", json=_base_query_payload())

    assert response.status_code == 500
    assert response.json()["detail"] == "boom"


def test_openapi_exposes_query_schema_examples(client: TestClient) -> None:
    """The OpenAPI document should publish the request/response schema examples."""
    openapi = client.get("/openapi.json").json()
    schemas = openapi["components"]["schemas"]

    assert schemas["QueryPayload"]["examples"]
    assert schemas["QueryResult"]["examples"]
    assert "result_count" in schemas["QueryPayload"]["properties"]
    assert "rerank_strategy" in schemas["QueryPayload"]["properties"]
    assert "guardrail" in schemas["QueryResult"]["properties"]
    assert "input_guardrail" in schemas["QueryResult"]["properties"]


def test_chat_endpoint_forwards_course_id(monkeypatch, client: TestClient) -> None:
    captured: dict[str, str | None] = {}

    async def fake_run_chat(
        messages,
        model_name,
        settings,
        stream=False,
        course_id=None,
        session_id=None,
        request_id=None,
        turn_id=None,
        section_id=None,
        result_count=None,
        rerank_strategy=None,
    ):
        captured["course_id"] = course_id
        captured["session_id"] = session_id
        captured["request_id"] = request_id
        captured["turn_id"] = turn_id
        captured["section_id"] = section_id
        captured["result_count"] = result_count
        captured["rerank_strategy"] = rerank_strategy
        return {"message": {"content": "Try checking whether the pointer is initialized."}}

    monkeypatch.setattr("rag_eng.api.run_chat", fake_run_chat)

    response = client.post(
        "/api/chat",
        json={
            "model": "codingrabbit",
            "course_id": "mit14",
            "session_id": "sess-123",
            "request_id": "req-456",
            "turn_id": "turn-789",
            "section_id": "sec-1",
            "result_count": 8,
            "rerank_strategy": "mmr_0.9",
            "messages": [{"role": "user", "content": "Why does my pointer segfault?"}],
        },
    )

    assert response.status_code == 200
    assert captured["course_id"] == "mit14"
    assert captured["session_id"] == "sess-123"
    assert captured["request_id"] == "req-456"
    assert captured["turn_id"] == "turn-789"
    assert captured["section_id"] == "sec-1"
    assert captured["result_count"] == 8
    assert captured["rerank_strategy"] == "mmr_0.9"


def test_admin_ensure_requires_token_when_configured(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    unauthorized = client.post("/admin/index/ensure")

    assert unauthorized.status_code == 401


def test_admin_ensure_allows_authorized_request(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.ensure_index_service",
        lambda: IndexEnsureResponse(
            success=True,
            collection_name="capstone",
            created_collection=False,
            indexed_documents=1,
            message="ok",
        ),
    )

    response = client.post(
        "/admin/index/ensure",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["collection_name"] == "capstone"


def test_admin_ensure_is_open_when_token_not_configured(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(
        "rag_eng.api.ensure_index_service",
        lambda: IndexEnsureResponse(
            success=True,
            collection_name="capstone",
            created_collection=True,
            indexed_documents=3,
            message="ok",
        ),
    )

    response = client.post("/admin/index/ensure")

    assert response.status_code == 200
    assert response.json()["created_collection"] is True


def test_admin_ensure_returns_500_on_service_exception(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.ensure_index_service",
        lambda: (_ for _ in ()).throw(RuntimeError("index failure")),
    )

    response = client.post(
        "/admin/index/ensure",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "index failure"


def test_admin_rebuild_allows_authorized_request(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.rebuild_index_service",
        lambda: IndexRebuildResponse(
            success=True,
            collection_name="capstone",
            indexed_documents=12,
            message="rebuilt",
        ),
    )

    response = client.post(
        "/admin/index/rebuild",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["indexed_documents"] == 12


def test_admin_rebuild_returns_500_on_service_exception(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.rebuild_index_service",
        lambda: (_ for _ in ()).throw(RuntimeError("rebuild failure")),
    )

    response = client.post(
        "/admin/index/rebuild",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "rebuild failure"


def _ingestion_job_response(
    *,
    job_id: str = "job-123",
    status: str = "running",
) -> IngestionJobResponse:
    return IngestionJobResponse(
        job_id=job_id,
        course_id="mit14",
        job_kind="chunk-index",
        status=status,
        message="ECS ingestion task launched.",
        registered=True,
        course_corpus_version_id=job_id,
        ecs_cluster="cluster",
        ecs_task_definition="taskdef",
        ecs_container_name="worker",
        ecs_task_arn="arn:aws:ecs:task/123",
        collection_name="course_knowledge",
        bucket="codingrabbit-data-dev",
        input_prefix="parsed_json/mit14",
        output_prefix=None,
        prepared_output_prefix="prepared_chunks/mit14",
        request_payload={
            "job_id": job_id,
            "course_id": "mit14",
            "job_kind": "chunk-index",
            "bucket": "codingrabbit-data-dev",
            "input_prefix": "parsed_json/mit14",
            "prepared_output_prefix": "prepared_chunks/mit14",
            "collection_name": "course_knowledge",
            "recreate_collection": False,
            "course_corpus_version_id": job_id,
        },
        ecs_response={
            "tasks": [{"taskArn": "arn:aws:ecs:task/123"}],
            "failures": [],
        },
        created_at="2026-06-19T00:00:00+00:00",
        updated_at="2026-06-19T00:00:00+00:00",
        started_at="2026-06-19T00:00:00+00:00",
        completed_at=None,
    )


def test_admin_launch_ingestion_requires_token_when_configured(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    response = client.post(
        "/admin/ingestion/launch",
        json={
            "course_id": "mit14",
            "job_kind": "chunk-index",
            "bucket": "codingrabbit-data-dev",
            "input_prefix": "parsed_json/mit14",
            "prepared_output_prefix": "prepared_chunks/mit14",
        },
    )

    assert response.status_code == 401


def test_admin_launch_ingestion_allows_authorized_request(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.launch_ingestion_job",
        lambda payload: _ingestion_job_response(),
    )

    response = client.post(
        "/admin/ingestion/launch",
        headers={"X-Admin-Token": "expected-token"},
        json={
            "course_id": "mit14",
            "job_kind": "chunk-index",
            "bucket": "codingrabbit-data-dev",
            "input_prefix": "parsed_json/mit14",
            "prepared_output_prefix": "prepared_chunks/mit14",
        },
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"
    assert response.json()["course_corpus_version_id"] == "job-123"


def test_admin_launch_ingestion_allows_admin_bearer_request(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.launch_ingestion_job",
        lambda payload: _ingestion_job_response(),
    )

    def _admin(_token: str, _settings) -> CurrentUser:
        return CurrentUser(
            cognito_sub="admin-sub-1",
            email="admin@test.codingrabbit.dev",
            groups=["Admins"],
            primary_role="admin",
        )

    monkeypatch.setattr("rag_eng.api.verify_cognito_access_token", _admin)

    response = client.post(
        "/admin/ingestion/launch",
        headers={"Authorization": "Bearer valid-token"},
        json={
            "course_id": "mit14",
            "job_kind": "chunk-index",
            "bucket": "codingrabbit-data-dev",
            "input_prefix": "parsed_json/mit14",
            "prepared_output_prefix": "prepared_chunks/mit14",
        },
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"


def test_admin_get_ingestion_job_returns_404_when_missing(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.get_ingestion_job",
        lambda job_id: (_ for _ in ()).throw(LookupError(job_id)),
    )

    response = client.get(
        "/admin/ingestion/jobs/job-123",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 404


def test_admin_get_ingestion_job_allows_authorized_request(
    monkeypatch, client: TestClient
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.get_ingestion_job",
        lambda job_id: _ingestion_job_response(job_id=job_id),
    )

    response = client.get(
        "/admin/ingestion/jobs/job-123",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-123"
