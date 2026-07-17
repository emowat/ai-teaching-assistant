from __future__ import annotations

from dataclasses import dataclass

from rag_eng.telemetry import TelemetryStore, TraceContext


@dataclass
class _FakeCursor:
    statements: list[tuple[str, tuple]]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.statements.append((sql, params))


@dataclass
class _FakeConnection:
    cursor_obj: _FakeCursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        return None


def test_connect_postgres_uses_interactive_retry_profile(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "rag_eng.telemetry.connect_postgres_with_retry",
        lambda database_url, **kwargs: captured.update(
            {"database_url": database_url, **kwargs}
        )
        or object(),
    )

    from rag_eng.telemetry import _connect_postgres

    _connect_postgres("postgresql://example", 3)

    assert captured == {
        "database_url": "postgresql://example",
        "profile": "interactive",
        "connect_timeout_seconds": 3,
    }


def test_connect_postgres_refreshes_and_retries_on_password_auth_failure(
    monkeypatch,
) -> None:
    import rag_eng.aurora_secret_refresh as aurora_secret_refresh
    from rag_eng.telemetry import _connect_postgres

    aurora_secret_refresh._refreshed_database_url = None
    calls: list[str] = []
    sentinel_connection = object()

    def fake_connect_with_retry(database_url, **kwargs):
        calls.append(database_url)
        if database_url == "postgresql://stale":
            raise RuntimeError('FATAL:  password authentication failed for user "cr_app"')
        return sentinel_connection

    monkeypatch.setattr(
        "rag_eng.telemetry.connect_postgres_with_retry", fake_connect_with_retry
    )
    monkeypatch.setattr(
        "rag_eng.telemetry.refresh_database_url_from_secrets_manager",
        lambda: "postgresql://fresh",
    )

    connection = _connect_postgres("postgresql://stale", 3)

    assert connection is sentinel_connection
    assert calls == ["postgresql://stale", "postgresql://fresh"]


def test_connect_postgres_does_not_refresh_on_non_auth_error(monkeypatch) -> None:
    import rag_eng.aurora_secret_refresh as aurora_secret_refresh
    from rag_eng.telemetry import _connect_postgres

    aurora_secret_refresh._refreshed_database_url = None
    refresh_calls: list[bool] = []

    def fake_connect_with_retry(database_url, **kwargs):
        raise RuntimeError("connection timeout expired")

    monkeypatch.setattr(
        "rag_eng.telemetry.connect_postgres_with_retry", fake_connect_with_retry
    )
    monkeypatch.setattr(
        "rag_eng.telemetry.refresh_database_url_from_secrets_manager",
        lambda: refresh_calls.append(True) or "postgresql://fresh",
    )

    try:
        _connect_postgres("postgresql://example", 3)
        assert False, "expected RuntimeError to propagate"
    except RuntimeError as exc:
        assert "connection timeout expired" in str(exc)

    assert refresh_calls == []


def test_connect_postgres_prefers_previously_cached_refresh(monkeypatch) -> None:
    import rag_eng.aurora_secret_refresh as aurora_secret_refresh
    from rag_eng.telemetry import _connect_postgres

    aurora_secret_refresh._refreshed_database_url = "postgresql://already-fresh"
    calls: list[str] = []
    sentinel_connection = object()

    def fake_connect_with_retry(database_url, **kwargs):
        calls.append(database_url)
        return sentinel_connection

    monkeypatch.setattr(
        "rag_eng.telemetry.connect_postgres_with_retry", fake_connect_with_retry
    )

    connection = _connect_postgres("postgresql://stale-from-env", 3)

    assert connection is sentinel_connection
    assert calls == ["postgresql://already-fresh"]

    aurora_secret_refresh._refreshed_database_url = None


def test_record_turn_snapshot_writes_aura_sql(monkeypatch) -> None:
    statements: list[tuple[str, tuple]] = []
    fake_connection = _FakeConnection(cursor_obj=_FakeCursor(statements))

    monkeypatch.setattr(
        "rag_eng.telemetry._connect_postgres",
        lambda *_args, **_kwargs: fake_connection,
    )
    monkeypatch.setattr(
        "rag_eng.telemetry._json_adapter",
        lambda data: data,
    )

    store = TelemetryStore(database_url="postgresql://example")
    trace = TraceContext(
        request_id="req-1",
        session_id="sess-1",
        turn_id="turn-1",
        turn_index=3,
        source="chat",
        course_id="mit14",
        course_source="mit14",
        section_id="week-6",
        user_sub="student-1",
        app_user_id="app-user-1",
        mode="Homework Assist",
        week=6,
        persisted=True,
    )
    snapshot = {
        "schema_version": "v1",
        "trace": {
            "request_id": "req-1",
            "session_id": "sess-1",
            "turn_id": "turn-1",
            "turn_index": 3,
            "source": "chat",
        },
        "orchestrator_phase": {
            "final_rendered_text": "hello"
        },
    }

    assert store.record_turn_snapshot(trace, snapshot) is True
    assert len(statements) == 1
    sql, params = statements[0]
    assert "INSERT INTO tutor_turn_snapshots" in sql
    assert sql.count("%s") == 11
    assert params[0] == "turn-1"
    assert params[1] == "sess-1"
    assert params[2] == "req-1"
    assert params[3] == 3
    assert params[4] == "student-1"
    assert params[5] == "app-user-1"
    assert params[6] == "mit14"
    assert params[9] == "v1"
    assert params[10] == snapshot


def test_record_out_of_band_telemetry_writes_app_user_id(monkeypatch) -> None:
    statements: list[tuple[str, tuple]] = []
    fake_connection = _FakeConnection(cursor_obj=_FakeCursor(statements))

    monkeypatch.setattr(
        "rag_eng.telemetry._connect_postgres",
        lambda *_args, **_kwargs: fake_connection,
    )
    monkeypatch.setattr(
        "rag_eng.telemetry._json_adapter",
        lambda data: data,
    )

    store = TelemetryStore(database_url="postgresql://example")

    assert store.record_out_of_band_telemetry(
        session_id="sess-1",
        mode="Homework Assist",
        engagement_metrics={
            "paste_count": 1,
            "run_count": 0,
            "hint_count": 2,
            "telemetry_version": "v1",
        },
        request_id="req-1",
        turn_id="turn-1",
        turn_index=2,
        section_id="mit14-fall-001",
        user_sub="student-1",
        app_user_id="app-user-1",
        course_id="mit14",
        course_source="mit14",
    )
    assert len(statements) == 1
    sql, params = statements[0]
    assert "INSERT INTO telemetry_events" in sql
    assert params[4] == "student-1"
    assert params[5] == "app-user-1"
    assert params[6] == "mit14"
    assert params[7] == "mit14"
    assert params[8] == "mit14-fall-001"
    assert params[9] == "out_of_band_telemetry"


def test_record_feedback_updates_turn_by_app_user_id(monkeypatch) -> None:
    statements: list[tuple[str, tuple]] = []
    fake_connection = _FakeConnection(cursor_obj=_FakeCursor(statements))

    monkeypatch.setattr(
        "rag_eng.telemetry._connect_postgres",
        lambda *_args, **_kwargs: fake_connection,
    )
    monkeypatch.setattr(
        "rag_eng.telemetry._json_adapter",
        lambda data: data,
    )

    store = TelemetryStore(database_url="postgresql://example")

    assert store.record_feedback(
        session_id="sess-1",
        message_index=2,
        rating="up",
        reason="helpful",
        turn_id="turn-1",
        user_sub="student-1",
        app_user_id="app-user-1",
    )
    assert len(statements) == 1
    sql, params = statements[0]
    assert "UPDATE tutor_turn_snapshots" in sql
    assert params[0] == "positive"
    assert params[2] == "turn-1"
    assert params[3] == "student-1"
    assert params[5] == "app-user-1"
