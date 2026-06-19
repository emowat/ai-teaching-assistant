"""Tests for admin Gradio tool helpers."""

from __future__ import annotations

from types import SimpleNamespace

from rag_eng.gradio_tools import (
    TrafficLight,
    build_extension_user_message,
    fetch_sagemaker_status,
    format_traffic_lights_html,
    invoke_pipeline_chat,
)


def test_build_extension_user_message_includes_blocks() -> None:
    msg = build_extension_user_message(
        mode="Homework Assist",
        week=3,
        code_raw="int *p;",
        terminal_output="segfault",
        student_message="Why?",
    )
    assert "[Code_Context]" in msg
    assert "[Student_Question]" in msg
    assert "Week: 3" in msg


def test_format_traffic_lights_html_renders_lights() -> None:
    from rag_eng.gradio_tools import SageMakerStatus

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
    html = format_traffic_lights_html(status)
    assert "InService" in html
    assert "#22c55e" in html


def test_fetch_sagemaker_status_without_aws(monkeypatch) -> None:
    """Status helper should degrade gracefully when AWS is unavailable."""

    def _fail_session(*_args, **_kwargs):
        raise RuntimeError("no aws")

    monkeypatch.setattr("rag_eng.gradio_tools._boto_session", _fail_session)
    monkeypatch.setattr(
        "rag_eng.gradio_tools._load_deploy_config",
        lambda: (_ for _ in ()).throw(RuntimeError("no yaml")),
    )

    status = fetch_sagemaker_status()
    assert status.endpoint_name
    assert any(light.label == "rag_eng routing" for light in status.lights)


def test_invoke_pipeline_chat_forwards_trace_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_chat(
        messages,
        model_name,
        settings,
        stream=False,
        course_id=None,
        session_id=None,
        request_id=None,
        turn_id=None,
        section_id=None,
    ):
        captured["messages"] = messages
        captured["model_name"] = model_name
        captured["stream"] = stream
        captured["course_id"] = course_id
        captured["session_id"] = session_id
        captured["request_id"] = request_id
        captured["turn_id"] = turn_id
        captured["section_id"] = section_id
        return {
            "message": {"content": "Trace-aware response"},
            "session_id": "session-123",
            "request_id": "request-456",
            "turn_id": "turn-789",
        }

    monkeypatch.setattr("rag_eng.gradio_tools.run_chat", fake_run_chat)

    response, raw, status = invoke_pipeline_chat(
        "Why does my pointer segfault?",
        "int *p;",
        "Segmentation fault",
        4,
        "Homework Assist",
        course_id="mit14",
        session_id="session-123",
        request_id="request-456",
        turn_id="turn-789",
        section_id="section-2",
        settings=SimpleNamespace(
            use_sagemaker=True,
            sagemaker_endpoint="endpoint-name",
            ollama_url="http://localhost:11434/api/chat",
        ),
    )

    assert response == "Trace-aware response"
    assert '"session_id": "session-123"' in raw
    assert captured["course_id"] == "mit14"
    assert captured["session_id"] == "session-123"
    assert captured["request_id"] == "request-456"
    assert captured["turn_id"] == "turn-789"
    assert captured["section_id"] == "section-2"
    assert "session=session-123" in status
    assert "request=request-456" in status
