from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

import pytest

import rag_eng.course_admin as course_admin
from rag_eng.course_admin import CourseConflictError, CourseNotFoundError
from rag_eng.schemas import (
    AdminCourseAliasCreate,
    AdminCourseCreate,
    AdminCourseUpdate,
)
NOW = datetime(2026, 6, 20, tzinfo=timezone.utc)


@dataclass
class _FakeState:
    courses: dict[str, dict[str, object]]
    aliases: dict[str, dict[str, object]]
    corpus_versions: list[dict[str, object]] | None = None


class _FakeCursor:
    def __init__(self, state: _FakeState):
        self.state = state
        self._rows: list[tuple[object, ...]] = []
        self.rowcount = 0

    @staticmethod
    def _normalize_sql(query: str) -> str:
        return " ".join(query.split())

    def execute(self, query: str, params: tuple[object, ...] | None = None) -> None:
        sql = self._normalize_sql(query)
        params = params or ()
        self.rowcount = 0

        if sql.startswith(
            "SELECT course_id, course_source, collection_name, display_name, is_active, created_at, updated_at FROM courses ORDER BY course_id"
        ):
            self._rows = [
                (
                    record["course_id"],
                    record["course_source"],
                    record["collection_name"],
                    record["display_name"],
                    record["is_active"],
                    record["created_at"],
                    record["updated_at"],
                )
                for record in sorted(
                    self.state.courses.values(),
                    key=lambda record: str(record["course_id"]),
                )
            ]
            return

        if sql.startswith(
            "SELECT alias, course_id, is_active FROM course_aliases ORDER BY alias"
        ):
            self._rows = [
                (
                    record["alias"],
                    record["course_id"],
                    record["is_active"],
                )
                for record in sorted(
                    self.state.aliases.values(),
                    key=lambda record: str(record["alias"]),
                )
            ]
            return

        if sql.startswith(
            "SELECT course_id, COUNT(*) FROM course_corpus_versions GROUP BY course_id"
        ):
            counts: dict[str, int] = {}
            for record in self.state.corpus_versions or []:
                course_id = str(record["course_id"])
                counts[course_id] = counts.get(course_id, 0) + 1
            self._rows = [(course_id, count) for course_id, count in sorted(counts.items())]
            return

        if sql.startswith(
            "SELECT course_id, course_source, collection_name, display_name, is_active, created_at, updated_at FROM courses WHERE course_id = %s"
        ):
            course_id = str(params[0])
            record = self.state.courses.get(course_id)
            self._rows = [
                (
                    record["course_id"],
                    record["course_source"],
                    record["collection_name"],
                    record["display_name"],
                    record["is_active"],
                    record["created_at"],
                    record["updated_at"],
                )
            ] if record is not None else []
            return

        if sql.startswith(
            "SELECT alias, course_id, is_active FROM course_aliases WHERE alias = %s"
        ):
            alias = str(params[0])
            record = self.state.aliases.get(alias)
            self._rows = [
                (
                    record["alias"],
                    record["course_id"],
                    record["is_active"],
                )
            ] if record is not None else []
            return

        if sql.startswith("INSERT INTO courses"):
            course_id, course_source, collection_name, display_name, is_active = params
            self.state.courses[str(course_id)] = {
                "course_id": str(course_id),
                "course_source": str(course_source),
                "collection_name": str(collection_name),
                "display_name": str(display_name),
                "is_active": bool(is_active),
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            self._rows = []
            return

        if sql.startswith("INSERT INTO course_aliases"):
            alias, course_id = params
            self.state.aliases[str(alias)] = {
                "alias": str(alias),
                "course_id": str(course_id),
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
            self.rowcount = 1
            self._rows = []
            return

        if sql.startswith("UPDATE courses SET"):
            course_id = str(params[-1])
            record = self.state.courses.get(course_id)
            if record is None:
                self._rows = []
                self.rowcount = 0
                return
            columns = [
                match
                for match in re.findall(r"(\w+)\s*=\s*%s", sql)
                if match != "updated_at"
            ]
            values = list(params[:-1])
            for column, value in zip(columns, values):
                record[column] = value
            record["updated_at"] = NOW
            self.rowcount = 1
            self._rows = []
            return

        if sql.startswith("UPDATE course_aliases SET is_active = TRUE"):
            alias = str(params[0])
            record = self.state.aliases.get(alias)
            if record is not None:
                record["is_active"] = True
                record["updated_at"] = NOW
                self.rowcount = 1
            self._rows = []
            return

        if sql.startswith("UPDATE course_aliases SET is_active = FALSE"):
            alias = str(params[0])
            record = self.state.aliases.get(alias)
            if record is not None:
                record["is_active"] = False
                record["updated_at"] = NOW
                self.rowcount = 1
            self._rows = []
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
    def __init__(self, state: _FakeState):
        self.state = state

    def cursor(self):
        return _FakeCursor(self.state)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _make_state(
    courses: dict[str, dict[str, object]] | None = None,
    aliases: dict[str, dict[str, object]] | None = None,
    corpus_versions: list[dict[str, object]] | None = None,
) -> _FakeState:
    return _FakeState(
        courses=courses or {},
        aliases=aliases or {},
        corpus_versions=corpus_versions,
    )


def _runtime() -> course_admin.CourseAdminRuntimeConfig:
    return course_admin.CourseAdminRuntimeConfig(
        database_url="postgresql://example",
        connect_timeout_seconds=5,
    )


def _patch_connection(monkeypatch: pytest.MonkeyPatch, state: _FakeState) -> None:
    monkeypatch.setattr(
        course_admin,
        "_connect_postgres",
        lambda database_url, connect_timeout_seconds: _FakeConnection(state),
    )


def test_list_admin_courses_returns_active_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _make_state(
        courses={
            "mit14": {
                "course_id": "mit14",
                "course_source": "mit14",
                "collection_name": "course_knowledge",
                "display_name": "MIT 6.0014",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
            "cs202": {
                "course_id": "cs202",
                "course_source": "mit14",
                "collection_name": "course_cs202",
                "display_name": "Advanced C++",
                "is_active": False,
                "created_at": NOW,
                "updated_at": NOW,
            },
        },
        aliases={
            "mit-14": {
                "alias": "mit-14",
                "course_id": "mit14",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
            "mit_14": {
                "alias": "mit_14",
                "course_id": "mit14",
                "is_active": False,
                "created_at": NOW,
                "updated_at": NOW,
            },
        },
        corpus_versions=[{"course_id": "mit14"}],
    )
    _patch_connection(monkeypatch, state)

    courses = course_admin.list_admin_courses(runtime=_runtime())

    assert [course.course_id for course in courses] == ["cs202", "mit14"]
    assert courses[1].aliases == ["mit-14"]
    assert courses[0].is_active is False
    assert courses[1].has_ingestion_history is True
    assert courses[0].has_ingestion_history is False


def test_list_admin_courses_marks_courses_with_corpus_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(
        courses={
            "mit14": {
                "course_id": "mit14",
                "course_source": "mit14",
                "collection_name": "course_knowledge",
                "display_name": "MIT 6.0014",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
        corpus_versions=[
            {"course_id": "mit14"},
            {"course_id": "mit14"},
        ],
    )
    _patch_connection(monkeypatch, state)

    courses = course_admin.list_admin_courses(runtime=_runtime())

    assert courses[0].has_ingestion_history is True


def test_create_admin_course_inserts_course_and_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    _patch_connection(monkeypatch, state)
    cleared = {"count": 0}
    monkeypatch.setattr(
        course_admin,
        "_clear_course_registry_cache",
        lambda: cleared.__setitem__("count", cleared["count"] + 1),
    )

    created = course_admin.create_admin_course(
        AdminCourseCreate(
            course_id="cs202",
            display_name="Advanced C++",
            course_source="mit14",
            collection_name="course_cs202",
            aliases=["advanced-cpp", "cs-202"],
        ),
        runtime=_runtime(),
    )

    assert created.course_id == "cs202"
    assert created.collection_name == "course_cs202"
    assert created.aliases == ["advanced-cpp", "cs-202"]
    assert state.courses["cs202"]["display_name"] == "Advanced C++"
    assert state.aliases["advanced-cpp"]["course_id"] == "cs202"
    assert cleared["count"] == 1


def test_create_admin_course_rejects_alias_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(
        courses={
            "mit14": {
                "course_id": "mit14",
                "course_source": "mit14",
                "collection_name": "course_knowledge",
                "display_name": "MIT 6.0014",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
        aliases={
            "advanced-cpp": {
                "alias": "advanced-cpp",
                "course_id": "mit14",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
    )
    _patch_connection(monkeypatch, state)

    with pytest.raises(CourseConflictError):
        course_admin.create_admin_course(
            AdminCourseCreate(
                course_id="cs202",
                display_name="Advanced C++",
                course_source="mit14",
                collection_name="course_cs202",
                aliases=["advanced-cpp"],
            ),
            runtime=_runtime(),
        )


def test_update_admin_course_updates_selected_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(
        courses={
            "cs202": {
                "course_id": "cs202",
                "course_source": "mit14",
                "collection_name": "course_old",
                "display_name": "Old Name",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        }
    )
    _patch_connection(monkeypatch, state)
    cleared = {"count": 0}
    monkeypatch.setattr(
        course_admin,
        "_clear_course_registry_cache",
        lambda: cleared.__setitem__("count", cleared["count"] + 1),
    )

    updated = course_admin.update_admin_course(
        "cs202",
        AdminCourseUpdate(
            display_name="New Name",
            collection_name="course_new",
            is_active=False,
        ),
        runtime=_runtime(),
    )

    assert updated.display_name == "New Name"
    assert updated.collection_name == "course_new"
    assert updated.is_active is False
    assert state.courses["cs202"]["display_name"] == "New Name"
    assert state.courses["cs202"]["collection_name"] == "course_new"
    assert cleared["count"] == 1


def test_add_admin_course_aliases_reactivates_inactive_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(
        courses={
            "cs202": {
                "course_id": "cs202",
                "course_source": "mit14",
                "collection_name": "course_cs202",
                "display_name": "Advanced C++",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
        aliases={
            "advanced-cpp": {
                "alias": "advanced-cpp",
                "course_id": "cs202",
                "is_active": False,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
    )
    _patch_connection(monkeypatch, state)

    updated = course_admin.add_admin_course_aliases(
        "cs202",
        AdminCourseAliasCreate(aliases=["advanced-cpp"]),
        runtime=_runtime(),
    )

    assert updated.aliases == ["advanced-cpp"]
    assert state.aliases["advanced-cpp"]["is_active"] is True


def test_deactivate_admin_course_alias_marks_alias_inactive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(
        courses={
            "cs202": {
                "course_id": "cs202",
                "course_source": "mit14",
                "collection_name": "course_cs202",
                "display_name": "Advanced C++",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
        aliases={
            "advanced-cpp": {
                "alias": "advanced-cpp",
                "course_id": "cs202",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
    )
    _patch_connection(monkeypatch, state)

    updated = course_admin.deactivate_admin_course_alias(
        "cs202",
        "advanced-cpp",
        runtime=_runtime(),
    )

    assert updated.aliases == []
    assert state.aliases["advanced-cpp"]["is_active"] is False


def test_deactivate_admin_course_alias_rejects_wrong_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(
        courses={
            "cs202": {
                "course_id": "cs202",
                "course_source": "mit14",
                "collection_name": "course_cs202",
                "display_name": "Advanced C++",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
            "other": {
                "course_id": "other",
                "course_source": "mit14",
                "collection_name": "course_other",
                "display_name": "Other",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            },
        },
        aliases={
            "advanced-cpp": {
                "alias": "advanced-cpp",
                "course_id": "other",
                "is_active": True,
                "created_at": NOW,
                "updated_at": NOW,
            }
        },
    )
    _patch_connection(monkeypatch, state)

    with pytest.raises(CourseNotFoundError):
        course_admin.deactivate_admin_course_alias(
            "cs202",
            "advanced-cpp",
            runtime=_runtime(),
        )
