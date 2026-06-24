from __future__ import annotations

from dataclasses import dataclass

import pytest

from rag_eng.aurora_retry import (
    INTERACTIVE_RETRY_PROFILE,
    RELIABLE_RETRY_PROFILE,
    connect_postgres_with_retry,
    get_retry_profile,
)


@dataclass
class _FakePsycopg:
    outcomes: list[object]
    calls: list[tuple[str, int]]

    def connect(self, database_url: str, *, connect_timeout: int):
        self.calls.append((database_url, connect_timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_get_retry_profile_returns_expected_defaults() -> None:
    assert get_retry_profile("interactive") == INTERACTIVE_RETRY_PROFILE
    assert get_retry_profile("reliable") == RELIABLE_RETRY_PROFILE


def test_connect_postgres_with_retry_uses_retries_until_success(monkeypatch) -> None:
    sleep_calls: list[float] = []
    fake_psycopg = _FakePsycopg(
        outcomes=[
            RuntimeError("connection timeout expired"),
            RuntimeError("connection timeout expired"),
            object(),
        ],
        calls=[],
    )

    monkeypatch.setattr(
        "rag_eng.aurora_retry._load_psycopg_module",
        lambda: fake_psycopg,
    )

    connection = connect_postgres_with_retry(
        "postgresql://example",
        profile="interactive",
        sleep_func=sleep_calls.append,
    )

    assert connection is not None
    assert fake_psycopg.calls == [
        ("postgresql://example", 3),
        ("postgresql://example", 3),
        ("postgresql://example", 3),
    ]
    assert sleep_calls == [1.0, 1.0]


def test_connect_postgres_with_retry_reraises_last_error(monkeypatch) -> None:
    fake_psycopg = _FakePsycopg(
        outcomes=[RuntimeError("boom")] * 5,
        calls=[],
    )

    monkeypatch.setattr(
        "rag_eng.aurora_retry._load_psycopg_module",
        lambda: fake_psycopg,
    )

    with pytest.raises(RuntimeError, match="boom"):
        connect_postgres_with_retry(
            "postgresql://example",
            profile="interactive",
            sleep_func=lambda _seconds: None,
        )

    assert len(fake_psycopg.calls) == 5
