"""Tests for admin Gradio tool helpers."""

from __future__ import annotations

from rag_eng.gradio_tools import (
    TrafficLight,
    build_extension_user_message,
    fetch_sagemaker_status,
    format_traffic_lights_html,
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
