from __future__ import annotations

from rag_eng.ui import build_gradio_app


def test_build_gradio_app_smoke() -> None:
    app = build_gradio_app()

    assert app is not None
    assert hasattr(app, "fns")
