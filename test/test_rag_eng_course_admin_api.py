from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.auth.models import CurrentUser
from rag_eng.course_admin import CourseConflictError, CourseNotFoundError
from rag_eng.schemas import AdminCourse


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def _course(course_id: str = "cs202") -> AdminCourse:
    return AdminCourse(
        course_id=course_id,
        display_name="Advanced C++",
        course_source="mit14",
        collection_name="course_cs202",
        is_active=True,
        aliases=["advanced-cpp"],
        created_at="2026-06-20T00:00:00+00:00",
        updated_at="2026-06-20T00:00:00+00:00",
    )


def test_admin_courses_require_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")

    response = client.get("/admin/courses")

    assert response.status_code == 401


def test_admin_list_courses_allows_authorized_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.list_admin_courses",
        lambda: [_course()],
    )

    response = client.get(
        "/admin/courses",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 200
    assert response.json()[0]["course_id"] == "cs202"


def test_admin_list_courses_allows_admin_bearer_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.list_admin_courses",
        lambda: [_course()],
    )

    def _admin(_token: str, _settings) -> CurrentUser:
        return CurrentUser(
            cognito_sub="admin-sub-1",
            email="admin@test.codingrabbit.dev",
            groups=["Admins"],
            primary_role="admin",
        )

    monkeypatch.setattr("rag_eng.api.verify_cognito_access_token", _admin)

    response = client.get(
        "/admin/courses",
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 200
    assert response.json()[0]["course_id"] == "cs202"


def test_admin_get_course_returns_404_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.get_admin_course",
        lambda course_id: (_ for _ in ()).throw(CourseNotFoundError(course_id)),
    )

    response = client.get(
        "/admin/courses/cs202",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert response.status_code == 404


def test_admin_create_course_maps_conflict_to_409(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.create_admin_course",
        lambda payload: (_ for _ in ()).throw(CourseConflictError("duplicate")),
    )

    response = client.post(
        "/admin/courses",
        headers={"X-Admin-Token": "expected-token"},
        json={
            "course_id": "cs202",
            "display_name": "Advanced C++",
            "course_source": "mit14",
            "collection_name": "course_cs202",
            "aliases": ["advanced-cpp"],
        },
    )

    assert response.status_code == 409


def test_admin_update_course_allows_authorized_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.update_admin_course",
        lambda course_id, payload: _course(course_id),
    )

    response = client.patch(
        "/admin/courses/cs202",
        headers={"X-Admin-Token": "expected-token"},
        json={
            "display_name": "Updated Name",
            "collection_name": "course_updated",
            "is_active": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["course_id"] == "cs202"


def test_admin_alias_routes_allow_authorized_request(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "expected-token")
    monkeypatch.setattr(
        "rag_eng.api.add_admin_course_aliases",
        lambda course_id, payload: _course(course_id),
    )
    monkeypatch.setattr(
        "rag_eng.api.deactivate_admin_course_alias",
        lambda course_id, alias: _course(course_id),
    )

    add_response = client.post(
        "/admin/courses/cs202/aliases",
        headers={"X-Admin-Token": "expected-token"},
        json={"aliases": ["cs-202"]},
    )
    delete_response = client.delete(
        "/admin/courses/cs202/aliases/cs-202",
        headers={"X-Admin-Token": "expected-token"},
    )

    assert add_response.status_code == 200
    assert delete_response.status_code == 200
