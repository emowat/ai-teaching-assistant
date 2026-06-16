from __future__ import annotations

from rag_eng.gradio_tools import SageMakerStatus, TrafficLight
from rag_eng.ui import (
    _clear_sagemaker_request,
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
