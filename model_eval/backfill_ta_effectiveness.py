"""One-time backfill: ingest TA Effectiveness scores for evaluation runs that
completed before `rag_eng.ta_effectiveness_ingest` existed.

Reuses the same `ingest_ta_effectiveness_scores` the live ECS worker calls,
reading the already-uploaded `macro_results.json`/`micro_results.json`/
`drift_results.json` artifacts back out of S3 (no re-run of the judge).

Usage (from repo root):
    python -m model_eval.backfill_ta_effectiveness --database-url postgresql://... [--dry-run]
    python -m model_eval.backfill_ta_effectiveness --evaluation-run-id <run_id> ...
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from rag_eng.aurora_retry import connect_postgres_with_retry
from rag_eng.aurora_secret_refresh import (
    get_cached_refreshed_url,
    is_password_auth_error,
    refresh_database_url_from_secrets_manager,
)
from rag_eng.ta_effectiveness_ingest import ingest_ta_effectiveness_scores

try:
    from . import eval_functions as ef
except ImportError:  # pragma: no cover - direct script execution fallback
    import eval_functions as ef

load_dotenv()

logger = logging.getLogger(__name__)

_ARTIFACT_TYPES = ("macro", "micro", "drift")


def _connect_postgres_with_secret_refresh(database_url: str, *, profile: str = "reliable"):
    """Connect to Aurora, self-healing from a rotated master password.

    Prefers a previously Secrets-Manager-refreshed URL over the one passed in,
    and on a password-auth failure specifically, refreshes from Secrets
    Manager and retries once - see rag_eng/aurora_secret_refresh.py for why a
    plain retry can't recover from this on its own.
    """
    effective_url = get_cached_refreshed_url() or database_url
    try:
        return connect_postgres_with_retry(effective_url, profile=profile)
    except Exception as exc:
        if not is_password_auth_error(exc):
            raise
        refreshed_url = refresh_database_url_from_secrets_manager()
        if not refreshed_url or refreshed_url == effective_url:
            raise
        return connect_postgres_with_retry(refreshed_url, profile=profile)


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _build_s3_client(*, region: str, profile_name: str | None):
    import boto3

    session = boto3.Session(profile_name=profile_name, region_name=region)
    return session.client("s3")


def _download_json(s3_client, s3_uri: str) -> Any:
    bucket, key = _parse_s3_uri(s3_uri)
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"].read().decode("utf-8")
    return json.loads(body)


def _fetch_succeeded_runs(
    connection, evaluation_run_id: str | None
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        if evaluation_run_id:
            cursor.execute(
                """
                SELECT evaluation_run_id, results_s3_prefix, completed_at
                FROM evaluation_runs
                WHERE status = 'succeeded' AND evaluation_run_id = %s
                """,
                (evaluation_run_id,),
            )
        else:
            cursor.execute(
                """
                SELECT evaluation_run_id, results_s3_prefix, completed_at
                FROM evaluation_runs
                WHERE status = 'succeeded'
                ORDER BY completed_at ASC
                """
            )
        rows = cursor.fetchall()
    return [
        {"evaluation_run_id": row[0], "results_s3_prefix": row[1], "completed_at": row[2]}
        for row in rows
    ]


def _fetch_result_artifact_uris(connection, evaluation_run_id: str) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT artifact_type, s3_uri
            FROM evaluation_run_artifacts
            WHERE evaluation_run_id = %s AND artifact_type = ANY(%s)
            """,
            (evaluation_run_id, list(_ARTIFACT_TYPES)),
        )
        rows = cursor.fetchall()
    return {row[0]: row[1] for row in rows}


def backfill_run(
    connection,
    s3_client,
    *,
    evaluation_run_id: str,
    results_s3_prefix: str,
    completed_at: datetime | None,
    dry_run: bool,
) -> dict[str, int]:
    artifact_uris = _fetch_result_artifact_uris(connection, evaluation_run_id)
    missing = [t for t in ("macro", "micro") if t not in artifact_uris]
    if missing:
        logger.warning(
            "Run %s is missing required artifact(s) %s (prefix=%s) — skipping.",
            evaluation_run_id,
            missing,
            results_s3_prefix,
        )
        return {"sessions_written": 0, "turns_written": 0, "sessions_skipped_no_session_row": 0}

    macro_results = _download_json(s3_client, artifact_uris["macro"])
    micro_results = _download_json(s3_client, artifact_uris["micro"])
    drift_results = (
        _download_json(s3_client, artifact_uris["drift"]) if "drift" in artifact_uris else {}
    )

    if dry_run:
        logger.info(
            "[dry-run] Run %s: would ingest %d macro / %d micro records.",
            evaluation_run_id,
            len(macro_results),
            len(micro_results),
        )
        return {"sessions_written": 0, "turns_written": 0, "sessions_skipped_no_session_row": 0}

    # Note: `with connection:` in psycopg3 both commits/rolls back AND closes
    # the connection on exit — using it here (rather than explicit
    # commit/rollback) would close the connection after the first run and
    # break every subsequent run in the same backfill pass.
    try:
        result = ingest_ta_effectiveness_scores(
            connection,
            evaluation_run_id=evaluation_run_id,
            macro_results=macro_results,
            micro_results=micro_results,
            drift_results=drift_results,
            macro_metric_names=ef.macro_metrics,
            micro_metric_names=ef.micro_metrics,
            scored_at=completed_at or datetime.now(timezone.utc),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    logger.info("Run %s: %s", evaluation_run_id, result)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill ta_effectiveness_session_scores/turn_scores from past succeeded evaluation runs."
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--evaluation-run-id", default=None, help="Backfill a single run instead of all succeeded runs.")
    parser.add_argument("--aws-region", default=None)
    parser.add_argument("--aws-profile", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Report what would be ingested without writing to Aurora.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    env = os.environ

    database_url = (
        args.database_url
        or env.get("EVALUATION_DATABASE_URL")
        or env.get("COURSE_REGISTRY_DATABASE_URL")
        or env.get("DATABASE_URL")
    )
    if not database_url:
        parser.error("A database URL is required (--database-url or EVALUATION_DATABASE_URL).")

    region = (args.aws_region or env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1").strip()
    profile_name = args.aws_profile or env.get("AWS_PROFILE") or None

    connection = _connect_postgres_with_secret_refresh(database_url, profile="reliable")
    s3_client = _build_s3_client(region=region, profile_name=profile_name)

    totals = {"sessions_written": 0, "turns_written": 0, "sessions_skipped_no_session_row": 0, "runs_processed": 0}
    runs = _fetch_succeeded_runs(connection, args.evaluation_run_id)
    connection.commit()
    logger.info("Found %d succeeded run(s) to backfill.", len(runs))
    for run in runs:
        # backfill_run commits/rolls back explicitly per run and keeps the
        # connection open — reused across every run in this loop.
        result = backfill_run(
            connection,
            s3_client,
            evaluation_run_id=run["evaluation_run_id"],
            results_s3_prefix=run["results_s3_prefix"],
            completed_at=run["completed_at"],
            dry_run=args.dry_run,
        )
        totals["runs_processed"] += 1
        for key in ("sessions_written", "turns_written", "sessions_skipped_no_session_row"):
            totals[key] += result[key]

    logger.info("Backfill complete: %s", totals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
