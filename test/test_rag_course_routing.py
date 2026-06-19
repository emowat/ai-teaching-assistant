from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag.course_registry import (
    CourseRegistry,
    CourseRoute,
    _load_database_routes,
    resolve_course_route,
)
from rag.pipeline import run_retrieval
from rag.schemas import AssistMode, CourseSource, QueryInput, RetrievalResult


def _stub_retrieval_result() -> RetrievalResult:
    return RetrievalResult(formatted_context="[ctx]")


def _stub_registry() -> CourseRegistry:
    return CourseRegistry(
        SimpleNamespace(
            collection_mit13="mit13_course",
            collection_mit14="mit14_course",
            collection_cs50="cs50_course",
        )
    )


class _FakeCursor:
    def __init__(self, course_rows, alias_rows):
        self._course_rows = list(course_rows)
        self._alias_rows = list(alias_rows)
        self._call_count = 0

    def execute(self, query: str) -> None:
        self._call_count += 1

    def fetchall(self):
        if self._call_count == 1:
            return self._course_rows
        return self._alias_rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeConnection:
    def __init__(self, course_rows, alias_rows):
        self._course_rows = course_rows
        self._alias_rows = alias_rows

    def cursor(self):
        return _FakeCursor(self._course_rows, self._alias_rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_load_database_routes_uses_canonical_rows_and_aliases(monkeypatch) -> None:
    fake_connection = _FakeConnection(
        [
            ("mit13", "mit13", "mit13_course_db"),
            ("mit14", "mit14", "mit14_course_db"),
            ("cs50", "cs50", "cs50_course_db"),
        ],
        [
            ("mit-13", "mit13"),
            ("cs50x", "cs50"),
        ],
    )
    monkeypatch.setattr(
        "rag.course_registry._connect_postgres",
        lambda database_url: fake_connection,
    )

    routes = _load_database_routes("postgresql://example")

    assert routes["mit13"].collection_name == "mit13_course_db"
    assert routes["mit14"].collection_name == "mit14_course_db"
    assert routes["cs50"].collection_name == "cs50_course_db"


def test_course_registry_overlays_database_routes(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag.course_registry._load_database_routes",
        lambda database_url: {
            "mit14": CourseRoute(
                course_id="mit14",
                course_source=CourseSource.MIT_14,
                collection_name="mit14_course_db",
            )
        },
    )

    registry = CourseRegistry(
        SimpleNamespace(
            collection_mit13="mit13_course",
            collection_mit14="mit14_course",
            collection_cs50="cs50_course",
        ),
        database_url="postgresql://example",
    )

    route = registry.resolve(course_id="mit-14")

    assert route.course_source is CourseSource.MIT_14
    assert route.collection_name == "mit14_course_db"


def test_course_registry_falls_back_to_static_routes_when_aurora_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "rag.course_registry._load_database_routes",
        lambda database_url: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    registry = CourseRegistry(
        SimpleNamespace(
            collection_mit13="mit13_course",
            collection_mit14="mit14_course",
            collection_cs50="cs50_course",
        ),
        database_url="postgresql://example",
    )

    route = registry.resolve(course_id="mit-14")

    assert route.course_source is CourseSource.MIT_14
    assert route.collection_name == "mit14_course"


def test_resolve_course_route_prefers_explicit_course_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag.course_registry.get_course_registry",
        lambda: _stub_registry(),
    )

    route = resolve_course_route(
        QueryInput(
            student_message="Why does this crash?",
            week=3,
            course_id="mit-14",
            course_source=CourseSource.CS50,
        )
    )

    assert route.course_source is CourseSource.MIT_14
    assert route.collection_name == "mit14_course"


def test_resolve_course_route_falls_back_to_legacy_course_source(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag.course_registry.get_course_registry",
        lambda: _stub_registry(),
    )

    route = resolve_course_route(
        QueryInput(
            student_message="Why does this crash?",
            week=3,
            course_source=CourseSource.MIT_13,
        )
    )

    assert route.course_source is CourseSource.MIT_13
    assert route.collection_name == "mit13_course"


def test_run_retrieval_uses_registry_collection_name(monkeypatch) -> None:
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        "rag.course_registry.get_course_registry",
        lambda: _stub_registry(),
    )
    monkeypatch.setattr("rag.pipeline.build_query", lambda query: "dense query")
    monkeypatch.setattr(
        "rag.pipeline.retrieve_guidelines",
        lambda dense_query, top_k, threshold: [],
    )

    def fake_syllabus(week, *, collection_name):
        captured["syllabus_collection"] = collection_name
        return SimpleNamespace()

    def fake_semantic(dense_query, week, top_k=5, *, cumulative=False, collection_name):
        captured["semantic_collection"] = collection_name
        return []

    def fake_rules(dense_query, week, top_k=3, threshold=0.55, *, cumulative=False, collection_name):
        captured["rules_collection"] = collection_name
        return []

    monkeypatch.setattr("rag.pipeline.retrieve_syllabus", fake_syllabus)
    monkeypatch.setattr("rag.pipeline.retrieve_semantic", fake_semantic)
    monkeypatch.setattr("rag.pipeline.retrieve_strict_rules", fake_rules)
    monkeypatch.setattr(
        "rag.pipeline.retrieve_harvard",
        lambda *args, **kwargs: pytest.fail("Harvard retriever should not be used"),
    )
    monkeypatch.setattr(
        "rag.pipeline.retrieve_harvard_rules",
        lambda *args, **kwargs: pytest.fail("Harvard retriever should not be used"),
    )
    monkeypatch.setattr(
        "rag.pipeline.merge_and_rerank",
        lambda **kwargs: (None, [], [], [], []),
    )
    monkeypatch.setattr(
        "rag.pipeline.build_retrieval_result",
        lambda **kwargs: _stub_retrieval_result(),
    )

    result = run_retrieval(
        QueryInput(
            student_message="Why does this crash?",
            week=3,
            mode=AssistMode.HOMEWORK_ASSIST,
            course_id="mit14",
            course_source=CourseSource.CS50,
        )
    )

    assert result.formatted_context == "[ctx]"
    assert captured["syllabus_collection"] == "mit14_course"
    assert captured["semantic_collection"] == "mit14_course"
    assert captured["rules_collection"] == "mit14_course"


def test_run_retrieval_rejects_unknown_course_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag.course_registry.get_course_registry",
        lambda: _stub_registry(),
    )

    with pytest.raises(ValueError, match="Unsupported course_id"):
        run_retrieval(
            QueryInput(
                student_message="Why does this crash?",
                week=3,
                mode=AssistMode.HOMEWORK_ASSIST,
                course_id="unknown-course",
            )
        )
