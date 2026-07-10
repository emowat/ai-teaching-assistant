from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag.course_registry import (
    CourseRegistry,
    CourseRoute,
    CourseRegistryStatus,
    _load_database_routes,
    get_course_registry_status,
    resolve_course_route,
)
from rag.pipeline import run_retrieval
from rag.schemas import ASTFeatures, AssistMode, CourseSource, QueryInput, RetrievalResult
from rag_eng.schemas import QueryPayload


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
            ("mit13", "mit13", "mit13_course_db", None, None),
            ("mit14", "mit14", "mit14_course_db", None, None),
            ("cs50", "cs50", "cs50_course_db", None, None),
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

    routes, defs = _load_database_routes("postgresql://example")

    assert routes["mit13"].collection_name == "mit13_course_db"
    assert routes["mit14"].collection_name == "mit14_course_db"
    assert routes["cs50"].collection_name == "cs50_course_db"


def test_course_registry_overlays_database_routes(monkeypatch) -> None:
    fake_route = CourseRoute(
        course_id="mit14",
        course_source=CourseSource.MIT_14,
        collection_name="mit14_course_db",
    )
    monkeypatch.setattr(
        "rag.course_registry._load_database_routes",
        lambda database_url: (
            {"mit14": fake_route},
            {},
        ),
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
    monkeypatch.setattr("rag.pipeline.build_course_query", lambda query: "dense query")
    monkeypatch.setattr("rag.pipeline.build_cpp_query", lambda query: "")
    monkeypatch.setattr("rag.pipeline.embed_query", lambda text: [0.0])
    monkeypatch.setattr(
        "rag.pipeline.embed_queries", lambda texts: [[0.0] for _ in texts]
    )
    monkeypatch.setattr(
        "rag.pipeline.retrieve_guidelines",
        lambda query_vector, top_k, threshold: [],
    )

    def fake_semantic(
        query_vector,
        week,
        top_k=5,
        *,
        cumulative=False,
        collection_name,
    ):
        captured["semantic_collection"] = collection_name
        return []

    def fake_rules(
        query_vector,
        week,
        top_k=3,
        threshold=0.55,
        *,
        cumulative=False,
        collection_name,
    ):
        captured["rules_collection"] = collection_name
        return []

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
            course_source=CourseSource.MIT_14,
        )
    )

    assert result.formatted_context == "[ctx]"
    assert captured["semantic_collection"] == "mit14_course"
    assert captured["rules_collection"] == "mit14_course"


def test_run_retrieval_precomputes_query_vectors_before_parallel_calls(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {
        "embed_queries_calls": [],
        "embed_query_calls": [],
        "semantic_vector": None,
        "rules_vector": None,
        "guidelines_vector": None,
    }

    monkeypatch.setattr(
        "rag.course_registry.get_course_registry",
        lambda: _stub_registry(),
    )
    monkeypatch.setattr("rag.pipeline.build_course_query", lambda query: "dense query")
    monkeypatch.setattr("rag.pipeline.build_cpp_query", lambda query: "cpp hints")

    def fake_embed_query(text: str):
        embed_query_calls = captured["embed_query_calls"]
        assert isinstance(embed_query_calls, list)
        embed_query_calls.append(text)
        return [float(len(text))]

    def fake_embed_queries(texts: list[str]):
        embed_queries_calls = captured["embed_queries_calls"]
        assert isinstance(embed_queries_calls, list)
        embed_queries_calls.append(list(texts))
        return [[float(len(text))] for text in texts]

    monkeypatch.setattr("rag.pipeline.embed_query", fake_embed_query)
    monkeypatch.setattr("rag.pipeline.embed_queries", fake_embed_queries)

    def fake_semantic(
        query_vector,
        week,
        top_k=5,
        *,
        cumulative=False,
        collection_name,
    ):
        captured["semantic_vector"] = query_vector
        return []

    def fake_rules(
        query_vector,
        week,
        top_k=3,
        threshold=0.55,
        *,
        cumulative=False,
        collection_name,
    ):
        captured["rules_vector"] = query_vector
        return []

    def fake_guidelines(query_vector, top_k, threshold):
        captured["guidelines_vector"] = query_vector
        return []

    monkeypatch.setattr("rag.pipeline.retrieve_semantic", fake_semantic)
    monkeypatch.setattr("rag.pipeline.retrieve_strict_rules", fake_rules)
    monkeypatch.setattr("rag.pipeline.retrieve_guidelines", fake_guidelines)
    monkeypatch.setattr(
        "rag.pipeline.merge_and_rerank",
        lambda **kwargs: (None, [], [], [], []),
    )
    monkeypatch.setattr(
        "rag.pipeline.build_retrieval_result",
        lambda **kwargs: _stub_retrieval_result(),
    )

    run_retrieval(
        QueryInput(
            student_message="Why does this crash?",
            week=3,
            mode=AssistMode.HOMEWORK_ASSIST,
            course_id="mit14",
            course_source=CourseSource.MIT_14,
            ast_features=ASTFeatures(has_pointer=True),
        )
    )

    assert captured["embed_query_calls"] == []
    assert captured["embed_queries_calls"] == [["dense query", "cpp hints"]]
    assert captured["semantic_vector"] == [11.0]
    assert captured["rules_vector"] == [11.0]
    assert captured["guidelines_vector"] == [9.0]


def test_run_retrieval_applies_rerank_strategy_controls(monkeypatch) -> None:
    captured: dict[str, int | float | str] = {}

    monkeypatch.setattr(
        "rag.course_registry.get_course_registry",
        lambda: _stub_registry(),
    )
    monkeypatch.setattr("rag.pipeline.build_course_query", lambda query: "dense query")
    monkeypatch.setattr("rag.pipeline.build_cpp_query", lambda query: "cpp hints")
    monkeypatch.setattr("rag.pipeline.embed_query", lambda text: [0.0])
    monkeypatch.setattr(
        "rag.pipeline.embed_queries", lambda texts: [[float(len(text))] for text in texts]
    )

    def fake_guidelines(query_vector, top_k, threshold):
        captured["guidelines_top_k"] = top_k
        return []

    monkeypatch.setattr("rag.pipeline.retrieve_guidelines", fake_guidelines)

    def fake_semantic(
        query_vector,
        week,
        top_k=5,
        *,
        cumulative=False,
        collection_name,
    ):
        captured["semantic_top_k"] = top_k
        return []

    def fake_rules(
        query_vector,
        week,
        top_k=3,
        threshold=0.55,
        *,
        cumulative=False,
        collection_name,
    ):
        captured["rules_top_k"] = top_k
        return []

    def fake_merge_and_rerank(**kwargs):
        captured["final_k"] = kwargs["final_k"]
        captured["lambda_param"] = kwargs["lambda_param"]
        return (None, [], [], [], [])

    monkeypatch.setattr("rag.pipeline.retrieve_semantic", fake_semantic)
    monkeypatch.setattr("rag.pipeline.retrieve_strict_rules", fake_rules)
    monkeypatch.setattr("rag.pipeline.merge_and_rerank", fake_merge_and_rerank)
    monkeypatch.setattr(
        "rag.pipeline.build_retrieval_result",
        lambda **kwargs: _stub_retrieval_result(),
    )

    run_retrieval(
        QueryPayload(
            student_message="Why does this crash?",
            week=3,
            mode=AssistMode.HOMEWORK_ASSIST,
            course_id="mit14",
            rerank_strategy="mmr_0.7",
            result_count=8,
        )
    )

    assert captured["final_k"] == 8
    assert captured["lambda_param"] == 0.7
    assert captured["semantic_top_k"] == 5
    assert captured["rules_top_k"] == 3
    assert captured["guidelines_top_k"] == 5


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


def test_get_course_registry_status_reports_unconfigured_when_env_missing(
    monkeypatch,
) -> None:
    monkeypatch.delenv("COURSE_REGISTRY_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    status = get_course_registry_status()

    assert status == CourseRegistryStatus(
        configured=False,
        reachable=False,
        message="Aurora course registry is not configured; using local fallback.",
    )


def test_get_course_registry_status_reports_reachable_when_probe_succeeds(
    monkeypatch,
) -> None:
    class _ProbeCursor:
        def execute(self, query: str) -> None:
            self.query = query

        def fetchone(self):
            return (3,)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _ProbeConnection:
        def cursor(self):
            return _ProbeCursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setenv("COURSE_REGISTRY_DATABASE_URL", "postgresql://example")
    monkeypatch.setattr(
        "rag.course_registry._connect_postgres",
        lambda database_url: _ProbeConnection(),
    )

    status = get_course_registry_status()

    assert status.configured is True
    assert status.reachable is True
    assert "3 active course" in status.message
