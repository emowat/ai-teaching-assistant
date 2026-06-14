"""Primary ASGI entrypoint for the AWS-ready RAG service."""

from __future__ import annotations

from rag_eng.api import create_app

# create_app() mounts the Gradio admin console at /gradio
app = create_app()
