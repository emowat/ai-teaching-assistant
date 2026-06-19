from __future__ import annotations

from rag_eng.gradio_tools import SageMakerStatus, TrafficLight
from rag_eng.ui import (
    _clear_sagemaker_request,
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


def test_pipeline_invoke_forwards_trace_overrides(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_invoke_pipeline_chat(
        student_message,
        code_raw,
        terminal_output,
        week,
        mode,
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
        "mit14",
        "session-123",
        "request-456",
        "turn-789",
        "section-2",
    )

    assert response == "answer"
    assert raw == '{"session_id": "session-123"}'
    assert status == "ok"
    assert captured["course_id"] == "mit14"
    assert captured["session_id"] == "session-123"
    assert captured["request_id"] == "request-456"
    assert captured["turn_id"] == "turn-789"
    assert captured["section_id"] == "section-2"
