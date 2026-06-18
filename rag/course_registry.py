"""Course routing registry for the RAG pipeline.

This module centralizes course-to-collection resolution so the retrieval layer
does not hard-code collection decisions. The default implementation is still
config-driven and local, but it provides the seam we will later replace with an
Aurora-backed registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rag.runtime import RagRuntimeConfig, get_runtime_config
from rag.schemas import CourseSource, QueryInput


def _normalize_course_id(course_id: str) -> str:
    """Normalize course IDs so punctuation and spacing do not matter."""
    return "".join(ch for ch in course_id.casefold() if ch.isalnum())


@dataclass(frozen=True)
class CourseRoute:
    """Resolved course metadata used by retrieval and tracing."""

    course_id: str
    course_source: CourseSource
    collection_name: str


class CourseRegistry:
    """Resolve course IDs to the active retrieval collection."""

    def __init__(self, runtime: RagRuntimeConfig):
        self._runtime = runtime
        self._routes = self._build_routes(runtime)

    @staticmethod
    def _build_routes(runtime: RagRuntimeConfig) -> dict[str, CourseRoute]:
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


@lru_cache(maxsize=1)
def get_course_registry() -> CourseRegistry:
    """Return the cached default registry."""
    return CourseRegistry(get_runtime_config())


def resolve_course_route(query: QueryInput) -> CourseRoute:
    """Resolve the active course route from the user query."""
    return get_course_registry().resolve(
        course_id=query.course_id,
        course_source=query.course_source,
    )
