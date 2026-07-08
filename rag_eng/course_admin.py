"""Aurora-backed course admin helpers for the `rag_eng` service."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from dotenv import load_dotenv

from rag.course_registry import get_course_registry
from rag.schemas import CourseSource
from rag_eng.schemas import (
    AdminCourse,
    AdminCourseAliasCreate,
    AdminCourseCreate,
    AdminCourseUpdate,
)


load_dotenv()

_SAFE_COLLECTION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class CourseAdminError(RuntimeError):
    """Base class for course admin write/read errors."""


class CourseNotFoundError(LookupError):
    """Raised when an admin course or alias cannot be found."""


class CourseConflictError(CourseAdminError):
    """Raised when a course, alias, or collection name collides."""


@dataclass(frozen=True)
class CourseAdminRuntimeConfig:
    """Runtime settings for the Aurora-backed course admin helpers."""

    database_url: str | None
    connect_timeout_seconds: int


@dataclass(frozen=True)
class _CourseState:
    courses_by_id: dict[str, dict[str, Any]]
    aliases_by_course: dict[str, list[str]]
    course_ids_by_normalized: dict[str, str]
    aliases_by_normalized: dict[str, dict[str, Any]]
    ingestion_history_by_course: dict[str, bool]


def _normalize_course_key(value: str) -> str:
    return "".join(ch for ch in value.casefold() if ch.isalnum())


def _format_timestamp(value: object | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _clean_required_text(value: object, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required.")
    return cleaned


def _validate_collection_name(value: object) -> str:
    cleaned = _clean_required_text(value, "collection_name")
    if not _SAFE_COLLECTION_NAME_RE.fullmatch(cleaned):
        raise ValueError(
            "collection_name may contain only letters, numbers, underscores, and hyphens."
        )
    return cleaned


def _validate_course_source(value: object) -> CourseSource:
    try:
        raw_value = getattr(value, "value", value)
        return CourseSource(str(raw_value))
    except ValueError as exc:
        raise ValueError(f"Unsupported course_source value: {value}") from exc


def _validate_json_string(value: str | None, field_name: str) -> str | None:
    if not value or not value.strip():
        return None
    import json
    try:
        json.loads(value)
        return value.strip()
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON: {exc}") from exc


def _dedupe_aliases(aliases: list[str], course_id: str) -> list[str]:
    seen: set[str] = set()
    cleaned_aliases: list[str] = []

    for alias in aliases:
        cleaned = _clean_required_text(alias, "alias")
        alias_key = _normalize_course_key(cleaned)
        if alias_key in seen:
            continue
        seen.add(alias_key)
        cleaned_aliases.append(cleaned)

    return cleaned_aliases


def _connect_postgres(database_url: str, connect_timeout_seconds: int):
    """Create a psycopg connection lazily so tests can stub the helper."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised only when missing
        raise RuntimeError("psycopg is required for course admin operations.") from exc

    return psycopg.connect(database_url, connect_timeout=connect_timeout_seconds)


def load_course_admin_runtime_config(
    env: Mapping[str, str] | None = None,
) -> CourseAdminRuntimeConfig:
    """Load Aurora course-admin settings from the process environment."""
    source = env or os.environ
    return CourseAdminRuntimeConfig(
        database_url=(
            source.get("COURSE_REGISTRY_DATABASE_URL")
            or source.get("DATABASE_URL")
        ),
        connect_timeout_seconds=int(
            source.get(
                "COURSE_REGISTRY_CONNECT_TIMEOUT_SECONDS",
                source.get("INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS", "5"),
            )
        ),
    )


def _load_course_state(connection) -> _CourseState:
    """Load all courses and aliases needed for course admin validation."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              course_id,
              course_source,
              collection_name,
              display_name,
              is_active,
              syllabus_matrix,
              style_guide,
              created_at,
              updated_at
            FROM courses
            ORDER BY course_id
            """
        )
        course_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT
              alias,
              course_id,
              is_active
            FROM course_aliases
            ORDER BY alias
            """
        )
        alias_rows = cursor.fetchall()
        cursor.execute(
            """
            SELECT course_id, COUNT(*)
            FROM course_corpus_versions
            GROUP BY course_id
            """
        )
        history_rows = cursor.fetchall()

    courses_by_id: dict[str, dict[str, Any]] = {}
    aliases_by_course: dict[str, list[str]] = defaultdict(list)
    course_ids_by_normalized: dict[str, str] = {}
    aliases_by_normalized: dict[str, dict[str, Any]] = {}
    ingestion_history_by_course: dict[str, bool] = {}

    for row in course_rows:
        stored_course_id = str(row[0])
        courses_by_id[stored_course_id] = {
            "course_id": stored_course_id,
            "course_source": _validate_course_source(row[1]),
            "collection_name": str(row[2]),
            "display_name": str(row[3] or ""),
            "is_active": bool(row[4]),
            "syllabus_matrix": row[5],
            "style_guide": row[6],
            "created_at": _format_timestamp(row[7]),
            "updated_at": _format_timestamp(row[8]),
            "has_ingestion_history": False,
        }
        course_ids_by_normalized[_normalize_course_key(stored_course_id)] = stored_course_id

    for row in alias_rows:
        alias, course_id, is_active = row[:3]
        stored_alias = str(alias)
        stored_course_id = str(course_id)
        normalized_alias = _normalize_course_key(stored_alias)
        aliases_by_normalized[normalized_alias] = {
            "alias": stored_alias,
            "course_id": stored_course_id,
            "is_active": bool(is_active),
        }
        if bool(is_active) and stored_course_id in courses_by_id:
            aliases_by_course[stored_course_id].append(stored_alias)

    for row in history_rows:
        course_id, count = row[:2]
        has_history = int(count or 0) > 0
        course_key = str(course_id)
        ingestion_history_by_course[course_key] = has_history
        if course_key in courses_by_id:
            courses_by_id[course_key]["has_ingestion_history"] = has_history

    return _CourseState(
        courses_by_id=courses_by_id,
        aliases_by_course=aliases_by_course,
        course_ids_by_normalized=course_ids_by_normalized,
        aliases_by_normalized=aliases_by_normalized,
        ingestion_history_by_course=ingestion_history_by_course,
    )


def _state_to_course(course_data: dict[str, Any], aliases: list[str]) -> AdminCourse:
    return AdminCourse(
        course_id=course_data["course_id"],
        display_name=course_data["display_name"],
        course_source=course_data["course_source"],
        collection_name=course_data["collection_name"],
        is_active=course_data["is_active"],
        has_ingestion_history=course_data.get("has_ingestion_history", False),
        aliases=sorted(aliases),
        syllabus_matrix=course_data.get("syllabus_matrix"),
        style_guide=course_data.get("style_guide"),
        created_at=_format_timestamp(course_data["created_at"]),
        updated_at=_format_timestamp(course_data["updated_at"]),
    )


def _state_to_courses(state: _CourseState) -> list[AdminCourse]:
    courses: list[AdminCourse] = []
    for course_id in sorted(state.courses_by_id):
        course_data = state.courses_by_id[course_id]
        aliases = state.aliases_by_course.get(course_id, [])
        courses.append(_state_to_course(course_data, aliases))
    return courses


def _fetch_admin_course(connection, course_id: str) -> AdminCourse:
    """Fetch a single admin course using the current connection state."""
    state = _load_course_state(connection)
    course_data = _require_course_exists(state, course_id)
    aliases = state.aliases_by_course.get(course_id, [])
    return _state_to_course(course_data, aliases)


def _require_course_exists(state: _CourseState, course_id: str) -> dict[str, Any]:
    course = state.courses_by_id.get(course_id)
    if course is None:
        raise CourseNotFoundError(f"Course not found: {course_id}")
    return course


def _validate_alias_collisions(
    state: _CourseState,
    *,
    course_id: str,
    aliases: list[str],
) -> None:
    for alias in aliases:
        alias_key = _normalize_course_key(alias)
        course_owner = state.course_ids_by_normalized.get(alias_key)
        if course_owner is not None and course_owner != course_id:
            raise CourseConflictError(f"Alias already belongs to course {course_owner}.")

        alias_owner = state.aliases_by_normalized.get(alias_key)
        if alias_owner is not None and alias_owner["course_id"] != course_id:
            raise CourseConflictError(
                f"Alias already belongs to course {alias_owner['course_id']}."
            )


def _clear_course_registry_cache() -> None:
    get_course_registry.cache_clear()


def _resolve_course_row(connection, course_id: str) -> tuple[Any, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              course_id,
              course_source,
              collection_name,
              display_name,
              is_active,
              syllabus_matrix,
              style_guide,
              created_at,
              updated_at
            FROM courses
            WHERE course_id = %s
            """,
            (course_id,),
        )
        row = cursor.fetchone()
    if row is None:
        raise CourseNotFoundError(f"Course not found: {course_id}")
    return row


def _resolve_course_alias_row(connection, alias: str) -> tuple[Any, ...]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              alias,
              course_id,
              is_active
            FROM course_aliases
            WHERE alias = %s
            """,
            (alias,),
        )
        row = cursor.fetchone()
    if row is None:
        raise CourseNotFoundError(f"Alias not found: {alias}")
    return row


def list_admin_courses(
    runtime: CourseAdminRuntimeConfig | None = None,
) -> list[AdminCourse]:
    """Return all courses and active aliases for the admin dashboard."""
    runtime = runtime or load_course_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        state = _load_course_state(connection)
    return _state_to_courses(state)


def get_admin_course(
    course_id: str,
    runtime: CourseAdminRuntimeConfig | None = None,
) -> AdminCourse:
    """Return a single course and its active aliases."""
    runtime = runtime or load_course_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    cleaned_course_id = _clean_required_text(course_id, "course_id")
    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        return _fetch_admin_course(connection, cleaned_course_id)


def create_admin_course(
    payload: AdminCourseCreate,
    runtime: CourseAdminRuntimeConfig | None = None,
) -> AdminCourse:
    """Create a new course and optional aliases."""
    runtime = runtime or load_course_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    cleaned_course_id = _clean_required_text(payload.course_id, "course_id")
    display_name = _clean_required_text(payload.display_name, "display_name")
    collection_name = _validate_collection_name(payload.collection_name)
    course_source = _validate_course_source(payload.course_source)
    aliases = _dedupe_aliases(payload.aliases, cleaned_course_id)
    syllabus_matrix = _validate_json_string(payload.syllabus_matrix, "syllabus_matrix")
    style_guide = payload.style_guide.strip() if payload.style_guide else None

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        state = _load_course_state(connection)
        if cleaned_course_id in state.courses_by_id:
            raise CourseConflictError(f"Course already exists: {cleaned_course_id}")
        _validate_alias_collisions(
            state,
            course_id=cleaned_course_id,
            aliases=aliases,
        )

        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO courses (
                    course_id, course_source, collection_name, display_name, is_active, syllabus_matrix, style_guide
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    cleaned_course_id,
                    course_source.value,
                    collection_name,
                    display_name,
                    payload.is_active,
                    syllabus_matrix,
                    style_guide,
                ),
            )
            for alias in aliases:
                cursor.execute(
                    """
                    INSERT INTO course_aliases (
                      alias,
                      course_id,
                      is_active
                    )
                    VALUES (%s, %s, TRUE)
                    """,
                    (alias, cleaned_course_id),
                )

        created = _fetch_admin_course(connection, cleaned_course_id)

    _clear_course_registry_cache()
    return created


def update_admin_course(
    course_id: str,
    payload: AdminCourseUpdate,
    runtime: CourseAdminRuntimeConfig | None = None,
) -> AdminCourse:
    """Update mutable course fields and return the refreshed course."""
    runtime = runtime or load_course_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    cleaned_course_id = _clean_required_text(course_id, "course_id")
    updates: list[str] = []
    values: list[Any] = []

    if payload.display_name is not None:
        updates.append("display_name = %s")
        values.append(_clean_required_text(payload.display_name, "display_name"))
    if payload.course_source is not None:
        updates.append("course_source = %s")
        values.append(_validate_course_source(payload.course_source).value)
    if payload.collection_name is not None:
        updates.append("collection_name = %s")
        values.append(_validate_collection_name(payload.collection_name))
    if payload.is_active is not None:
        updates.append("is_active = %s")
        values.append(payload.is_active)
    if payload.syllabus_matrix is not None:
        updates.append("syllabus_matrix = %s")
        values.append(_validate_json_string(payload.syllabus_matrix, "syllabus_matrix"))
    if payload.style_guide is not None:
        updates.append("style_guide = %s")
        values.append(payload.style_guide.strip() if payload.style_guide.strip() else None)

    if not updates:
        raise ValueError("At least one course field must be provided.")

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        _resolve_course_row(connection, cleaned_course_id)
        set_clause = ", ".join(updates)
        params = tuple(values) + (cleaned_course_id,)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE courses
                SET {set_clause},
                    updated_at = now()
                WHERE course_id = %s
                """,
                params,
            )
        updated = _fetch_admin_course(connection, cleaned_course_id)

    _clear_course_registry_cache()
    return updated


def add_admin_course_aliases(
    course_id: str,
    payload: AdminCourseAliasCreate,
    runtime: CourseAdminRuntimeConfig | None = None,
) -> AdminCourse:
    """Add or reactivate aliases for an existing course."""
    runtime = runtime or load_course_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    cleaned_course_id = _clean_required_text(course_id, "course_id")
    aliases = _dedupe_aliases(payload.aliases, cleaned_course_id)

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        _resolve_course_row(connection, cleaned_course_id)
        state = _load_course_state(connection)
        _validate_alias_collisions(
            state,
            course_id=cleaned_course_id,
            aliases=aliases,
        )

        with connection.cursor() as cursor:
            for alias in aliases:
                alias_row = state.aliases_by_normalized.get(_normalize_course_key(alias))
                if alias_row is not None and alias_row["course_id"] == cleaned_course_id:
                    cursor.execute(
                        """
                        UPDATE course_aliases
                        SET is_active = TRUE,
                            updated_at = now()
                        WHERE alias = %s
                        """,
                        (alias_row["alias"],),
                    )
                    continue

                cursor.execute(
                    """
                    INSERT INTO course_aliases (
                      alias,
                      course_id,
                      is_active
                    )
                    VALUES (%s, %s, TRUE)
                    """,
                    (alias, cleaned_course_id),
                )

        updated = _fetch_admin_course(connection, cleaned_course_id)

    _clear_course_registry_cache()
    return updated


def deactivate_admin_course_alias(
    course_id: str,
    alias: str,
    runtime: CourseAdminRuntimeConfig | None = None,
) -> AdminCourse:
    """Deactivate an alias that belongs to the given course."""
    runtime = runtime or load_course_admin_runtime_config()
    if not runtime.database_url:
        raise RuntimeError("Course registry database URL is not configured.")

    cleaned_course_id = _clean_required_text(course_id, "course_id")
    cleaned_alias = _clean_required_text(alias, "alias")

    with _connect_postgres(
        runtime.database_url,
        runtime.connect_timeout_seconds,
    ) as connection:
        _resolve_course_row(connection, cleaned_course_id)
        alias_row = _resolve_course_alias_row(connection, cleaned_alias)
        if str(alias_row[1]) != cleaned_course_id:
            raise CourseNotFoundError(
                f"Alias {cleaned_alias} is not attached to course {cleaned_course_id}."
            )

        with connection.cursor() as cursor:
                cursor.execute(
                    """
                UPDATE course_aliases
                SET is_active = FALSE,
                    updated_at = now()
                WHERE alias = %s
                """,
                (cleaned_alias,),
            )

        updated = _fetch_admin_course(connection, cleaned_course_id)

    _clear_course_registry_cache()
    return updated
