"""CLI entrypoints for idempotent Qdrant indexing and course routing smoke tests."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date

from rag.course_registry import CourseRegistry
from rag.course_registry import get_course_registry
from rag.runtime import get_runtime_config
from rag.schemas import CourseSource

from rag_eng.chat_log_export import DEFAULT_EXPORT_PREFIX
from rag_eng.chat_log_export import DEFAULT_EXPORT_BUCKET
from rag_eng.chat_log_export import DEFAULT_EXPORT_CONNECT_TIMEOUT_SECONDS
from rag_eng.chat_log_export import export_turn_snapshots_to_s3
from rag_eng.indexing import ensure_index, rebuild_index


def _course_route_payload(route) -> dict[str, str]:
    return {
        "course_id": route.course_id,
        "course_source": route.course_source.value,
        "collection_name": route.collection_name,
    }


def _result_payload(result: object) -> object:
    if isinstance(result, list):
        return [_result_payload(item) for item in result]
    if isinstance(result, dict):
        return result
    return result.__dict__


def main(argv: list[str] | None = None) -> None:
    """Parse CLI arguments and run the selected command."""
    parser = argparse.ArgumentParser(description="rag_eng indexing utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "ensure-index", help="Create the index if missing and upsert documents."
    )
    subparsers.add_parser("rebuild-index", help="Delete and rebuild the entire index.")
    export_turn_snapshots = subparsers.add_parser(
        "export-turn-snapshots",
        help="Export Aurora turn snapshots to S3 JSONL partitions.",
    )
    export_turn_snapshots.add_argument(
        "--database-url",
        default=None,
        help="Aurora/PostgreSQL URL override for the export query.",
    )
    export_turn_snapshots.add_argument(
        "--bucket",
        default=DEFAULT_EXPORT_BUCKET or None,
        help="S3 bucket that will receive the exported JSONL files.",
    )
    export_turn_snapshots.add_argument(
        "--prefix",
        default=DEFAULT_EXPORT_PREFIX,
        help="S3 prefix under the bucket for exported turn logs.",
    )
    export_turn_snapshots.add_argument(
        "--start-date",
        default=None,
        help="UTC start date in YYYY-MM-DD format (defaults to today).",
    )
    export_turn_snapshots.add_argument(
        "--end-date",
        default=None,
        help="UTC end date in YYYY-MM-DD format (defaults to start-date).",
    )
    export_turn_snapshots.add_argument(
        "--course-id",
        default=None,
        help="Optional course ID filter for the export window.",
    )
    export_turn_snapshots.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE"),
        help="AWS profile used for the S3 upload.",
    )
    export_turn_snapshots.add_argument(
        "--region",
        default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        help="AWS region used for the S3 upload.",
    )
    export_turn_snapshots.add_argument(
        "--connect-timeout-seconds",
        type=int,
        default=DEFAULT_EXPORT_CONNECT_TIMEOUT_SECONDS,
        help="psycopg connect timeout for the Aurora query.",
    )
    resolve_course = subparsers.add_parser(
        "resolve-course",
        help="Resolve a course ID or legacy course source to the active collection.",
    )
    resolve_course.add_argument(
        "--course-id",
        default=None,
        help="Explicit course ID to resolve (preferred).",
    )
    resolve_course.add_argument(
        "--course-source",
        choices=[source.value for source in CourseSource],
        default=None,
        help="Legacy course source fallback for compatibility.",
    )
    resolve_course.add_argument(
        "--database-url",
        default=None,
        help="Optional PostgreSQL URL override for Aurora-backed registry lookup.",
    )

    args = parser.parse_args(argv)
    if args.command == "ensure-index":
        result = ensure_index()
    elif args.command == "rebuild-index":
        result = rebuild_index()
    elif args.command == "export-turn-snapshots":
        bucket = args.bucket or DEFAULT_EXPORT_BUCKET or os.getenv("S3_DATA_BUCKET")
        if not bucket:
            parser.error(
                "export-turn-snapshots requires --bucket or a configured S3 bucket"
            )
        result = export_turn_snapshots_to_s3(
            database_url=args.database_url,
            bucket=bucket,
            prefix=args.prefix or DEFAULT_EXPORT_PREFIX,
            start_date=date.fromisoformat(args.start_date)
            if args.start_date
            else None,
            end_date=date.fromisoformat(args.end_date) if args.end_date else None,
            course_id=args.course_id,
            profile=args.profile,
            region=args.region,
            connect_timeout_seconds=args.connect_timeout_seconds,
        )
    else:
        if not args.course_id and not args.course_source:
            parser.error("resolve-course requires --course-id or --course-source")

        registry = (
            CourseRegistry(get_runtime_config(), database_url=args.database_url)
            if args.database_url
            else get_course_registry()
        )
        route = registry.resolve(
            course_id=args.course_id,
            course_source=CourseSource(args.course_source)
            if args.course_source
            else None,
        )
        result = _course_route_payload(route)

    print(json.dumps(_result_payload(result), indent=2))


if __name__ == "__main__":
    main()
