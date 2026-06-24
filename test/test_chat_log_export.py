from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json

from rag_eng.chat_log_export import export_turn_snapshots_to_s3


@dataclass
class _FakeCursor:
    rows: list[tuple[datetime, dict]]
    statements: list[tuple[str, tuple]]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params):
        self.statements.append((sql, params))

    def fetchall(self):
        return list(self.rows)


@dataclass
class _FakeConnection:
    cursor_obj: _FakeCursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_obj


class _FakeS3Client:
    def __init__(self):
        self.put_objects: list[dict[str, object]] = []

    def put_object(self, **kwargs):
        self.put_objects.append(kwargs)


class _FakeSession:
    def __init__(self, client):
        self._client = client
        self.kwargs = None

    def client(self, service_name):
        assert service_name == "s3"
        return self._client


def test_connect_postgres_uses_reliable_retry_profile(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "rag_eng.chat_log_export.connect_postgres_with_retry",
        lambda database_url, **kwargs: captured.update(
            {"database_url": database_url, **kwargs}
        )
        or object(),
    )

    from rag_eng.chat_log_export import _connect_postgres

    _connect_postgres("postgresql://example", 3)

    assert captured == {
        "database_url": "postgresql://example",
        "profile": "reliable",
        "connect_timeout_seconds": 3,
    }


def test_export_turn_snapshots_groups_by_date_and_uploads_jsonl(monkeypatch):
    rows = [
        (
            datetime(2026, 6, 23, 1, 2, tzinfo=timezone.utc),
            {
                "schema_version": "v1",
                "trace": {
                    "request_id": "req-1",
                    "session_id": "sess-1",
                    "turn_id": "turn-1",
                    "turn_index": 1,
                    "source": "chat",
                },
                "final_response": {"text": "one", "source": "model"},
            },
        ),
        (
            datetime(2026, 6, 23, 20, 3, tzinfo=timezone.utc),
            {
                "schema_version": "v1",
                "trace": {
                    "request_id": "req-2",
                    "session_id": "sess-1",
                    "turn_id": "turn-2",
                    "turn_index": 2,
                    "source": "chat",
                },
                "final_response": {"text": "two", "source": "model"},
            },
        ),
        (
            datetime(2026, 6, 24, 0, 1, tzinfo=timezone.utc),
            {
                "schema_version": "v1",
                "trace": {
                    "request_id": "req-3",
                    "session_id": "sess-2",
                    "turn_id": "turn-3",
                    "turn_index": 1,
                    "source": "chat",
                },
                "final_response": {"text": "three", "source": "input_guardrail"},
            },
        ),
    ]
    statements: list[tuple[str, tuple]] = []
    fake_connection = _FakeConnection(cursor_obj=_FakeCursor(rows, statements))
    fake_client = _FakeS3Client()
    fake_session = _FakeSession(fake_client)

    monkeypatch.setattr(
        "rag_eng.chat_log_export._connect_postgres",
        lambda *_args, **_kwargs: fake_connection,
    )
    monkeypatch.setattr(
        "rag_eng.chat_log_export.boto3.Session",
        lambda **kwargs: fake_session,
    )

    result = export_turn_snapshots_to_s3(
        database_url="postgresql://example",
        bucket="codingrabbit-data-dev",
        prefix="eval/chat_logs/turn_logs",
        start_date=date(2026, 6, 23),
        end_date=date(2026, 6, 24),
    )

    assert [item["date"] for item in result] == ["2026-06-23", "2026-06-24"]
    assert result[0]["record_count"] == 2
    assert result[1]["record_count"] == 1
    assert fake_client.put_objects[0]["Key"] == (
        "eval/chat_logs/turn_logs/date=2026-06-23/turn_snapshots.jsonl"
    )
    assert fake_client.put_objects[1]["Key"] == (
        "eval/chat_logs/turn_logs/date=2026-06-24/turn_snapshots.jsonl"
    )

    body_lines = fake_client.put_objects[0]["Body"].decode("utf-8").strip().splitlines()
    exported = [json.loads(line) for line in body_lines]
    assert exported[0]["trace"]["turn_id"] == "turn-1"
    assert exported[1]["trace"]["turn_id"] == "turn-2"

    sql, params = statements[0]
    assert "FROM tutor_turn_snapshots" in sql
    assert len(params) == 2


def test_export_turn_snapshots_adds_course_partition(monkeypatch):
    rows = [
        (
            datetime(2026, 6, 23, 1, 2, tzinfo=timezone.utc),
            {
                "schema_version": "v1",
                "trace": {
                    "request_id": "req-1",
                    "session_id": "sess-1",
                    "turn_id": "turn-1",
                    "turn_index": 1,
                    "source": "chat",
                },
                "course": {
                    "course_id": "mit14",
                    "course_source": "mit14",
                    "section_id": "week-6",
                },
                "final_response": {"text": "one", "source": "model"},
            },
        ),
    ]
    fake_connection = _FakeConnection(
        cursor_obj=_FakeCursor(rows, statements=[]),
    )
    fake_client = _FakeS3Client()

    monkeypatch.setattr(
        "rag_eng.chat_log_export._connect_postgres",
        lambda *_args, **_kwargs: fake_connection,
    )
    monkeypatch.setattr(
        "rag_eng.chat_log_export.boto3.Session",
        lambda **kwargs: _FakeSession(fake_client),
    )

    result = export_turn_snapshots_to_s3(
        database_url="postgresql://example",
        bucket="codingrabbit-data-dev",
        prefix="eval/chat_logs/turn_logs",
        start_date=date(2026, 6, 23),
        end_date=date(2026, 6, 23),
        course_id="mit14",
    )

    assert result[0]["key"] == (
        "eval/chat_logs/turn_logs/course_id=mit14/date=2026-06-23/turn_snapshots.jsonl"
    )
    assert len(fake_connection.cursor_obj.statements[0][1]) == 3
