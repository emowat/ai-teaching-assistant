"""Single shared Aurora/PostgreSQL connector: bounded retry + password self-heal.

Composes aurora_retry's wake-up-tolerant bounded retry loop with
aurora_secret_refresh's refresh-on-auth-failure recovery, so every caller
gets both behaviors from one place instead of hand-copying this
try/except body per file. See aurora_secret_refresh.py for why a plain
retry loop alone can't recover from a rotated master password - it just
retries the same now-wrong password until the attempts run out.

This is the module every DB-writing entry point should import instead of
defining its own local _connect_postgres. See the project's Postgres
connection centralization effort - prior to this module, at least nine
call sites across rag/, rag_eng/, and model_eval/ each hand-copied a
slightly different version of this same body, and three of them
(rag/course_registry.py, rag_eng/document_admin.py,
rag_eng/ingestion_jobs.py) had no self-heal at all.
"""

from __future__ import annotations

from typing import Any

from rag_eng.aurora_retry import connect_postgres_with_retry
from rag_eng.aurora_secret_refresh import (
    get_cached_refreshed_url,
    is_password_auth_error,
    refresh_database_url_from_secrets_manager,
)


def connect_postgres(
    database_url: str,
    *,
    profile: str = "interactive",
    connect_timeout_seconds: int | None = None,
) -> Any:
    """Connect to Aurora, preferring a cached refresh and self-healing once
    on a password-rotation auth failure.

    Prefers a previously Secrets-Manager-refreshed URL over the one passed
    in (which every caller resolves from a process-lifetime-static env
    var). On a password-auth failure specifically (SQLSTATE 28P01), re-fetch
    fresh credentials from Secrets Manager and retry once. Any other
    failure (e.g. a transient connectivity error already exhausted by the
    retry profile) propagates unchanged.
    """
    effective_url = get_cached_refreshed_url() or database_url
    try:
        return connect_postgres_with_retry(
            effective_url,
            profile=profile,
            connect_timeout_seconds=connect_timeout_seconds,
        )
    except Exception as exc:
        if not is_password_auth_error(exc):
            raise
        refreshed_url = refresh_database_url_from_secrets_manager()
        if not refreshed_url or refreshed_url == effective_url:
            raise
        return connect_postgres_with_retry(
            refreshed_url,
            profile=profile,
            connect_timeout_seconds=connect_timeout_seconds,
        )


def connect_postgres_interactive(
    database_url: str, connect_timeout_seconds: int | None = None
) -> Any:
    """connect_postgres() bound to the "interactive" profile (fast-fail,
    request/health-path calls). Import this directly as a call site's
    _connect_postgres - every caller observed in this codebase uses a
    single fixed profile for its entire lifetime, so there is no need for
    each file to define its own pass-through wrapper just to bind that
    choice.
    """
    return connect_postgres(
        database_url, profile="interactive", connect_timeout_seconds=connect_timeout_seconds
    )


def connect_postgres_reliable(
    database_url: str, connect_timeout_seconds: int | None = None
) -> Any:
    """connect_postgres() bound to the "reliable" profile (more patient,
    background/export/evaluation jobs). See connect_postgres_interactive.
    """
    return connect_postgres(
        database_url, profile="reliable", connect_timeout_seconds=connect_timeout_seconds
    )
