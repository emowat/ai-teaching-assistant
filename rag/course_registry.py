"""Course routing registry for the RAG pipeline.

This module centralizes course-to-collection resolution so the retrieval layer
does not hard-code collection decisions. The default implementation is still
config-driven and local, but it provides the seam we will later replace with an
Aurora-backed registry.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from functools import lru_cache

from rag.runtime import RagRuntimeConfig, get_runtime_config
from rag.schemas import CourseSource, QueryInput


logger = logging.getLogger(__name__)


def _normalize_course_id(course_id: str) -> str:
    """Normalize course IDs so punctuation and spacing do not matter."""
    return "".join(ch for ch in course_id.casefold() if ch.isalnum())


def _parse_course_source(course_source: object) -> CourseSource:
    """Coerce a database value into the CourseSource enum."""
    try:
        return CourseSource(str(course_source))
    except ValueError as exc:
        raise ValueError(f"Unsupported course_source value: {course_source}") from exc


def _connect_postgres(database_url: str):
    """Create a psycopg connection lazily so local tests do not need the dependency."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - exercised only when dependency missing
        raise RuntimeError(
            "psycopg is required for the Aurora-backed course registry."
        ) from exc

    return psycopg.connect(database_url, connect_timeout=5)


@dataclass(frozen=True)
class CourseRoute:
    """Resolved course metadata used by retrieval and tracing."""

    course_id: str
    course_source: CourseSource
    collection_name: str


@dataclass(frozen=True)
class CourseDef:
    """Full course definition including content policy fields."""

    course_id: str
    course_source: CourseSource
    collection_name: str
    syllabus_matrix: str | None = None
    style_guide: str | None = None


@dataclass(frozen=True)
class CourseRegistryStatus:
    """Health information for the Aurora-backed course registry."""

    configured: bool
    reachable: bool
    message: str = ""


class CourseRegistry:
    """Resolve course IDs to the active retrieval collection."""

    def __init__(
        self,
        runtime: RagRuntimeConfig | object | None = None,
        *,
        database_url: str | None = None,
    ):
        self._runtime = runtime or get_runtime_config()
        self._routes = self._build_routes(self._runtime)
        self._course_defs: dict[str, CourseDef] = {}
        if database_url:
            try:
                database_routes, database_defs = _load_database_routes(database_url)
            except Exception as exc:
                logger.warning(
                    "Aurora course registry unavailable; using static fallback: %s",
                    exc,
                )
            else:
                if database_routes:
                    self._routes.update(database_routes)
                    self._course_defs.update(database_defs)
                else:
                    logger.warning(
                        "Aurora course registry returned no rows; using static fallback."
                    )

    @staticmethod
    def _build_routes(runtime: RagRuntimeConfig | object) -> dict[str, CourseRoute]:
        routes: dict[str, CourseRoute] = {
            "mit13": CourseRoute(
                course_id="mit13",
                course_source=CourseSource.MIT_13,
                collection_name=runtime.collection_mit13,
            ),
            "mit14": CourseRoute(
                course_id="mit14",
                course_source=CourseSource.MIT_14,
                collection_name=runtime.collection_mit14,
            ),
            "cs50": CourseRoute(
                course_id="cs50",
                course_source=CourseSource.CS50,
                collection_name=runtime.collection_cs50,
            ),
        }

        aliases = {
            "mit": "mit13",
            "mit_13": "mit13",
            "mit-13": "mit13",
            "mit_14": "mit14",
            "mit-14": "mit14",
            "harvard": "cs50",
            "harvardcs50": "cs50",
            "harvard-cs50": "cs50",
            "cs50x": "cs50",
        }

        for alias, canonical in aliases.items():
            routes[_normalize_course_id(alias)] = routes[canonical]
        return routes

    def resolve(
        self,
        *,
        course_id: str | None = None,
        course_source: CourseSource | None = None,
    ) -> CourseRoute:
        """Resolve the active route, preferring an explicit course_id."""
        if course_id:
            normalized = _normalize_course_id(course_id)
            route = self._routes.get(normalized)
            if route is None:
                raise ValueError(f"Unsupported course_id: {course_id}")
            return route

        if course_source is None:
            raise ValueError("course_source is required when course_id is missing.")

        for route in self._routes.values():
            if route.course_source == course_source:
                return route

        raise ValueError(f"Unsupported course_source: {course_source}")

    def get_course(self, course_id: str) -> CourseDef | None:
        """Return the full course definition including style_guide and syllabus_matrix.

        Loaded once at startup from the DB — no per-request DB connections.
        """
        normalized = _normalize_course_id(course_id)
        # Return the full CourseDef if we loaded it from the DB at startup
        if normalized in self._course_defs:
            return self._course_defs[normalized]
        # Fall back to route-only (no policy fields) if DB wasn't available
        route = self._routes.get(normalized)
        if route is None:
            return None
        return CourseDef(
            course_id=route.course_id,
            course_source=route.course_source,
            collection_name=route.collection_name,
        )



def _load_database_routes(
    database_url: str,
) -> tuple[dict[str, CourseRoute], dict[str, CourseDef]]:
    """Load canonical course routes, aliases, and policy fields from Aurora/PostgreSQL.

    Returns two dicts keyed by normalized course_id:
    - routes: CourseRoute (collection routing only)
    - defs:   CourseDef  (full definition including style_guide + syllabus_matrix)
    """
    routes: dict[str, CourseRoute] = {}
    defs: dict[str, CourseDef] = {}

    with _connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT course_id, course_source, collection_name,
                       syllabus_matrix, style_guide
                FROM courses
                WHERE is_active = TRUE
                ORDER BY course_id
                """
            )
            course_rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT alias, course_id
                FROM course_aliases
                WHERE is_active = TRUE
                ORDER BY alias
                """
            )
            alias_rows = cursor.fetchall()

    for row in course_rows:
        course_id, course_source, collection_name, syllabus_matrix, style_guide = row[:5]
        course_id = str(course_id)
        route = CourseRoute(
            course_id=course_id,
            course_source=_parse_course_source(course_source),
            collection_name=str(collection_name),
        )
        definition = CourseDef(
            course_id=course_id,
            course_source=route.course_source,
            collection_name=route.collection_name,
            syllabus_matrix=str(syllabus_matrix) if syllabus_matrix else None,
            style_guide=str(style_guide) if style_guide else None,
        )
        key = _normalize_course_id(course_id)
        routes[key] = route
        defs[key] = definition
        logger.debug(
            "Loaded course %s: style_guide=%s, syllabus_matrix=%s",
            course_id,
            "present" if style_guide else "missing",
            "present" if syllabus_matrix else "missing",
        )

    for row in alias_rows:
        alias, canonical_course_id = row[:2]
        canonical_key = _normalize_course_id(str(canonical_course_id))
        canonical_route = routes.get(canonical_key)
        if canonical_route is None:
            logger.warning(
                "Skipping course alias %s because canonical course %s was not loaded.",
                alias,
                canonical_course_id,
            )
            continue
        alias_key = _normalize_course_id(str(alias))
        routes[alias_key] = canonical_route
        if canonical_key in defs:
            defs[alias_key] = defs[canonical_key]

    return routes, defs


def get_course_registry_status(
    database_url: str | None = None,
) -> CourseRegistryStatus:
    """Probe the course registry database without relying on the cached registry.

    This keeps local fallback behavior intact while letting `/health` report
    whether the AWS runtime can actually reach the Aurora-backed registry.
    """
    resolved_url = database_url or (
        os.getenv("COURSE_REGISTRY_DATABASE_URL") or os.getenv("DATABASE_URL")
    )
    if not resolved_url:
        return CourseRegistryStatus(
            configured=False,
            reachable=False,
            message="Aurora course registry is not configured; using local fallback.",
        )

    try:
        with _connect_postgres(resolved_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM courses WHERE is_active = TRUE"
                )
                active_course_count = int(cursor.fetchone()[0] or 0)
    except Exception as exc:
        return CourseRegistryStatus(
            configured=True,
            reachable=False,
            message=f"Aurora course registry connectivity check failed: {exc}",
        )

    if active_course_count <= 0:
        return CourseRegistryStatus(
            configured=True,
            reachable=True,
            message="Aurora course registry is reachable but has no active courses.",
        )

    return CourseRegistryStatus(
        configured=True,
        reachable=True,
        message=f"Aurora course registry is reachable with {active_course_count} active course(s).",
    )


@lru_cache(maxsize=1)
def get_course_registry() -> CourseRegistry:
    """Return the cached default registry."""
    database_url = (
        os.getenv("COURSE_REGISTRY_DATABASE_URL")
        or os.getenv("DATABASE_URL")
    )
    return CourseRegistry(
        get_runtime_config(),
        database_url=database_url,
    )


def resolve_course_route(query: QueryInput) -> CourseRoute:
    """Resolve the active course route from the user query."""
    return get_course_registry().resolve(
        course_id=query.course_id,
        course_source=query.course_source,
    )
