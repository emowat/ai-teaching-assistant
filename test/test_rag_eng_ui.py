from __future__ import annotations

from rag_eng.ui import (
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
