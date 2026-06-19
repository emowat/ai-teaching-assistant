"""CLI entrypoints for idempotent Qdrant indexing and course routing smoke tests."""

from __future__ import annotations

import argparse
import json

from rag.course_registry import CourseRegistry
from rag.course_registry import get_course_registry
from rag.runtime import get_runtime_config
from rag.schemas import CourseSource

from rag_eng.indexing import ensure_index, rebuild_index


def _course_route_payload(route) -> dict[str, str]:
    return {
        "course_id": route.course_id,
        "course_source": route.course_source.value,
        "collection_name": route.collection_name,
    }


def _result_payload(result: object) -> object:
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
