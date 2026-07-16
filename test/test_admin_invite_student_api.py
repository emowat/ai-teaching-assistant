from __future__ import annotations

from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.app_registry import AppUserConflictError
from rag_eng.schemas import AdminSection


def _client() -> TestClient:
    return TestClient(create_app())


def _admin_section(section_id: str = "mit14-fall-001") -> AdminSection:
    return AdminSection(
        section_id=section_id,
        course_id="mit14",
        course_display_name="MIT 6.0014",
        display_name="MIT 6.0014 Section A",
        term="Fall 2026",
        is_active=True,
        professor_count=1,
        ta_count=0,
        student_count=1,
        memberships=[],
        created_at="2026-06-20T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        archived_at="",
    )


def test_admin_invite_student_route_requires_admin_token() -> None:
    client = _client()
    response = client.post(
        "/admin/sections/mit14-fall-001/students",
        json={"email": "student@example.edu", "display_name": "Student"},
    )
    assert response.status_code == 401


def test_admin_invite_student_route_invites_and_returns_section(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    captured: dict[str, object] = {}

    def fake_invite(section_id, payload):
        captured["section_id"] = section_id
        captured["payload"] = payload
        return _admin_section(section_id)

    monkeypatch.setattr("rag_eng.api.invite_admin_section_student", fake_invite)

    client = _client()
    response = client.post(
        "/admin/sections/mit14-fall-001/students",
        json={"email": "student@example.edu", "display_name": "Student"},
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert captured["section_id"] == "mit14-fall-001"
    assert captured["payload"].email == "student@example.edu"
    body = response.json()
    assert body["section_id"] == "mit14-fall-001"


def test_admin_invite_student_route_surfaces_conflict_errors(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")

    def _raise(section_id, payload):
        raise AppUserConflictError("User already linked to another Cognito identity.")

    monkeypatch.setattr("rag_eng.api.invite_admin_section_student", _raise)

    client = _client()
    response = client.post(
        "/admin/sections/mit14-fall-001/students",
        json={"email": "student@example.edu"},
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 409
