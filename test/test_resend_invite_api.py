from __future__ import annotations

from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.app_registry import MembershipAccessDeniedError
from rag_eng.auth.dependencies import require_authenticated_user
from rag_eng.auth.models import CurrentUser
from rag_eng.schemas import ProfessorSectionStudent


def _client() -> TestClient:
    return TestClient(create_app())


def _professor_user() -> CurrentUser:
    return CurrentUser(
        cognito_sub="prof-sub",
        email="prof@example.edu",
        primary_role="professor",
    )


def _roster() -> list[ProfessorSectionStudent]:
    return [
        ProfessorSectionStudent(
            user_id="student-1",
            cognito_sub="sub-student-1",
            email="corrected@example.edu",
            display_name="Student One",
            membership_status="invited",
            role_in_section="student",
            session_count=0,
            last_session_at="",
        )
    ]


def test_resend_invite_route_calls_resend_and_returns_roster(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    captured: dict[str, object] = {}

    def fake_resend(current_user, section_id, student_user_id, payload):
        captured["section_id"] = section_id
        captured["student_user_id"] = student_user_id
        captured["payload"] = payload
        return _roster()

    monkeypatch.setattr(
        "rag_eng.api.resend_professor_section_student_invite", fake_resend
    )

    try:
        response = client.post(
            "/professor/sections/mit14-fall-001/students/student-1/resend-invite",
            json={"email": "corrected@example.edu", "display_name": "Student One"},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["section_id"] == "mit14-fall-001"
    assert captured["student_user_id"] == "student-1"
    assert captured["payload"].email == "corrected@example.edu"
    body = response.json()
    assert body[0]["email"] == "corrected@example.edu"


def test_resend_invite_route_denies_non_member(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    def _raise(current_user, section_id, student_user_id, payload):
        raise MembershipAccessDeniedError("User is not assigned to this section.")

    monkeypatch.setattr(
        "rag_eng.api.resend_professor_section_student_invite", _raise
    )

    try:
        response = client.post(
            "/professor/sections/other-section/students/student-1/resend-invite",
            json={"email": "student@example.edu"},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 403
