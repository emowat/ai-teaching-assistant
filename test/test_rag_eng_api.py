from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag.schemas import QueryInput, RetrievalResult
from rag_eng.api import create_app
from rag_eng.schemas import (
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
    captured: dict[str, int] = {}

    def fake_run_query(payload):
        captured["result_count"] = payload.result_count
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
    assert captured["result_count"] == 5
    assert response.json()["answer"]
    assert response.json()["formatted_context"]


def test_query_endpoint_forwards_explicit_result_count(
    monkeypatch, client: TestClient
) -> None:
    captured: dict[str, int] = {}

    def fake_run_query(payload):
        captured["result_count"] = payload.result_count
        return QueryResponse(
            answer="Check the pointer before dereferencing it.",
            retrieval_result=RetrievalResult(
                formatted_context="[Pedagogical_Context]\nPointers"
            ),
            formatted_context="[Pedagogical_Context]\nPointers",
        )

    monkeypatch.setattr("rag_eng.api.run_query", fake_run_query)

    response = client.post("/query", json=_base_query_payload() | {"result_count": 7})

    assert response.status_code == 200
    assert captured["result_count"] == 7


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
    ):
        captured["course_id"] = course_id
        captured["session_id"] = session_id
        captured["request_id"] = request_id
        captured["turn_id"] = turn_id
        captured["section_id"] = section_id
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
            "messages": [{"role": "user", "content": "Why does my pointer segfault?"}],
        },
    )

    assert response.status_code == 200
    assert captured["course_id"] == "mit14"
    assert captured["session_id"] == "sess-123"
    assert captured["request_id"] == "req-456"
    assert captured["turn_id"] == "turn-789"
    assert captured["section_id"] == "sec-1"


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
