from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.auth.models import CurrentUser


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_me_requires_bearer_token(client: TestClient) -> None:
    response = client.get("/me")
    assert response.status_code == 401
    assert "Missing Bearer" in response.json()["detail"]


def test_me_rejects_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    from fastapi import HTTPException

    def _fail(_token: str, _settings) -> CurrentUser:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.")

    monkeypatch.setattr("rag_eng.auth.dependencies.verify_cognito_access_token", _fail)

    response = client.get("/me", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401


def test_me_returns_student_profile(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    def _student(_token: str, _settings) -> CurrentUser:
        return CurrentUser(
            cognito_sub="student-sub-123",
            email="student@test.codingrabbit.dev",
            username="student@test.codingrabbit.dev",
            groups=["Students"],
            primary_role="student",
        )

    monkeypatch.setattr(
        "rag_eng.auth.dependencies.verify_cognito_access_token", _student
    )
    monkeypatch.setattr("rag_eng.api.sync_application_user", lambda _user: None)

    response = client.get("/me", headers={"Authorization": "Bearer valid-token"})
    assert response.status_code == 200
    body = response.json()
    assert body["cognito_sub"] == "student-sub-123"
    assert body["primary_role"] == "student"
    assert body["groups"] == ["Students"]


def test_me_returns_admin_profile(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    def _admin(_token: str, _settings) -> CurrentUser:
        return CurrentUser(
            cognito_sub="admin-sub-456",
            email="admin@test.codingrabbit.dev",
            groups=["Admins"],
            primary_role="admin",
        )

    monkeypatch.setattr("rag_eng.auth.dependencies.verify_cognito_access_token", _admin)

    response = client.get("/me", headers={"Authorization": "Bearer valid-token"})
    assert response.status_code == 200
    assert response.json()["primary_role"] == "admin"


def test_require_role_blocks_student(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import Depends

    from rag_eng.auth.dependencies import require_role

    def _student(_token: str, _settings) -> CurrentUser:
        return CurrentUser(
            cognito_sub="student-sub",
            groups=["Students"],
            primary_role="student",
        )

    monkeypatch.setattr(
        "rag_eng.auth.dependencies.verify_cognito_access_token", _student
    )

    app = create_app()

    @app.get("/admin-only-test")
    def admin_only(_user: CurrentUser = Depends(require_role("admin"))):
        return {"ok": True}

    test_client = TestClient(app)
    response = test_client.get(
        "/admin-only-test",
        headers={"Authorization": "Bearer valid-token"},
    )
    assert response.status_code == 403
