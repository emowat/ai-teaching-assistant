from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag.pipeline import run_retrieval
from rag.schemas import AssistMode, CourseSource, QueryInput, RetrievalResult


def _stub_retrieval_result() -> RetrievalResult:
    return RetrievalResult(formatted_context="[ctx]")


def test_run_retrieval_prefers_explicit_course_id(monkeypatch) -> None:
    captured: dict[str, CourseSource] = {}

    monkeypatch.setattr("rag.pipeline.build_query", lambda query: "dense query")
    monkeypatch.setattr(
        "rag.pipeline.retrieve_guidelines",
        lambda dense_query, top_k, threshold: [],
    )

    def fake_syllabus(week, *, course_source):
        captured["course_source"] = course_source
        return SimpleNamespace()

    def fake_semantic(dense_query, week, top_k=5, *, cumulative=False, course_source):
        captured["semantic_course_source"] = course_source
        return []

    def fake_rules(dense_query, week, top_k=3, threshold=0.55, *, cumulative=False, course_source):
        captured["rules_course_source"] = course_source
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
    assert captured["course_source"] is CourseSource.MIT_14
    assert captured["semantic_course_source"] is CourseSource.MIT_14
    assert captured["rules_course_source"] is CourseSource.MIT_14


def test_run_retrieval_falls_back_to_legacy_course_source(monkeypatch) -> None:
    captured: dict[str, CourseSource] = {}

    monkeypatch.setattr("rag.pipeline.build_query", lambda query: "dense query")
    monkeypatch.setattr(
        "rag.pipeline.retrieve_guidelines",
        lambda dense_query, top_k, threshold: [],
    )

    def fake_syllabus(week, *, course_source):
        captured["course_source"] = course_source
        return SimpleNamespace()

    def fake_semantic(dense_query, week, top_k=5, *, cumulative=False, course_source):
        captured["semantic_course_source"] = course_source
        return []

    def fake_rules(dense_query, week, top_k=3, threshold=0.55, *, cumulative=False, course_source):
        captured["rules_course_source"] = course_source
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
            course_source=CourseSource.MIT_13,
        )
    )

    assert result.formatted_context == "[ctx]"
    assert captured["course_source"] is CourseSource.MIT_13
    assert captured["semantic_course_source"] is CourseSource.MIT_13
    assert captured["rules_course_source"] is CourseSource.MIT_13


def test_run_retrieval_rejects_unknown_course_id() -> None:
    with pytest.raises(ValueError, match="Unsupported course_id"):
        run_retrieval(
            QueryInput(
                student_message="Why does this crash?",
                week=3,
                mode=AssistMode.HOMEWORK_ASSIST,
                course_id="unknown-course",
            )
        )
