"""Integration test for the end-to-end retrieval + Cohere response flow."""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv


load_dotenv()


pytestmark = pytest.mark.skipif(
    not os.getenv("COHERE_API_KEY") or not os.getenv("QDRANT_URL"),
    reason="Integration test requires live Cohere and Qdrant credentials.",
)


def test_generate_response_integration() -> None:
    """Run the full RAG flow only when live credentials are available."""
    langchain_cohere = pytest.importorskip("langchain_cohere")

    from rag import ASTFeatures, AssistMode, QueryInput, close_client, generate_response

    cohere_chat_model = langchain_cohere.ChatCohere(
        cohere_api_key=os.environ["COHERE_API_KEY"],
        model="command-xlarge-nightly",
    )

    try:
        answer = generate_response(
            query=QueryInput(
                student_message="Why does my program crash?",
                code_raw="int* p; *p = 5;",
                terminal_output="Segmentation fault (core dumped)",
                exit_code=139,
                week=3,
                mode=AssistMode.HOMEWORK_ASSIST,
                ast_features=ASTFeatures(has_pointer=True),
            ),
            llm=cohere_chat_model,
        )
    finally:
        close_client()

    assert answer
