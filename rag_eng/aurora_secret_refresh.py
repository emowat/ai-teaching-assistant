"""Recovers from Aurora password rotation for long-running processes.

Aurora's master password is managed and auto-rotated by AWS itself (RDS's
"Manage master user password" feature), on its own schedule, independent of
anything in this repo - see `aws rds describe-db-clusters` for
`MasterUserSecret.SecretArn` and `aws secretsmanager describe-secret` on that
ARN for the rotation schedule. That AWS-managed secret stores only
`{"username": ..., "password": ...}` as JSON; it has no knowledge of which
host/port/database this app should connect to, and ECS only resolves it once,
at task launch. Nothing re-checks it afterward, so any task alive longer than
the rotation interval starts failing with "password authentication failed"
until it's replaced. This module lets a live process self-heal from that: on
an auth failure, re-fetch fresh credentials from the AWS-managed secret and
rebuild the connection URL from them plus the (stable, non-rotating)
host/port/database.

Earlier versions of this module refreshed from a separate, manually-created
"codingrabbit/rag_eng/COURSE_REGISTRY_DATABASE_URL" secret - that secret is
never updated by AWS's rotation at all, so refreshing from it just re-fetched
the same stale password. Always point COURSE_REGISTRY_DATABASE_URL_SECRET_ID
at the AWS-managed secret's ARN, not that one.
"""

from __future__ import annotations

import json
import os
import threading
from urllib.parse import quote

_lock = threading.Lock()
_refreshed_database_url: str | None = None


def is_password_auth_error(exc: BaseException) -> bool:
    """True for a Postgres password-authentication failure (SQLSTATE 28P01),
    as opposed to a transient/connectivity error a plain retry might still
    resolve on its own (e.g. Aurora waking up from a scale-to-zero pause)."""
    if getattr(exc, "sqlstate", None) == "28P01":
        return True
    return "password authentication failed" in str(exc)


def get_cached_refreshed_url() -> str | None:
    """The most recent Secrets-Manager-refreshed URL, if this process has
    ever needed to refresh one. None means "no refresh has happened yet" -
    callers should fall back to whatever database_url they already have."""
    return _refreshed_database_url


def _build_database_url_from_credentials(username: str, password: str) -> str | None:
    """Combine live username/password with the stable, non-rotating
    connection details (host/port/database/sslmode) to build a full
    connection URL. Returns None if the host isn't configured (e.g. local
    dev, where there's nothing to rebuild against)."""
    host = os.getenv("COURSE_REGISTRY_DB_HOST", "").strip()
    if not host:
        return None
    port = os.getenv("COURSE_REGISTRY_DB_PORT", "5432").strip() or "5432"
    dbname = os.getenv("COURSE_REGISTRY_DB_NAME", "postgres").strip() or "postgres"
    sslmode = os.getenv("COURSE_REGISTRY_DB_SSLMODE", "require").strip() or "require"
    return (
        f"postgresql://{quote(username, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{dbname}?sslmode={sslmode}"
    )


def refresh_database_url_from_secrets_manager(
    *, secret_id_env_key: str = "COURSE_REGISTRY_DATABASE_URL_SECRET_ID"
) -> str | None:
    """Re-fetch the current Aurora credentials from Secrets Manager using the
    task's own runtime IAM role, rebuild the connection URL, and cache it for
    subsequent connections in this process. Returns None (without raising) if
    no secret ID is configured, or if the fetch/rebuild fails for any reason -
    callers should fall back to whatever database_url they already have.
    """
    global _refreshed_database_url
    secret_id = os.getenv(secret_id_env_key, "").strip()
    if not secret_id:
        return None

    with _lock:
        try:
            import boto3

            client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION"))
            secret_string = client.get_secret_value(SecretId=secret_id)["SecretString"]
        except Exception:
            return None

        secret_string = secret_string.strip()
        if not secret_string:
            return None

        # AWS-managed RDS secrets are JSON: {"username": ..., "password": ...}.
        # Fall back to treating the whole string as a ready-made URL for
        # flexibility in environments using a plain-string secret instead.
        try:
            parsed = json.loads(secret_string)
        except (json.JSONDecodeError, TypeError):
            parsed = None

        value: str | None
        if isinstance(parsed, dict) and "username" in parsed and "password" in parsed:
            value = _build_database_url_from_credentials(
                str(parsed["username"]), str(parsed["password"])
            )
        else:
            value = secret_string

        if not value:
            return None
        _refreshed_database_url = value
        return value
