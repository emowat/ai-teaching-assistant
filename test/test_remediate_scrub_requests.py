from __future__ import annotations

from typing import Any

import deploy.remediate_scrub_requests as remediate


class _FakeCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        return None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows
        self.committed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows)

    def commit(self) -> None:
        self.committed = True


def test_main_re_scrubs_every_completed_deletion_request(monkeypatch) -> None:
    connection = _FakeConnection([("user-1",), ("user-2",)])
    monkeypatch.setattr(
        remediate, "connect_postgres_with_retry", lambda *args, **kwargs: connection
    )
    scrubbed: list[str] = []
    monkeypatch.setattr(remediate, "scrub_user_data", lambda user_id: scrubbed.append(user_id))
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://example")

    exit_code = remediate.main([])

    assert exit_code == 0
    assert scrubbed == ["user-1", "user-2"]
    assert connection.committed is True


def test_main_dry_run_does_not_scrub_anyone(monkeypatch) -> None:
    connection = _FakeConnection([("user-1",)])
    monkeypatch.setattr(
        remediate, "connect_postgres_with_retry", lambda *args, **kwargs: connection
    )
    scrubbed: list[str] = []
    monkeypatch.setattr(remediate, "scrub_user_data", lambda user_id: scrubbed.append(user_id))
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://example")

    exit_code = remediate.main(["--dry-run"])

    assert exit_code == 0
    assert scrubbed == []


def test_main_handles_no_completed_requests(monkeypatch) -> None:
    connection = _FakeConnection([])
    monkeypatch.setattr(
        remediate, "connect_postgres_with_retry", lambda *args, **kwargs: connection
    )
    scrubbed: list[str] = []
    monkeypatch.setattr(remediate, "scrub_user_data", lambda user_id: scrubbed.append(user_id))
    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://example")

    exit_code = remediate.main([])

    assert exit_code == 0
    assert scrubbed == []
