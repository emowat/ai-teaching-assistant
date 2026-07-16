from __future__ import annotations

from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.app_registry import MembershipAccessDeniedError
from rag_eng.auth.dependencies import require_authenticated_user
from rag_eng.auth.models import CurrentUser
from rag_eng.schemas import AdminSection


def _client() -> TestClient:
    return TestClient(create_app())


def _professor_user() -> CurrentUser:
    return CurrentUser(
        cognito_sub="prof-sub",
        email="prof@example.edu",
        primary_role="professor",
    )


def _admin_section(section_id: str = "mit14-fall-001") -> AdminSection:
    return AdminSection(
        section_id=section_id,
        course_id="mit14",
        course_display_name="MIT 6.0014",
        display_name="MIT 6.0014 Section A",
        term="Fall 2026",
        is_active=False,
        professor_count=1,
        ta_count=0,
        student_count=0,
        memberships=[],
        created_at="2026-06-20T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        archived_at="2026-07-16T00:00:00+00:00",
    )


def test_admin_archive_section_route_archives_and_returns_section(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    captured: dict[str, object] = {}

    def fake_archive(section_id: str) -> None:
        captured["section_id"] = section_id

    monkeypatch.setattr("rag_eng.api.archive_section_data", fake_archive)
    monkeypatch.setattr(
        "rag_eng.api.get_admin_section", lambda section_id: _admin_section(section_id)
    )

    client = _client()
    response = client.post(
        "/admin/sections/mit14-fall-001/archive",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert captured["section_id"] == "mit14-fall-001"
    body = response.json()
    assert body["section_id"] == "mit14-fall-001"
    assert body["archived_at"] == "2026-07-16T00:00:00+00:00"
    assert body["is_active"] is False


def test_admin_archive_section_route_requires_admin_token() -> None:
    client = _client()
    response = client.post("/admin/sections/mit14-fall-001/archive")
    assert response.status_code == 401


def test_professor_archive_section_route_calls_archive_when_authorized(
    monkeypatch,
) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    monkeypatch.setattr(
        "rag_eng.api.require_section_membership",
        lambda current_user, section_id, allowed_roles=None: None,
    )
    captured: dict[str, object] = {}

    def fake_archive(section_id: str) -> None:
        captured["section_id"] = section_id

    monkeypatch.setattr("rag_eng.api.archive_section_data", fake_archive)

    try:
        response = client.post("/professor/sections/mit14-fall-001/archive")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert captured["section_id"] == "mit14-fall-001"


def test_professor_archive_section_route_denies_non_member(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    def _raise(current_user, section_id, allowed_roles=None):
        raise MembershipAccessDeniedError("User is not assigned to this section.")

    monkeypatch.setattr("rag_eng.api.require_section_membership", _raise)
    archive_called = {"called": False}
    monkeypatch.setattr(
        "rag_eng.api.archive_section_data",
        lambda section_id: archive_called.__setitem__("called", True),
    )

    try:
        response = client.post("/professor/sections/other-section/archive")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 403
    assert archive_called["called"] is False
