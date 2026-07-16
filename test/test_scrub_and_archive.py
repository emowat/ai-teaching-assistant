from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

import rag_eng.app_registry as app_registry
from rag_eng.app_registry import (
    SectionNotFoundError,
    _redact_snapshot_for_archive,
    archive_section_data,
    scrub_user_data,
)


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self._connection = connection
        self._rows: list[tuple[Any, ...]] = []
        self.rowcount = 0

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        normalized = " ".join(sql.split())
        self._connection.executed.append((normalized, params))
        if normalized.startswith("SELECT cognito_sub FROM users"):
            self._rows = (
                [self._connection.cognito_sub_row]
                if self._connection.cognito_sub_row
                else []
            )
        elif normalized.startswith(
            "SELECT session_id, turn_index, snapshot FROM tutor_turn_snapshots"
        ):
            self._rows = list(self._connection.snapshot_rows)
        elif normalized.startswith("UPDATE sections"):
            self.rowcount = 1 if self._connection.section_exists else 0
        else:
            self._rows = []

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConnection:
    def __init__(
        self,
        *,
        cognito_sub_row: tuple[Any, ...] | None = None,
        snapshot_rows: list[tuple[Any, ...]] | None = None,
        section_exists: bool = True,
    ) -> None:
        self.executed: list[tuple[str, Any]] = []
        self.cognito_sub_row = cognito_sub_row
        self.snapshot_rows = snapshot_rows or []
        self.section_exists = section_exists
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _runtime() -> Any:
    return SimpleNamespace(database_url="postgresql://example", connect_timeout_seconds=5)


def _sqls(connection: _FakeConnection, contains: str) -> list[tuple[str, Any]]:
    return [(sql, params) for sql, params in connection.executed if contains in sql]


def _patch_connection(monkeypatch: pytest.MonkeyPatch, connection: _FakeConnection) -> None:
    monkeypatch.setattr(
        app_registry,
        "_connect_postgres",
        lambda database_url, connect_timeout_seconds: connection,
    )


# --- scrub_user_data (Case 1: full deletion) --------------------------------


def test_scrub_user_data_deletes_tutor_sessions_and_dependent_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(cognito_sub_row=("sub-123",))
    _patch_connection(monkeypatch, connection)

    scrub_user_data("user-1", runtime=_runtime())

    delete_sessions = _sqls(connection, "DELETE FROM tutor_sessions")
    assert len(delete_sessions) == 1
    _, params = delete_sessions[0]
    assert params == ("user-1", "sub-123", "sub-123")

    assert len(_sqls(connection, "DELETE FROM reported_issues")) == 1
    assert len(_sqls(connection, "DELETE FROM section_memberships")) == 1
    assert len(_sqls(connection, "UPDATE users")) == 1
    assert len(_sqls(connection, "UPDATE data_deletion_requests")) == 1
    assert connection.committed is True

    # cognito_sub is looked up before the anonymizing UPDATE users runs, so
    # the legacy user_sub match in the DELETE FROM tutor_sessions clause
    # above still has the real value to match against.
    select_index = next(
        i for i, (sql, _) in enumerate(connection.executed) if "SELECT cognito_sub" in sql
    )
    update_users_index = next(
        i for i, (sql, _) in enumerate(connection.executed) if sql.startswith("UPDATE users")
    )
    assert select_index < update_users_index


def test_scrub_user_data_handles_user_with_no_cognito_sub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(cognito_sub_row=None)
    _patch_connection(monkeypatch, connection)

    scrub_user_data("user-2", runtime=_runtime())

    _, params = _sqls(connection, "DELETE FROM tutor_sessions")[0]
    assert params == ("user-2", None, None)


def test_scrub_user_data_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeConnection(cognito_sub_row=None)
    _patch_connection(monkeypatch, connection)

    scrub_user_data("user-3", runtime=_runtime())
    scrub_user_data("user-3", runtime=_runtime())

    # No exceptions, and every core statement ran twice — every statement in
    # scrub_user_data is a plain DELETE/UPDATE with no existence checks, so a
    # second call against already-scrubbed data is a safe no-op.
    assert len(_sqls(connection, "DELETE FROM tutor_sessions")) == 2
    assert len(_sqls(connection, "DELETE FROM section_memberships")) == 2


# --- _redact_snapshot_for_archive (pure function) ---------------------------


def test_redact_snapshot_for_archive_covers_free_text_and_preserves_structure() -> None:
    snapshot = {
        "student": {"user_sub": "sub-1"},
        "student_phase": {"raw_input": "hi", "processed_input": "hi-processed"},
        "ide_context": {
            "raw_code_snippet": "print(1)",
            "clipboard_event": {"text": "copied"},
            "terminal_context": "exit 0",
            "mode": "editor",
        },
        "input_guardrail_phase": {
            "final_answer": "blocked reply",
            "evidence": "matched text",
            "blocked": False,
        },
        "backend_retrieval_phase": {
            "query_string": "how do i",
            "cpp_query_string": "how do i cpp",
            "doc_count": 3,
        },
        "orchestrator_phase": {
            "final_rendered_text": "final answer",
            "action_taken": "generate",
        },
        "ta_generation_phase": {
            "generation_history": [
                {
                    "raw_generation": "raw resp",
                    "cot_keys": {"Cognitive_Stage": "debugging"},
                }
            ],
            "attempts_count": 1,
        },
        "output_guardrail_phase": {
            "evidence": "leak evidence",
            "final_answer": "replacement",
            "blocked": True,
        },
        "trace": {"turn_index": 3},
        "course": {"section_id": "sec-1", "course_id": "mit14"},
    }

    redacted = _redact_snapshot_for_archive(snapshot)

    assert redacted["student"]["user_sub"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["student_phase"]["raw_input"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["student_phase"]["processed_input"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["ide_context"]["raw_code_snippet"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["ide_context"]["clipboard_event"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["ide_context"]["terminal_context"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["ide_context"]["mode"] == "editor"
    assert redacted["input_guardrail_phase"]["final_answer"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["input_guardrail_phase"]["evidence"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["input_guardrail_phase"]["blocked"] is False
    assert redacted["backend_retrieval_phase"]["query_string"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["backend_retrieval_phase"]["cpp_query_string"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["backend_retrieval_phase"]["doc_count"] == 3
    assert redacted["orchestrator_phase"]["final_rendered_text"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["orchestrator_phase"]["action_taken"] == "generate"
    generation = redacted["ta_generation_phase"]["generation_history"][0]
    assert generation["raw_generation"] == "[DELETED_FOR_PRIVACY]"
    assert generation["cot_keys"]["Cognitive_Stage"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["ta_generation_phase"]["attempts_count"] == 1
    assert redacted["output_guardrail_phase"]["evidence"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["output_guardrail_phase"]["final_answer"] == "[DELETED_FOR_PRIVACY]"
    assert redacted["output_guardrail_phase"]["blocked"] is True
    # Structural fields relied on by section-wide aggregate charts survive.
    assert redacted["trace"]["turn_index"] == 3
    assert redacted["course"]["section_id"] == "sec-1"
    assert redacted["course"]["course_id"] == "mit14"


# --- archive_section_data (Case 2a: course-end scrub) -----------------------


def test_archive_section_data_redacts_snapshots_and_nulls_identity_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {
        "student": {"user_sub": "sub-1"},
        "student_phase": {"raw_input": "hi there"},
    }
    connection = _FakeConnection(snapshot_rows=[("session-1", 0, snapshot)])
    _patch_connection(monkeypatch, connection)

    archive_section_data("section-1", runtime=_runtime())

    update_snapshot = _sqls(connection, "UPDATE tutor_turn_snapshots SET snapshot")
    assert len(update_snapshot) == 1
    _, params = update_snapshot[0]
    redacted_json, snap_session_id, turn_index = params
    assert snap_session_id == "session-1"
    assert turn_index == 0
    redacted = json.loads(redacted_json)
    assert redacted["student_phase"]["raw_input"] == "[DELETED_FOR_PRIVACY]"
    assert "hi there" not in redacted_json

    for table in ("tutor_sessions", "tutor_turns", "tutor_turn_snapshots", "telemetry_events"):
        matches = _sqls(connection, f"UPDATE {table} SET app_user_id = NULL, user_sub = NULL")
        assert len(matches) == 1, f"expected identity-null UPDATE for {table}"

    for table in ("ta_effectiveness_session_scores", "ta_effectiveness_turn_scores"):
        matches = _sqls(connection, f"UPDATE {table} SET app_user_id = NULL")
        assert len(matches) == 1, f"expected app_user_id UPDATE for {table}"

    assert len(_sqls(connection, "UPDATE reported_issues")) == 1
    delete_memberships = _sqls(connection, "DELETE FROM section_memberships")
    assert len(delete_memberships) == 1
    assert "role_in_section = 'student'" in delete_memberships[0][0]

    update_sections = _sqls(connection, "UPDATE sections")
    assert len(update_sections) == 1
    assert "archived_at = now()" in update_sections[0][0]
    assert connection.committed is True


def test_archive_section_data_raises_when_section_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(section_exists=False)
    _patch_connection(monkeypatch, connection)

    with pytest.raises(SectionNotFoundError):
        archive_section_data("missing-section", runtime=_runtime())


def test_archive_section_data_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeConnection(snapshot_rows=[])
    _patch_connection(monkeypatch, connection)

    archive_section_data("section-1", runtime=_runtime())
    archive_section_data("section-1", runtime=_runtime())

    assert len(_sqls(connection, "UPDATE sections")) == 2
