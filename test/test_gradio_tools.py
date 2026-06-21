"""Tests for admin Gradio tool helpers."""

from __future__ import annotations

from types import SimpleNamespace

from rag_eng.gradio_tools import (
    TrafficLight,
    build_extension_user_message,
    fetch_sagemaker_status,
    format_traffic_lights_html,
    invoke_guardrail_review,
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
        result_count=None,
        rerank_strategy=None,
    ):
        captured["messages"] = messages
        captured["model_name"] = model_name
        captured["stream"] = stream
        captured["course_id"] = course_id
        captured["session_id"] = session_id
        captured["request_id"] = request_id
        captured["turn_id"] = turn_id
        captured["section_id"] = section_id
        captured["result_count"] = result_count
        captured["rerank_strategy"] = rerank_strategy
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
        result_count=8,
        rerank_strategy="mmr_0.9",
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
    assert captured["result_count"] == 8
    assert captured["rerank_strategy"] == "mmr_0.9"
    assert "session=session-123" in status
    assert "request=request-456" in status
    assert "k=8" in status
    assert "rerank=mmr_0.9" in status


def test_invoke_pipeline_chat_includes_guardrail_summary(monkeypatch) -> None:
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
        result_count=None,
        rerank_strategy=None,
    ):
        return {
            "message": {"content": "Guarded response"},
            "session_id": "session-123",
            "request_id": "request-456",
            "turn_id": "turn-789",
            "guardrail": {
                "stage": "v2",
                "action": "replace",
                "severity": "medium",
                "v2_score": 0.835,
            },
        }

    monkeypatch.setattr("rag_eng.gradio_tools.run_chat", fake_run_chat)

    response, raw, status = invoke_pipeline_chat(
        "Why does my pointer segfault?",
        "int *p;",
        "Segmentation fault",
        4,
        "Homework Assist",
        result_count=8,
        rerank_strategy="mmr_0.9",
        settings=SimpleNamespace(
            use_sagemaker=True,
            sagemaker_endpoint="endpoint-name",
            ollama_url="http://localhost:11434/api/chat",
        ),
    )

    assert response == "Guarded response"
    assert '"action": "replace"' in raw
    assert "guardrail=v2" in status
    assert "action=replace" in status
    assert "severity=medium" in status
    assert "v2=0.835" in status


def test_invoke_guardrail_review_reports_outcome(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag_eng.gradio_tools.apply_all_guardrails",
        lambda answer, user_query, student_code, conversation_history: {
            "safe": False,
            "blocked": True,
            "violation_type": "v2_unsafe",
            "severity": "medium",
            "action": "replace",
            "evidence": "v2 score=0.835 > 0.7",
            "final_answer": "Guardrail fallback",
            "v2_score": 0.835,
            "stage": "v2",
        },
    )

    final_answer, raw, status = invoke_guardrail_review(
        "Draft answer",
        "Why does my code crash?",
        "int *p;",
        '[{"role": "user", "content": "previous turn"}]',
    )

    assert final_answer == "Guardrail fallback"
    assert '"action": "replace"' in raw
    assert "stage=v2" in status
    assert "action=replace" in status
    assert "severity=medium" in status
    assert "v2=0.835" in status
