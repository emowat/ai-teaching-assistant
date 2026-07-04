"""Export canonical turn snapshots from Aurora to S3 JSONL."""

from __future__ import annotations

import argparse
import json
import logging
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import boto3
from rag_eng.aurora_retry import connect_postgres_with_retry
from rag_eng.config import get_runtime_policy_config


logger = logging.getLogger(__name__)
try:
    _RUNTIME_EXPORT_CONFIG = get_runtime_policy_config().chat_log_export
    DEFAULT_EXPORT_PREFIX = _RUNTIME_EXPORT_CONFIG.prefix
    DEFAULT_EXPORT_BUCKET = _RUNTIME_EXPORT_CONFIG.bucket
    DEFAULT_EXPORT_CONNECT_TIMEOUT_SECONDS = (
        _RUNTIME_EXPORT_CONFIG.connect_timeout_seconds
    )
except Exception:
    DEFAULT_EXPORT_PREFIX = "eval/chat_logs/turn_logs"
    DEFAULT_EXPORT_BUCKET = os.getenv("S3_DATA_BUCKET", "codingrabbit-data-dev")
    DEFAULT_EXPORT_CONNECT_TIMEOUT_SECONDS = 3


def _connect_postgres(database_url: str, connect_timeout_seconds: int):
    """Open Aurora export connections with the reliable retry profile."""
    return connect_postgres_with_retry(
        database_url,
        profile="reliable",
        connect_timeout_seconds=connect_timeout_seconds,
    )


def _parse_date(value: str | None, *, default: date | None = None) -> date:
    if value is None:
        if default is None:
            raise ValueError("A default date is required when value is omitted.")
        return default
    return date.fromisoformat(value)


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 URI: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _coerce_utc_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_snapshot(snapshot: Any) -> dict[str, Any]:
    if isinstance(snapshot, dict):
        return dict(snapshot)
    if isinstance(snapshot, (bytes, bytearray, memoryview)):
        snapshot = bytes(snapshot).decode("utf-8")
    if isinstance(snapshot, str):
        return json.loads(snapshot)
    raise TypeError(f"Unsupported snapshot payload type: {type(snapshot)!r}")


def _build_export_key(
    prefix: str,
    export_date: date,
    *,
    course_id: str | None = None,
) -> str:
    parts = [part.strip("/") for part in prefix.split("/") if part.strip("/")]
    if course_id:
        parts.append(f"course_id={course_id}")
    parts.append(f"date={export_date.isoformat()}")
    parts.append("turn_snapshots.jsonl")
    return "/".join(parts)


def _build_jsonl(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    return "\n".join(json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records) + "\n"


def _query_turn_snapshots(
    database_url: str,
    *,
    start_at: datetime,
    end_at: datetime,
    course_id: str | None = None,
    connect_timeout_seconds: int = 3,
) -> list[tuple[datetime, dict[str, Any]]]:
    """Fetch snapshots from Aurora for a UTC time window."""
    if course_id is None:
        sql = """
            SELECT
              created_at,
              snapshot
            FROM tutor_turn_snapshots
            WHERE created_at >= %s
              AND created_at < %s
            ORDER BY created_at ASC, session_id ASC, turn_index ASC, turn_id ASC
        """
        params: tuple[datetime, datetime] = (start_at, end_at)
    else:
        sql = """
            SELECT
              created_at,
              snapshot
            FROM tutor_turn_snapshots
            WHERE created_at >= %s
              AND created_at < %s
              AND course_id = %s
            ORDER BY created_at ASC, session_id ASC, turn_index ASC, turn_id ASC
        """
        params = (start_at, end_at, course_id)
    try:
        with _connect_postgres(database_url, connect_timeout_seconds) as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
    except Exception as exc:
        logger.warning("Aurora chat log export query failed: %s", exc)
        raise RuntimeError("Aurora chat log export query failed") from exc

    normalized: list[tuple[datetime, dict[str, Any]]] = []
    for row in rows:
        created_at = row[0] if isinstance(row, tuple) else row["created_at"]
        snapshot = row[1] if isinstance(row, tuple) else row["snapshot"]
        normalized.append((_coerce_utc_datetime(created_at), _normalize_snapshot(snapshot)))
    return normalized


@dataclass(frozen=True)
class ExportPartition:
    export_date: date
    record_count: int
    bucket: str
    key: str

    @property
    def s3_uri(self) -> str:
        return f"s3://{self.bucket}/{self.key}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "date": self.export_date.isoformat(),
            "record_count": self.record_count,
            "bucket": self.bucket,
            "key": self.key,
            "s3_uri": self.s3_uri,
        }


def export_turn_snapshots_to_s3(
    *,
    database_url: str,
    bucket: str | None = None,
    prefix: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    course_id: str | None = None,
    profile: str | None = None,
    region: str | None = None,
    connect_timeout_seconds: int | None = None,
    tz: str = "America/Los_Angeles",
) -> list[dict[str, Any]]:
    """Export one JSONL object per UTC date partition to S3."""
    if bucket is None:
        bucket = DEFAULT_EXPORT_BUCKET or os.getenv("S3_DATA_BUCKET", "")
    if not bucket:
        raise ValueError("A bucket is required for turn snapshot exports")
    if prefix is None:
        prefix = DEFAULT_EXPORT_PREFIX
    if connect_timeout_seconds is None:
        connect_timeout_seconds = DEFAULT_EXPORT_CONNECT_TIMEOUT_SECONDS

    import pytz
    pt_tz = pytz.timezone(tz)

    if start_date is None:
        start_date = datetime.now(pt_tz).date()
    if end_date is None:
        end_date = start_date
    if start_date > end_date:
        raise ValueError("start_date must be on or before end_date")

    start_at = datetime.combine(start_date, time.min, tzinfo=pt_tz)
    end_at = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=pt_tz)
    rows = _query_turn_snapshots(
        database_url,
        start_at=start_at,
        end_at=end_at,
        course_id=course_id,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    if not rows:
        return []

    grouped: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
    for created_at, snapshot in rows:
        c_id = snapshot.get("course", {}).get("course_id") or "unknown_course"
        grouped[(c_id, created_at.date())].append(snapshot)

    session_kwargs: dict[str, str] = {}
    if profile:
        session_kwargs["profile_name"] = profile
    if region:
        session_kwargs["region_name"] = region
    client = boto3.Session(**session_kwargs).client("s3")

    exported: list[dict[str, Any]] = []
    for (c_id, export_date) in sorted(grouped.keys()):
        records = grouped[(c_id, export_date)]
        key = _build_export_key(prefix, export_date, course_id=c_id)
        body = _build_jsonl(records)
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body.encode("utf-8"),
            ContentType="application/x-ndjson",
        )
        partition = ExportPartition(
            export_date=export_date,
            record_count=len(records),
            bucket=bucket,
            key=key,
        )
        exported.append(partition.as_dict())
        logger.info(
            "Exported %s turn snapshots to %s",
            partition.record_count,
            partition.s3_uri,
        )

    return exported


def _resolve_database_url(explicit: str | None) -> str | None:
    return explicit or os.getenv("COURSE_REGISTRY_DATABASE_URL") or os.getenv("DATABASE_URL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export canonical turn snapshots from Aurora to S3 JSONL."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Aurora/PostgreSQL URL override for the snapshot export query.",
    )
    parser.add_argument(
        "--bucket",
        default=DEFAULT_EXPORT_BUCKET or None,
        help="S3 bucket that will receive the exported JSONL files.",
    )
    parser.add_argument(
        "--prefix",
        default=DEFAULT_EXPORT_PREFIX,
        help="S3 prefix under the bucket for exported turn logs.",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="UTC start date in YYYY-MM-DD format (defaults to today).",
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="UTC end date in YYYY-MM-DD format (defaults to start-date).",
    )
    parser.add_argument(
        "--course-id",
        default=None,
        help="Optional course ID filter for the export window.",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE"),
        help="AWS profile used for the S3 upload.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        help="AWS region used for the S3 upload.",
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=int,
        default=DEFAULT_EXPORT_CONNECT_TIMEOUT_SECONDS,
        help="psycopg connect timeout for the Aurora query.",
    )
    args = parser.parse_args(argv)

    database_url = _resolve_database_url(args.database_url)
    if not database_url:
        parser.error("export-turn-snapshots requires --database-url or a configured Aurora URL")

    bucket = args.bucket or DEFAULT_EXPORT_BUCKET or os.getenv("S3_DATA_BUCKET")
    if not bucket:
        parser.error("export-turn-snapshots requires --bucket or a configured S3 bucket")

    import pytz
    pt_tz = pytz.timezone('America/Los_Angeles')
    start_date = _parse_date(args.start_date, default=datetime.now(pt_tz).date())
    end_date = _parse_date(args.end_date, default=start_date)

    exported = export_turn_snapshots_to_s3(
        database_url=database_url,
        bucket=bucket,
        prefix=args.prefix,
        start_date=start_date,
        end_date=end_date,
        course_id=args.course_id,
        profile=args.profile,
        region=args.region,
        connect_timeout_seconds=args.connect_timeout_seconds,
    )

    print(json.dumps(exported, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
