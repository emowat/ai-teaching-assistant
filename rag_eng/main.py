"""Primary ASGI entrypoint for the AWS-ready RAG service."""

from __future__ import annotations

import gradio as gr

from rag_eng.api import create_app
from rag_eng.ui import build_gradio_app


app = create_app()
app = gr.mount_gradio_app(app, build_gradio_app(), path="/gradio")
