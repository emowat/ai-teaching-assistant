from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
import uuid

import pytest

import rag_eng.app_registry as app_registry
from rag_eng.auth.models import CurrentUser
from rag_eng.schemas import (
    AdminSectionCreate,
    AdminSectionMembershipCreate,
    AdminSectionMembershipUpdate,
    AdminSectionUpdate,
    AdminUserCreate,
)


NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


@dataclass
class _State:
    courses: dict[str, dict[str, object]]
    users: dict[str, dict[str, object]]
    sections: dict[str, dict[str, object]]
    memberships: dict[tuple[str, str], dict[str, object]]
    tutor_sessions: list[dict[str, object]]


class _FakeCursor:
    def __init__(self, state: _State):
        self.state = state
        self._rows: list[tuple[object, ...]] = []
        self.rowcount = 0

    @staticmethod
    def _normalize_sql(query: str) -> str:
        return " ".join(query.split())

    def _user_row(self, record: dict[str, object]) -> tuple[object, ...]:
        return (
            record["user_id"],
            record.get("cognito_sub"),
            record["email"],
            record.get("display_name", ""),
            record["primary_role"],
            record["status"],
            record["created_at"],
            record["updated_at"],
        )

    def _section_row(self, record: dict[str, object]) -> tuple[object, ...]:
        course = self.state.courses[str(record["course_id"])]
        return (
            record["section_id"],
            record["course_id"],
            course["display_name"],
            record["display_name"],
            record.get("term", ""),
            record.get("is_active", True),
            record["created_at"],
            record["updated_at"],
        )

    def _membership_row_for_user(
        self,
        membership: dict[str, object],
    ) -> tuple[object, ...]:
        section = self.state.sections[str(membership["section_id"])]
        user = self.state.users[str(membership["user_id"])]
        course = self.state.courses[str(section["course_id"])]
        return (
            user["user_id"],
            section["section_id"],
            section["display_name"],
            section["course_id"],
            course["display_name"],
            membership["role_in_section"],
            membership["status"],
            membership["created_at"],
            membership["updated_at"],
        )

    def _membership_row_for_section(
        self,
        membership: dict[str, object],
    ) -> tuple[object, ...]:
        section = self.state.sections[str(membership["section_id"])]
        user = self.state.users[str(membership["user_id"])]
        course = self.state.courses[str(section["course_id"])]
        return (
            section["section_id"],
            user["user_id"],
            user.get("cognito_sub"),
            user["email"],
            user.get("display_name", ""),
            membership["role_in_section"],
            membership["status"],
            section["display_name"],
            section["course_id"],
            course["display_name"],
            membership["created_at"],
            membership["updated_at"],
        )

    def _student_row(self, membership: dict[str, object]) -> tuple[object, ...]:
        section_id = str(membership["section_id"])
        user = self.state.users[str(membership["user_id"])]
        sessions = [
            session
            for session in self.state.tutor_sessions
            if str(session.get("section_id", "")) == section_id
            and str(session.get("user_sub", "")) == str(user.get("cognito_sub", ""))
        ]
        last_session_at = None
        if sessions:
            last_session_at = max(session["last_seen_at"] for session in sessions)
        return (
            user["user_id"],
            user.get("cognito_sub"),
            user["email"],
            user.get("display_name", ""),
            membership["status"],
            membership["role_in_section"],
            len(sessions),
            last_session_at,
        )

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        sql = self._normalize_sql(query)
        params = params or ()
        self.rowcount = 0
        self._rows = []

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users WHERE cognito_sub = %s"
        ):
            cognito_sub = str(params[0])
            for record in self.state.users.values():
                if str(record.get("cognito_sub", "")) == cognito_sub:
                    self._rows = [self._user_row(record)]
                    return
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users WHERE lower(email) = lower(%s)"
        ):
            email = str(params[0]).casefold()
            for record in self.state.users.values():
                if str(record["email"]).casefold() == email:
                    self._rows = [self._user_row(record)]
                    return
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users WHERE user_id = %s"
        ):
            user_id = str(params[0])
            record = self.state.users.get(user_id)
            if record is not None:
                self._rows = [self._user_row(record)]
            return

        if sql.startswith(
            "SELECT user_id, cognito_sub, email, display_name, primary_role, status, created_at, updated_at FROM users ORDER BY email ASC"
        ):
            self._rows = [
                self._user_row(record)
                for record in sorted(
                    self.state.users.values(),
                    key=lambda row: str(row["email"]).casefold(),
                )
            ]
            return

        if sql.startswith("INSERT INTO users"):
            user_id = str(uuid.uuid4())
            email, display_name, primary_role, status = params
            self.state.users[user_id] = {
                "user_id": user_id,
                "cognito_sub": None,
                "email": str(email),
                "display_name": str(display_name),
                "primary_role": str(primary_role),
                "status": str(status),
                "created_at": NOW,
                "updated_at": NOW,
            }
            self._rows = [(user_id,)]
            self.rowcount = 1
            return

        if sql.startswith(
            "UPDATE users SET cognito_sub = %s, status = CASE WHEN status = 'disabled' THEN status ELSE 'active' END, updated_at = now() WHERE user_id = %s"
        ):
            cognito_sub, user_id = params
            record = self.state.users.get(str(user_id))
            if record is not None:
                record["cognito_sub"] = str(cognito_sub)
                if record["status"] != "disabled":
                    record["status"] = "active"
                record["updated_at"] = NOW
                self.rowcount = 1
            return

        if sql.startswith("UPDATE users SET status = 'active', updated_at = now() WHERE user_id = %s"):
            user_id = str(params[0])
            record = self.state.users.get(user_id)
            if record is not None:
                record["status"] = "active"
                record["updated_at"] = NOW
                self.rowcount = 1
            return

        if sql.startswith("UPDATE users SET"):
            user_id = str(params[-1])
            record = self.state.users.get(user_id)
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            for column, value in zip(columns, params[:-1]):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id ORDER BY sm.section_id ASC, u.email ASC"
        ):
            self._rows = [
                self._membership_row_for_section(self.state.memberships[key])
                for key in sorted(self.state.memberships)
            ]
            return

        if sql.startswith(
            "SELECT u.user_id, s.section_id, s.display_name, s.course_id, c.display_name, sm.role_in_section, sm.status, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id ORDER BY u.email ASC, s.section_id ASC"
        ):
            rows = [
                self._membership_row_for_user(membership)
                for membership in self.state.memberships.values()
            ]
            self._rows = sorted(rows, key=lambda row: (str(row[2]).casefold(), str(row[1])))
            return

        if sql.startswith(
            "SELECT u.user_id, s.section_id, s.display_name, s.course_id, c.display_name, sm.role_in_section, sm.status, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE u.user_id = %s ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._membership_row_for_user(membership)
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
            ]
            self._rows = sorted(rows, key=lambda row: str(row[1]))
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE sm.section_id IN ( SELECT s2.section_id FROM sections AS s2 WHERE s2.is_active = TRUE AND EXISTS ( SELECT 1 FROM section_memberships AS sm2 WHERE sm2.section_id = s2.section_id AND sm2.user_id = %s AND sm2.status = 'active' AND sm2.role_in_section IN ('professor', 'ta') ) ) ORDER BY sm.section_id ASC, u.email ASC"
        ):
            user_id = str(params[0])
            accessible_section_ids = {
                str(membership["section_id"])
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["status"]) == "active"
                and str(membership["role_in_section"]) in {"professor", "ta"}
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
            }
            rows = [
                self._membership_row_for_section(membership)
                for membership in self.state.memberships.values()
                if str(membership["section_id"]) in accessible_section_ids
            ]
            self._rows = sorted(rows, key=lambda row: (str(row[1]), str(row[3]).casefold()))
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE u.user_id = %s ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            rows = [
                self._membership_row_for_section(record)
                for record in self.state.memberships.values()
                if str(record["user_id"]) == user_id
            ]
            self._rows = sorted(rows, key=lambda row: str(row[1]))
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id ORDER BY s.section_id ASC"
        ):
            self._rows = [
                self._section_row(record)
                for record in sorted(
                    self.state.sections.values(),
                    key=lambda row: str(row["section_id"]),
                )
            ]
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id WHERE EXISTS ( SELECT 1 FROM section_memberships AS sm WHERE sm.section_id = s.section_id AND sm.user_id = %s AND sm.status = 'active' AND sm.role_in_section IN ('professor', 'ta') ) AND s.is_active = TRUE ORDER BY s.section_id ASC"
        ):
            user_id = str(params[0])
            section_ids = {
                str(membership["section_id"])
                for membership in self.state.memberships.values()
                if str(membership["user_id"]) == user_id
                and str(membership["status"]) == "active"
                and str(membership["role_in_section"]) in {"professor", "ta"}
                and bool(self.state.sections[str(membership["section_id"])]["is_active"])
            }
            self._rows = [
                self._section_row(self.state.sections[section_id])
                for section_id in sorted(section_ids)
            ]
            return

        if sql.startswith(
            "SELECT u.user_id, u.cognito_sub, u.email, u.display_name, sm.status, sm.role_in_section, COALESCE(stats.session_count, 0) AS session_count, stats.last_session_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id LEFT JOIN ( SELECT user_sub, COUNT(*) AS session_count, MAX(last_seen_at) AS last_session_at FROM tutor_sessions WHERE section_id = %s GROUP BY user_sub ) AS stats ON stats.user_sub = u.cognito_sub WHERE sm.section_id = %s AND sm.role_in_section = 'student' AND sm.status = 'active' ORDER BY u.display_name ASC, u.email ASC"
        ):
            section_id = str(params[0])
            rows = [
                self._student_row(membership)
                for membership in self.state.memberships.values()
                if str(membership["section_id"]) == section_id
                and str(membership["role_in_section"]) == "student"
                and str(membership["status"]) == "active"
            ]
            self._rows = rows
            return

        if sql.startswith("SELECT course_id FROM courses WHERE course_id = %s"):
            course_id = str(params[0])
            if course_id in self.state.courses:
                self._rows = [(course_id,)]
            return

        if sql.startswith(
            "SELECT s.section_id, s.course_id, c.display_name, s.display_name, s.term, s.is_active, s.created_at, s.updated_at FROM sections AS s INNER JOIN courses AS c ON c.course_id = s.course_id WHERE s.section_id = %s"
        ):
            section_id = str(params[0])
            record = self.state.sections.get(section_id)
            if record is not None:
                self._rows = [self._section_row(record)]
            return

        if sql.startswith(
            "SELECT sm.section_id, u.user_id, u.cognito_sub, u.email, u.display_name, sm.role_in_section, sm.status, s.display_name, s.course_id, c.display_name, sm.created_at, sm.updated_at FROM section_memberships AS sm INNER JOIN users AS u ON u.user_id = sm.user_id INNER JOIN sections AS s ON s.section_id = sm.section_id INNER JOIN courses AS c ON c.course_id = s.course_id WHERE sm.section_id = %s ORDER BY u.email ASC, sm.role_in_section ASC"
        ):
            section_id = str(params[0])
            rows = [
                self._membership_row_for_section(membership)
                for membership in self.state.memberships.values()
                if str(membership["section_id"]) == section_id
            ]
            self._rows = sorted(rows, key=lambda row: (str(row[3]).casefold(), str(row[5])))
            return

        if sql.startswith("INSERT INTO sections"):
            section_id, course_id, display_name, term, is_active = params
            self.state.sections[str(section_id)] = {
                "section_id": str(section_id),
                "course_id": str(course_id),
                "display_name": str(display_name),
                "term": str(term),
                "is_active": bool(is_active),
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            return

        if sql.startswith("UPDATE sections SET"):
            section_id = str(params[-1])
            record = self.state.sections.get(section_id)
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            for column, value in zip(columns, params[:-1]):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith("INSERT INTO section_memberships"):
            section_id, user_id, role_in_section, status = params
            self.state.memberships[(str(section_id), str(user_id))] = {
                "section_id": str(section_id),
                "user_id": str(user_id),
                "role_in_section": str(role_in_section),
                "status": str(status),
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            return

        if sql.startswith("UPDATE section_memberships SET"):
            section_id = str(params[-2])
            user_id = str(params[-1])
            record = self.state.memberships.get((section_id, user_id))
            if record is None:
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            for column, value in zip(columns, params[:-2]):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            return

        if sql.startswith("SELECT section_id FROM section_memberships WHERE section_id = %s AND user_id = %s"):
            section_id, user_id = map(str, params)
            if (section_id, user_id) in self.state.memberships:
                self._rows = [(section_id,)]
            return

        if sql.startswith("SELECT role_in_section, status FROM section_memberships WHERE section_id = %s AND user_id = %s"):
            section_id, user_id = map(str, params)
            record = self.state.memberships.get((section_id, user_id))
            if record is not None:
                self._rows = [(record["role_in_section"], record["status"])]
            return

        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, state: _State):
        self.state = state

    def cursor(self):
        return _FakeCursor(self.state)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _state() -> _State:
    return _State(
        courses={
            "mit14": {
                "course_id": "mit14",
                "display_name": "MIT 6.0014",
            }
        },
        users={},
        sections={},
        memberships={},
        tutor_sessions=[],
    )


def _runtime() -> app_registry.AppRegistryRuntimeConfig:
    return app_registry.AppRegistryRuntimeConfig(
        database_url="postgresql://example",
        connect_timeout_seconds=5,
    )


def _patch_connection(monkeypatch: pytest.MonkeyPatch, state: _State) -> None:
    monkeypatch.setattr(
        app_registry,
        "_connect_postgres",
        lambda database_url, connect_timeout_seconds: _FakeConnection(state),
    )


def _user(
    *,
    user_id: str,
    email: str,
    display_name: str,
    primary_role: str,
    status: str,
    cognito_sub: str | None = None,
) -> dict[str, object]:
    return {
        "user_id": user_id,
        "cognito_sub": cognito_sub,
        "email": email,
        "display_name": display_name,
        "primary_role": primary_role,
        "status": status,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _section(
    *,
    section_id: str,
    course_id: str = "mit14",
    display_name: str,
    term: str = "Fall 2026",
    is_active: bool = True,
) -> dict[str, object]:
    return {
        "section_id": section_id,
        "course_id": course_id,
        "display_name": display_name,
        "term": term,
        "is_active": is_active,
        "created_at": NOW,
        "updated_at": NOW,
    }


def _membership(
    *,
    section_id: str,
    user_id: str,
    role_in_section: str,
    status: str = "active",
) -> dict[str, object]:
    return {
        "section_id": section_id,
        "user_id": user_id,
        "role_in_section": role_in_section,
        "status": status,
        "created_at": NOW,
        "updated_at": NOW,
    }


def test_resolve_application_user_claims_by_cognito_sub_without_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-1"] = _user(
        user_id="user-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-1",
    )
    _patch_connection(monkeypatch, state)

    resolved = app_registry.resolve_application_user(
        CurrentUser(
            cognito_sub="sub-1",
            email=None,
            primary_role="professor",
        ),
        runtime=_runtime(),
    )

    assert resolved["user_id"] == "user-1"
    assert resolved["email"] == "prof@example.edu"


def test_resolve_application_user_claims_invited_user_by_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-2"] = _user(
        user_id="user-2",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="invited",
    )
    _patch_connection(monkeypatch, state)

    resolved = app_registry.resolve_application_user(
        CurrentUser(
            cognito_sub="sub-2",
            email="student@example.edu",
            primary_role="student",
        ),
        runtime=_runtime(),
    )

    assert resolved["user_id"] == "user-2"
    assert resolved["cognito_sub"] == "sub-2"
    assert state.users["user-2"]["status"] == "active"


def test_resolve_application_user_rejects_disabled_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-3"] = _user(
        user_id="user-3",
        email="disabled@example.edu",
        display_name="Disabled",
        primary_role="student",
        status="disabled",
        cognito_sub="sub-3",
    )
    _patch_connection(monkeypatch, state)

    with pytest.raises(app_registry.AppUserDisabledError):
        app_registry.resolve_application_user(
            CurrentUser(
                cognito_sub="sub-3",
                email="disabled@example.edu",
                primary_role="student",
            ),
            runtime=_runtime(),
        )


def test_admin_user_and_section_crud_with_memberships(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["user-1"] = _user(
        user_id="user-1",
        email="existing@example.edu",
        display_name="Existing User",
        primary_role="student",
        status="active",
        cognito_sub="sub-existing",
    )
    _patch_connection(monkeypatch, state)

    created_user = app_registry.create_admin_user(
        AdminUserCreate(
            email="invite@example.edu",
            display_name="Invite User",
            primary_role="professor",
        ),
        runtime=_runtime(),
    )
    created_section = app_registry.create_admin_section(
        AdminSectionCreate(
            section_id="mit14-fall-001",
            course_id="mit14",
            display_name="MIT 6.0014 Section A",
            term="Fall 2026",
        ),
        runtime=_runtime(),
    )
    updated_section = app_registry.update_admin_section(
        "mit14-fall-001",
        AdminSectionUpdate(display_name="MIT 6.0014 Section A+", is_active=False),
        runtime=_runtime(),
    )
    membership_section = app_registry.create_section_membership(
        "mit14-fall-001",
        AdminSectionMembershipCreate(
            user_id=created_user.user_id,
            role_in_section="professor",
        ),
        runtime=_runtime(),
    )
    updated_membership = app_registry.update_section_membership(
        "mit14-fall-001",
        created_user.user_id,
        AdminSectionMembershipUpdate(status="disabled"),
        runtime=_runtime(),
    )

    users = app_registry.list_admin_users(runtime=_runtime())
    sections = app_registry.list_admin_sections(runtime=_runtime())

    assert created_user.email == "invite@example.edu"
    assert created_section.section_id == "mit14-fall-001"
    assert updated_section.is_active is False
    assert membership_section.section_id == "mit14-fall-001"
    assert updated_membership.memberships[0].status == "disabled"
    assert users[0].email == "existing@example.edu"
    assert users[1].section_memberships[0].section_id == "mit14-fall-001"
    assert sections[0].memberships[0].section_id == "mit14-fall-001"


def test_professor_views_return_active_sections_and_rosters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state()
    state.users["prof-1"] = _user(
        user_id="prof-1",
        email="prof@example.edu",
        display_name="Prof",
        primary_role="professor",
        status="active",
        cognito_sub="sub-prof",
    )
    state.users["student-1"] = _user(
        user_id="student-1",
        email="student@example.edu",
        display_name="Student",
        primary_role="student",
        status="active",
        cognito_sub="sub-student",
    )
    state.sections["mit14-fall-001"] = _section(
        section_id="mit14-fall-001",
        display_name="MIT 6.0014 Section A",
    )
    state.sections["mit14-fall-002"] = _section(
        section_id="mit14-fall-002",
        display_name="Inactive Section",
        is_active=False,
    )
    state.memberships[("mit14-fall-001", "prof-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.memberships[("mit14-fall-001", "student-1")] = _membership(
        section_id="mit14-fall-001",
        user_id="student-1",
        role_in_section="student",
    )
    state.memberships[("mit14-fall-002", "prof-1")] = _membership(
        section_id="mit14-fall-002",
        user_id="prof-1",
        role_in_section="professor",
    )
    state.tutor_sessions.append(
        {
            "session_id": "sess-1",
            "user_sub": "sub-student",
            "section_id": "mit14-fall-001",
            "last_seen_at": NOW,
        }
    )
    _patch_connection(monkeypatch, state)

    sections = app_registry.list_professor_sections(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        runtime=_runtime(),
    )
    students = app_registry.list_professor_section_students(
        CurrentUser(
            cognito_sub="sub-prof",
            email="prof@example.edu",
            primary_role="professor",
        ),
        "mit14-fall-001",
        runtime=_runtime(),
    )

    assert [section.section_id for section in sections] == ["mit14-fall-001"]
    assert students[0].email == "student@example.edu"
    assert students[0].session_count == 1
