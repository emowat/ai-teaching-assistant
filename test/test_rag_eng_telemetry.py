from __future__ import annotations

from collections.abc import Callable

from rag.schemas import CourseSource, QueryInput
from rag_eng.telemetry import TelemetryStore


class _FakeCursor:
    def __init__(self, statements: list[tuple[str, tuple | None]]) -> None:
        self._statements = statements

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self._statements.append((sql.strip(), params))

    def fetchone(self):
        return [1]


class _FakeConnection:
    def __init__(self, statements: list[tuple[str, tuple | None]]) -> None:
        self._statements = statements

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._statements)


def _fake_connect_factory(
    statements: list[tuple[str, tuple | None]],
) -> Callable[[str, int], _FakeConnection]:
    def _connect(_database_url: str, _connect_timeout_seconds: int) -> _FakeConnection:
        return _FakeConnection(statements)

    return _connect


def test_telemetry_store_persists_session_turn_and_events(monkeypatch) -> None:
    statements: list[tuple[str, tuple | None]] = []
    monkeypatch.setattr(
        "rag_eng.telemetry._connect_postgres",
        _fake_connect_factory(statements),
    )

    store = TelemetryStore(database_url="postgresql://example")
    trace = store.start_turn(
        query=QueryInput(
            student_message="Why does this crash?",
            week=2,
            course_id="mit14",
            course_source=CourseSource.MIT_14,
            session_id="session-1",
            request_id="request-1",
            turn_id="turn-1",
        ),
        source="chat",
    )

    assert trace.session_id == "session-1"
    assert trace.request_id == "request-1"
    assert trace.turn_id == "turn-1"
    assert trace.turn_index == 1

    assert store.record_event(
        trace,
        event_type="retrieval_started",
        stage="retrieval",
        status="started",
        metadata={"source": "chat"},
    )

    assert store.finish_turn(
        trace,
        status="completed",
        latency_ms=42,
        model_provider="sagemaker",
        model_name="codingrabbit-ta",
        answer_chars=128,
        metadata={"source": "chat"},
    )

    sql_text = "\n".join(statement for statement, _ in statements)
    assert "INSERT INTO tutor_sessions" in sql_text
    assert "INSERT INTO tutor_turns" in sql_text
    assert "INSERT INTO telemetry_events" in sql_text
    assert "UPDATE tutor_sessions" in sql_text
    assert "UPDATE tutor_turns" in sql_text

    event_types = [params[8] for statement, params in statements if "telemetry_events" in statement]
    assert "request_started" in event_types
    assert "retrieval_started" in event_types
    assert "answer_returned" in event_types
