from __future__ import annotations

from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.app_registry import MembershipAccessDeniedError
from rag_eng.auth.dependencies import require_authenticated_user
from rag_eng.auth.models import CurrentUser
from rag_eng.schemas import (
    EvaluationRunSummary,
    ProfessorSectionStudent,
    ProfessorSectionSummary,
    TaEffectivenessRosterEntry,
    TaEffectivenessSectionRoster,
    TaEffectivenessSessionScore,
    TaEffectivenessSessionTurns,
    TaEffectivenessStudentDetail,
    TaEffectivenessTurnScore,
)


def _client() -> TestClient:
    return TestClient(create_app())


def _professor_user() -> CurrentUser:
    return CurrentUser(
        cognito_sub="prof-sub",
        email="prof@example.edu",
        primary_role="professor",
    )


def _section_summary() -> ProfessorSectionSummary:
    return ProfessorSectionSummary(
        section_id="mit14-fall-001",
        course_id="mit14",
        course_display_name="MIT 6.0014",
        display_name="Section A",
        term="Fall 2026",
        is_active=True,
        professor_count=1,
        ta_count=1,
        student_count=2,
        created_at="2026-07-08T00:00:00Z",
        updated_at="2026-07-08T00:00:00Z",
    )


def _student() -> ProfessorSectionStudent:
    return ProfessorSectionStudent(
        user_id="student-1",
        cognito_sub="student-sub",
        email="student@example.edu",
        display_name="Student",
        membership_status="active",
        role_in_section="student",
        session_count=3,
        last_session_at="2026-06-20T00:00:00+00:00",
    )


def _evaluation_summary(run_id: str = "run-123") -> EvaluationRunSummary:
    return EvaluationRunSummary(
        evaluation_run_id=run_id,
        run_label="TA effectiveness refresh",
        notes="",
        requested_by_user_id="user-1",
        requested_by_cognito_sub="prof-sub",
        requested_by_email="prof@example.edu",
        judge_provider="bedrock",
        judge_model="anthropic.claude-haiku-4-5",
        input_dataset_s3_uri="s3://codingrabbit-data-dev/evaluation/offline/run-123/input/turn_snapshots.jsonl",
        results_s3_prefix="s3://codingrabbit-data-dev/evaluation/offline/run-123/results",
        course_id="mit14",
        section_id="mit14-fall-001",
        status="queued",
        message="Launched.",
    )


def test_ta_effectiveness_roster_route_returns_live_data(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    roster = TaEffectivenessSectionRoster(
        section=_section_summary(),
        entries=[
            TaEffectivenessRosterEntry(
                student=_student(),
                session_count=3,
                avg_session_effectiveness=0.4,
                avg_pedagogical_impact=0.5,
                drift_rate=0.33,
                has_code_leak=False,
                last_scored_at="2026-07-10T00:00:00+00:00",
            )
        ],
        generated_at="2026-07-10T00:00:00+00:00",
    )
    monkeypatch.setattr(
        "rag_eng.api.get_ta_effectiveness_section_roster",
        lambda current_user, section_id: roster,
    )

    try:
        response = client.get("/professor/sections/mit14-fall-001/ta-effectiveness")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["section"]["section_id"] == "mit14-fall-001"
    assert body["entries"][0]["student"]["email"] == "student@example.edu"
    assert body["entries"][0]["avg_session_effectiveness"] == 0.4


def test_ta_effectiveness_roster_denies_non_member(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    def _raise(current_user, section_id):
        raise MembershipAccessDeniedError("User is not assigned to this section.")

    monkeypatch.setattr("rag_eng.api.get_ta_effectiveness_section_roster", _raise)

    try:
        response = client.get("/professor/sections/other-section/ta-effectiveness")
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 403


def test_ta_effectiveness_student_detail_route_returns_live_data(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    detail = TaEffectivenessStudentDetail(
        section=_section_summary(),
        student=_student(),
        sessions=[
            TaEffectivenessSessionScore(
                session_id="session-1",
                evaluation_run_id="run-1",
                mode="homework",
                session_effectiveness_score=0.6,
                session_passed=False,
                pedagogical_impact_score=0.5,
                turn_count=4,
                drift_flag=True,
                scored_at="2026-07-10T00:00:00+00:00",
            )
        ],
    )
    captured: dict[str, object] = {}

    def fake_get_detail(current_user, section_id, student_user_id):
        captured["section_id"] = section_id
        captured["student_user_id"] = student_user_id
        return detail

    monkeypatch.setattr(
        "rag_eng.api.get_ta_effectiveness_student_detail", fake_get_detail
    )

    try:
        response = client.get(
            "/professor/sections/mit14-fall-001/students/student-1/ta-effectiveness"
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured["section_id"] == "mit14-fall-001"
    assert captured["student_user_id"] == "student-1"
    body = response.json()
    assert body["sessions"][0]["session_id"] == "session-1"
    assert body["sessions"][0]["drift_flag"] is True


def test_ta_effectiveness_session_turns_route_passes_query_params(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    turns = TaEffectivenessSessionTurns(
        session_id="session-1",
        turns=[
            TaEffectivenessTurnScore(
                turn_id="turn-1",
                turn_index=0,
                mode="homework",
                pedagogical_turn_score=0.75,
                turn_passed=True,
            )
        ],
    )
    captured: dict[str, object] = {}

    def fake_get_turns(current_user, section_id, session_id, evaluation_run_id):
        captured["section_id"] = section_id
        captured["session_id"] = session_id
        captured["evaluation_run_id"] = evaluation_run_id
        return turns

    monkeypatch.setattr(
        "rag_eng.api.get_ta_effectiveness_session_turns", fake_get_turns
    )

    try:
        response = client.get(
            "/professor/sections/mit14-fall-001/ta-effectiveness/sessions/session-1/turns"
            "?evaluation_run_id=run-1"
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    assert captured == {
        "section_id": "mit14-fall-001",
        "session_id": "session-1",
        "evaluation_run_id": "run-1",
    }
    assert response.json()["turns"][0]["turn_id"] == "turn-1"


def test_ta_effectiveness_refresh_forces_section_id_from_path_not_body(
    monkeypatch,
) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    monkeypatch.setattr(
        "rag_eng.api.require_section_membership",
        lambda current_user, section_id, allowed_roles=None: None,
    )
    monkeypatch.setattr(
        "rag_eng.api.get_evaluation_config_payload",
        lambda: {
            "default_judge_provider": "bedrock",
            "default_judge_model": "anthropic.claude-haiku-4-5",
        },
    )
    captured: dict[str, object] = {}

    def fake_launch(request, current_user=None):
        captured["request"] = request
        return _evaluation_summary()

    monkeypatch.setattr("rag_eng.api.launch_evaluation_run", fake_launch)

    try:
        response = client.post(
            "/professor/sections/mit14-fall-001/ta-effectiveness/refresh",
            # A crafted body cannot smuggle a different section_id — the
            # request schema has no section_id field, and even if it did,
            # the handler must force it from the path param.
            json={"section_id": "someone-elses-section", "run_label": "manual"},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    launched_request = captured["request"]
    assert launched_request.export_scope.section_id == "mit14-fall-001"
    assert launched_request.run_label == "manual"


def test_ta_effectiveness_refresh_passes_through_explicit_date_range(
    monkeypatch,
) -> None:
    """The professor UI pre-fills a date range (defaulting to today) and lets
    the professor widen it — e.g. after a run against a section with no
    activity today returned zero rows. The handler must forward whatever
    range the professor picked unmodified, not silently override it."""
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    monkeypatch.setattr(
        "rag_eng.api.require_section_membership",
        lambda current_user, section_id, allowed_roles=None: None,
    )
    monkeypatch.setattr(
        "rag_eng.api.get_evaluation_config_payload",
        lambda: {
            "default_judge_provider": "bedrock",
            "default_judge_model": "anthropic.claude-haiku-4-5",
        },
    )
    captured: dict[str, object] = {}

    def fake_launch(request, current_user=None):
        captured["request"] = request
        return _evaluation_summary()

    monkeypatch.setattr("rag_eng.api.launch_evaluation_run", fake_launch)

    try:
        response = client.post(
            "/professor/sections/mit14-fall-001/ta-effectiveness/refresh",
            json={"start_date": "2026-06-01", "end_date": "2026-07-16"},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 200
    launched_request = captured["request"]
    assert launched_request.export_scope.start_date == "2026-06-01"
    assert launched_request.export_scope.end_date == "2026-07-16"


def test_ta_effectiveness_refresh_denies_non_member(monkeypatch) -> None:
    client = _client()
    client.app.dependency_overrides[require_authenticated_user] = _professor_user

    def _raise(current_user, section_id, allowed_roles=None):
        raise MembershipAccessDeniedError("User is not assigned to this section.")

    monkeypatch.setattr("rag_eng.api.require_section_membership", _raise)
    launch_called = {"called": False}
    monkeypatch.setattr(
        "rag_eng.api.launch_evaluation_run",
        lambda request, current_user=None: launch_called.__setitem__("called", True),
    )

    try:
        response = client.post(
            "/professor/sections/other-section/ta-effectiveness/refresh",
            json={},
        )
    finally:
        client.app.dependency_overrides.clear()

    assert response.status_code == 403
    assert launch_called["called"] is False
