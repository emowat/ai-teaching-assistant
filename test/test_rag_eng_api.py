from __future__ import annotations

from fastapi.testclient import TestClient

from rag.schemas import QueryInput, RetrievalResult
from rag_eng.api import create_app
from rag_eng.schemas import (
    HealthResponse,
    IndexEnsureResponse,
    QueryResponse,
)


def test_health_endpoint(monkeypatch) -> None:
    app = create_app()
    client = TestClient(app)
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


def test_query_endpoint_returns_answer(monkeypatch) -> None:
    app = create_app()
    client = TestClient(app)

    monkeypatch.setattr(
        "rag_eng.api.run_query",
        lambda payload: QueryResponse(
            answer="Check the pointer before dereferencing it.",
            retrieval_result=RetrievalResult(formatted_context="[Pedagogical_Context]\nPointers"),
            formatted_context="[Pedagogical_Context]\nPointers",
        ),
    )

    response = client.post(
        "/query",
        json=QueryInput(
            student_message="Why does this crash?",
            week=3,
        ).model_dump(),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["answer"]
    assert data["formatted_context"]


def test_admin_endpoint_requires_token(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    app = create_app()
    client = TestClient(app)
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

    unauthorized = client.post("/admin/index/ensure")
    authorized = client.post(
        "/admin/index/ensure",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
