from __future__ import annotations

import pytest

import rag_eng.aurora_connect as aurora_connect
import rag_eng.aurora_secret_refresh as aurora_secret_refresh


def test_connect_postgres_passes_profile_and_timeout_through(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        aurora_connect,
        "connect_postgres_with_retry",
        lambda database_url, **kwargs: captured.update(
            {"database_url": database_url, **kwargs}
        )
        or object(),
    )

    aurora_connect.connect_postgres(
        "postgresql://example", profile="reliable", connect_timeout_seconds=3
    )

    assert captured == {
        "database_url": "postgresql://example",
        "profile": "reliable",
        "connect_timeout_seconds": 3,
    }


def test_connect_postgres_refreshes_and_retries_on_password_auth_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aurora_secret_refresh._refreshed_database_url = None
    calls: list[str] = []
    sentinel_connection = object()

    def fake_connect_with_retry(database_url, **kwargs):
        calls.append(database_url)
        if database_url == "postgresql://stale":
            raise RuntimeError('FATAL:  password authentication failed for user "cr_app"')
        return sentinel_connection

    monkeypatch.setattr(
        aurora_connect, "connect_postgres_with_retry", fake_connect_with_retry
    )
    monkeypatch.setattr(
        aurora_connect,
        "refresh_database_url_from_secrets_manager",
        lambda: "postgresql://fresh",
    )

    connection = aurora_connect.connect_postgres("postgresql://stale")

    assert connection is sentinel_connection
    assert calls == ["postgresql://stale", "postgresql://fresh"]

    aurora_secret_refresh._refreshed_database_url = None


def test_connect_postgres_does_not_refresh_on_non_auth_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aurora_secret_refresh._refreshed_database_url = None
    refresh_calls: list[bool] = []

    def fake_connect_with_retry(database_url, **kwargs):
        raise RuntimeError("connection timeout expired")

    monkeypatch.setattr(
        aurora_connect, "connect_postgres_with_retry", fake_connect_with_retry
    )
    monkeypatch.setattr(
        aurora_connect,
        "refresh_database_url_from_secrets_manager",
        lambda: refresh_calls.append(True) or "postgresql://fresh",
    )

    with pytest.raises(RuntimeError, match="connection timeout expired"):
        aurora_connect.connect_postgres("postgresql://example")

    assert refresh_calls == []


def test_connect_postgres_prefers_previously_cached_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aurora_secret_refresh._refreshed_database_url = "postgresql://already-fresh"
    calls: list[str] = []
    sentinel_connection = object()

    def fake_connect_with_retry(database_url, **kwargs):
        calls.append(database_url)
        return sentinel_connection

    monkeypatch.setattr(
        aurora_connect, "connect_postgres_with_retry", fake_connect_with_retry
    )

    connection = aurora_connect.connect_postgres("postgresql://stale-from-env")

    assert connection is sentinel_connection
    assert calls == ["postgresql://already-fresh"]

    aurora_secret_refresh._refreshed_database_url = None


def test_connect_postgres_interactive_binds_interactive_profile(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        aurora_connect,
        "connect_postgres_with_retry",
        lambda database_url, **kwargs: captured.update(
            {"database_url": database_url, **kwargs}
        )
        or object(),
    )

    aurora_connect.connect_postgres_interactive("postgresql://example", 3)

    assert captured == {
        "database_url": "postgresql://example",
        "profile": "interactive",
        "connect_timeout_seconds": 3,
    }


def test_connect_postgres_reliable_binds_reliable_profile(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        aurora_connect,
        "connect_postgres_with_retry",
        lambda database_url, **kwargs: captured.update(
            {"database_url": database_url, **kwargs}
        )
        or object(),
    )

    aurora_connect.connect_postgres_reliable("postgresql://example", 8)

    assert captured == {
        "database_url": "postgresql://example",
        "profile": "reliable",
        "connect_timeout_seconds": 8,
    }


def test_connect_postgres_does_not_retry_refresh_when_url_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If Secrets Manager hands back the same URL that just failed, don't
    loop forever - raise the original error instead."""
    aurora_secret_refresh._refreshed_database_url = None

    def fake_connect_with_retry(database_url, **kwargs):
        raise RuntimeError('FATAL:  password authentication failed for user "cr_app"')

    monkeypatch.setattr(
        aurora_connect, "connect_postgres_with_retry", fake_connect_with_retry
    )
    monkeypatch.setattr(
        aurora_connect,
        "refresh_database_url_from_secrets_manager",
        lambda: "postgresql://stale",
    )

    with pytest.raises(RuntimeError, match="password authentication failed"):
        aurora_connect.connect_postgres("postgresql://stale")

    aurora_secret_refresh._refreshed_database_url = None
