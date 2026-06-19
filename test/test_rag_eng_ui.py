from __future__ import annotations

from types import SimpleNamespace

from rag_eng.gradio_tools import SageMakerStatus, TrafficLight
from rag_eng.ui import (
    _clear_sagemaker_request,
    _guardrail_invoke,
    _query_api,
    _resolve_retrieval_preset,
    _pipeline_invoke,
    _refresh_sagemaker_status,
    build_gradio_app,
    build_pipeline_console_app,
    build_rag_query_app,
    build_sagemaker_console_app,
)


def test_build_gradio_app_smoke() -> None:
    for builder in (
        build_gradio_app,
        build_rag_query_app,
        build_sagemaker_console_app,
        build_pipeline_console_app,
    ):
        app = builder()
        assert app is not None
        assert hasattr(app, "fns")
        fn_names = {
            fn.fn.__name__
            for fn in app.fns.values()
            if getattr(fn, "fn", None) is not None
        }
        assert "_refresh_sagemaker_status" in fn_names
        assert "_clear_sagemaker_request" in fn_names
        assert "_guardrail_invoke" in fn_names


def test_refresh_sagemaker_status_renders_current_status(monkeypatch) -> None:
    status = SageMakerStatus(
        endpoint_name="test-endpoint",
        endpoint_status="InService",
        instance_count=1,
        desired_count=1,
        use_sagemaker=True,
        inference_backend="vllm",
        max_model_len="10240",
        lights=[TrafficLight("Endpoint", "ok", "test-endpoint — InService")],
        summary="Endpoint test-endpoint is InService.",
        checked_at="2026-01-01 00:00:00 UTC",
    )
    monkeypatch.setattr("rag_eng.ui.fetch_sagemaker_status", lambda: status)
    monkeypatch.setattr(
        "rag_eng.ui.format_traffic_lights_html",
        lambda value: f"<div>{value.summary}</div>",
    )

    html = _refresh_sagemaker_status()
    assert "Endpoint test-endpoint is InService." in html


def test_clear_sagemaker_request_returns_retry_hint() -> None:
    response, status = _clear_sagemaker_request()
    assert response == ""
    assert "send it again" in status.lower()


def test_resolve_retrieval_preset_uses_saved_values() -> None:
    result_count, rerank_strategy, active_preset = _resolve_retrieval_preset(
        "MMR relevance (K=8, lambda=0.7)",
        3,
        "similarity",
    )

    assert result_count == 8
    assert rerank_strategy == "mmr_0.7"
    assert active_preset == "MMR relevance (K=8, lambda=0.7)"


def test_resolve_retrieval_preset_keeps_manual_controls_for_custom() -> None:
    result_count, rerank_strategy, active_preset = _resolve_retrieval_preset(
        "Custom (manual controls)",
        10,
        "mmr_0.5",
    )

    assert result_count == 10
    assert rerank_strategy == "mmr_0.5"
    assert active_preset == "Custom (manual controls)"


def test_query_api_forwards_rerank_strategy(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "rag_eng.ui.get_settings",
        lambda: SimpleNamespace(api_base_url="http://backend.example"),
    )

    def fake_post_json(url: str, payload: dict) -> dict:
        captured["url"] = url
        captured["payload"] = payload
        return {
            "answer": "answer",
            "retrieval_result": {"formatted_context": "[ctx]"},
            "formatted_context": "[ctx]",
        }

    monkeypatch.setattr("rag_eng.ui._post_json", fake_post_json)

    response, docs, ctx, status = _query_api(
        "Why does my pointer segfault?",
        "int *p;",
        "Segmentation fault",
        4,
        "Homework Assist",
        "Custom (manual controls)",
        8,
        "mmr_0.9",
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    )

    assert response == "answer"
    assert docs == '{\n  "formatted_context": "[ctx]"\n}'
    assert ctx == "[ctx]"
    assert status == "Request completed successfully."
    assert captured["url"] == "http://backend.example/query"
    assert captured["payload"]["result_count"] == 8
    assert captured["payload"]["rerank_strategy"] == "mmr_0.9"
    assert "Preset: Custom" not in status


def test_pipeline_invoke_forwards_trace_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_invoke_pipeline_chat(
        student_message,
        code_raw,
        terminal_output,
        week,
        mode,
        result_count=None,
        rerank_strategy=None,
        course_id=None,
        session_id=None,
        request_id=None,
        turn_id=None,
        section_id=None,
    ):
        captured["student_message"] = student_message
        captured["code_raw"] = code_raw
        captured["terminal_output"] = terminal_output
        captured["week"] = week
        captured["mode"] = mode
        captured["result_count"] = result_count
        captured["rerank_strategy"] = rerank_strategy
        captured["course_id"] = course_id
        captured["session_id"] = session_id
        captured["request_id"] = request_id
        captured["turn_id"] = turn_id
        captured["section_id"] = section_id
        return ("answer", '{"session_id": "session-123"}', "ok")

    monkeypatch.setattr("rag_eng.ui.invoke_pipeline_chat", fake_invoke_pipeline_chat)

    response, raw, status = _pipeline_invoke(
        "Why does my pointer segfault?",
        "int *p;",
        "Segmentation fault",
        4,
        "Homework Assist",
        "Custom (manual controls)",
        8,
        "mmr_0.7",
        "mit14",
        "session-123",
        "request-456",
        "turn-789",
        "section-2",
    )

    assert response == "answer"
    assert raw == '{"session_id": "session-123"}'
    assert status == "ok"
    assert captured["result_count"] == 8
    assert captured["rerank_strategy"] == "mmr_0.7"
    assert captured["course_id"] == "mit14"
    assert captured["session_id"] == "session-123"
    assert captured["request_id"] == "request-456"
    assert captured["turn_id"] == "turn-789"
    assert captured["section_id"] == "section-2"


def test_pipeline_invoke_applies_saved_preset(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_invoke_pipeline_chat(
        student_message,
        code_raw,
        terminal_output,
        week,
        mode,
        result_count=None,
        rerank_strategy=None,
        course_id=None,
        session_id=None,
        request_id=None,
        turn_id=None,
        section_id=None,
    ):
        captured["result_count"] = result_count
        captured["rerank_strategy"] = rerank_strategy
        return ("answer", "{}", "ok")

    monkeypatch.setattr("rag_eng.ui.invoke_pipeline_chat", fake_invoke_pipeline_chat)

    response, raw, status = _pipeline_invoke(
        "Why does my pointer segfault?",
        "int *p;",
        "Segmentation fault",
        4,
        "Homework Assist",
        "MMR focus (K=8, lambda=0.9)",
        3,
        "similarity",
        "mit14",
        "session-123",
        "request-456",
        "turn-789",
        "section-2",
    )

    assert response == "answer"
    assert raw == "{}"
    assert captured["result_count"] == 8
    assert captured["rerank_strategy"] == "mmr_0.9"
    assert "preset=MMR focus (K=8, lambda=0.9)" in status


def test_guardrail_invoke_forwards_inputs(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_invoke_guardrail_review(
        draft_answer,
        student_question,
        student_code,
        conversation_history_json,
    ):
        captured["draft_answer"] = draft_answer
        captured["student_question"] = student_question
        captured["student_code"] = student_code
        captured["conversation_history_json"] = conversation_history_json
        return ("final", "{}", "status")

    monkeypatch.setattr("rag_eng.ui.invoke_guardrail_review", fake_invoke_guardrail_review)

    response, raw, status = _guardrail_invoke(
        "Draft answer",
        "Why does my pointer segfault?",
        "int *p;",
        '[{"role": "user", "content": "previous"}]',
    )

    assert response == "final"
    assert raw == "{}"
    assert status == "status"
    assert captured["draft_answer"] == "Draft answer"
    assert captured["student_question"] == "Why does my pointer segfault?"
    assert captured["student_code"] == "int *p;"
    assert captured["conversation_history_json"] == '[{"role": "user", "content": "previous"}]'
