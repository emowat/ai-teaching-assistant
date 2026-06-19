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

    return psycopg.connect(database_url)


@dataclass(frozen=True)
class CourseRoute:
    """Resolved course metadata used by retrieval and tracing."""

    course_id: str
    course_source: CourseSource
    collection_name: str


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
        if database_url:
            try:
                database_routes = _load_database_routes(database_url)
            except Exception as exc:
                logger.warning(
                    "Aurora course registry unavailable; using static fallback: %s",
                    exc,
                )
            else:
                if database_routes:
                    self._routes.update(database_routes)
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


def _load_database_routes(database_url: str) -> dict[str, CourseRoute]:
    """Load canonical course routes and aliases from Aurora/PostgreSQL."""
    routes: dict[str, CourseRoute] = {}

    with _connect_postgres(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT course_id, course_source, collection_name
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
        course_id, course_source, collection_name = row[:3]
        route = CourseRoute(
            course_id=str(course_id),
            course_source=_parse_course_source(course_source),
            collection_name=str(collection_name),
        )
        routes[_normalize_course_id(route.course_id)] = route

    for row in alias_rows:
        alias, canonical_course_id = row[:2]
        canonical_route = routes.get(_normalize_course_id(str(canonical_course_id)))
        if canonical_route is None:
            logger.warning(
                "Skipping course alias %s because canonical course %s was not loaded.",
                alias,
                canonical_course_id,
            )
            continue
        routes[_normalize_course_id(str(alias))] = canonical_route

    return routes


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
