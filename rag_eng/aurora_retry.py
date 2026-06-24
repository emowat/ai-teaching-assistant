"""Shared Aurora/PostgreSQL connection retry profiles."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AuroraRetryProfile:
    """Bounded retry settings for Aurora wake-up tolerant connections."""

    name: str
    connect_timeout_seconds: int
    max_attempts: int
    retry_sleep_seconds: float


INTERACTIVE_RETRY_PROFILE = AuroraRetryProfile(
    name="interactive",
    connect_timeout_seconds=3,
    max_attempts=5,
    retry_sleep_seconds=1.0,
)

RELIABLE_RETRY_PROFILE = AuroraRetryProfile(
    name="reliable",
    connect_timeout_seconds=3,
    max_attempts=8,
    retry_sleep_seconds=1.0,
)

_RETRY_PROFILES = {
    INTERACTIVE_RETRY_PROFILE.name: INTERACTIVE_RETRY_PROFILE,
    RELIABLE_RETRY_PROFILE.name: RELIABLE_RETRY_PROFILE,
}


def _load_psycopg_module() -> Any:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - only when dependency missing
        raise RuntimeError("psycopg is required for Aurora/PostgreSQL access.") from exc
    return psycopg


def get_retry_profile(name: str) -> AuroraRetryProfile:
    """Return one of the predefined Aurora retry profiles."""
    try:
        return _RETRY_PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown Aurora retry profile: {name}") from exc


def connect_postgres_with_retry(
    database_url: str,
    *,
    profile: str = "interactive",
    connect_timeout_seconds: int | None = None,
    max_attempts: int | None = None,
    retry_sleep_seconds: float | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> Any:
    """Connect to Aurora/PostgreSQL with a bounded retry loop."""
    retry_profile = get_retry_profile(profile)
    timeout_seconds = (
        retry_profile.connect_timeout_seconds
        if connect_timeout_seconds is None
        else connect_timeout_seconds
    )
    attempts_limit = (
        retry_profile.max_attempts if max_attempts is None else max_attempts
    )
    sleep_seconds = (
        retry_profile.retry_sleep_seconds
        if retry_sleep_seconds is None
        else retry_sleep_seconds
    )
    if attempts_limit < 1:
        raise ValueError("max_attempts must be at least 1")
    if timeout_seconds < 1:
        raise ValueError("connect_timeout_seconds must be at least 1")
    if sleep_seconds < 0:
        raise ValueError("retry_sleep_seconds must be non-negative")

    psycopg = _load_psycopg_module()
    last_error: Exception | None = None
    for attempt_index in range(1, attempts_limit + 1):
        try:
            return psycopg.connect(
                database_url,
                connect_timeout=timeout_seconds,
            )
        except Exception as exc:
            last_error = exc
            if attempt_index >= attempts_limit:
                break
            sleep_func(sleep_seconds)

    assert last_error is not None
    raise last_error
