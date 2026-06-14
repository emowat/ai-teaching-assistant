"""Thin orchestration layer for the AWS-ready RAG service."""

from __future__ import annotations

import re
from typing import AsyncIterator

from rag import (
    build_prompt,
    generate_response_from_result,
    run_retrieval,
)
from rag.runtime import create_qdrant_client

from rag_eng.config import Settings, get_settings
from rag_eng.indexing import ensure_index, rebuild_index
from rag_eng.inference import run_inference
from rag_eng.prompts import get_system_prompt
from rag_eng.schemas import (
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
    QueryPayload,
    QueryResponse,
)


def _build_llm():
    """Create the Cohere chat model lazily."""
    from langchain_cohere import ChatCohere

    settings = get_settings()
    if not settings.cohere_api_key:
        raise ValueError("COHERE_API_KEY is not configured.")
    return ChatCohere(
        cohere_api_key=settings.cohere_api_key,
        model="command-xlarge-nightly",
    )


def run_query(query) -> QueryResponse:
    """Execute retrieval once, then generate the TA answer from that result."""
    retrieval_result = run_retrieval(query)
    llm = _build_llm()
    answer = generate_response_from_result(
        query=query,
        result=retrieval_result,
        llm=llm,
    )
    return QueryResponse(
        answer=answer,
        retrieval_result=retrieval_result,
        formatted_context=retrieval_result.formatted_context,
    )


def get_health() -> HealthResponse:
    """Check config and basic backend connectivity."""
    settings = get_settings()
    qdrant_configured = bool(
        settings.qdrant_url
        and settings.qdrant_api_key
        and settings.qdrant_collection_name
        and settings.qdrant_guidelines_collection_name
        and settings.qdrant_harvard_collection_name
    )
    cohere_configured = bool(settings.cohere_api_key)
    qdrant_reachable = False
    message = "Ready."

    if qdrant_configured:
        try:
            client = create_qdrant_client()
            try:
                client.get_collections()
                qdrant_reachable = True
            finally:
                client.close()
        except Exception as exc:
            message = f"Qdrant connectivity check failed: {exc}"
    else:
        message = "Qdrant environment variables are incomplete."

    if not cohere_configured and message == "Ready.":
        message = "Cohere API key is not configured."

    ready = qdrant_configured and qdrant_reachable and cohere_configured
    return HealthResponse(
        ready=ready,
        qdrant_configured=qdrant_configured,
        cohere_configured=cohere_configured,
        qdrant_reachable=qdrant_reachable,
        cohere_reachable=cohere_configured,
        message=message,
    )


def preview_prompt(query) -> str:
    """Build the final LLM prompt for debugging and tests."""
    retrieval_result = run_retrieval(query)
    return build_prompt(query=query, result=retrieval_result)


def ensure_index_service() -> IndexEnsureResponse:
    """Service adapter for the idempotent indexing flow."""
    result = ensure_index()
    return IndexEnsureResponse(
        success=True,
        collection_name=result.collection_name,
        created_collection=result.created_collection,
        indexed_documents=result.indexed_documents,
        message=result.message,
    )


def rebuild_index_service() -> IndexRebuildResponse:
    """Service adapter for the destructive indexing flow."""
    result = rebuild_index()
    return IndexRebuildResponse(
        success=True,
        collection_name=result.collection_name,
        indexed_documents=result.indexed_documents,
        message=result.message,
    )


# ---------------------------------------------------------------------------
# Chat orchestration  (called by POST /api/chat — VS Code extension endpoint)
# ---------------------------------------------------------------------------

def _extract_chat_context(messages: list[dict]) -> dict:
    """Pull structured fields out of the extension's [Context] blocks."""
    last_user = next(
        (m for m in reversed(messages) if m.get("role") == "user"), None
    )
    content = last_user["content"] if last_user else ""

    def _block(tag: str) -> str:
        m = re.search(rf"\[{tag}\](.*?)(?=\[|$)", content, re.DOTALL)
        return m.group(1).strip() if m else ""

    mode = "Study Assist" if "Mode: Study Assist" in content else "Homework Assist"
    code_raw = _block("Code_Context")
    terminal_output = _block("Terminal_Context")
    student_message = re.sub(r"\[.*?\][\s\S]*?(?=\[|$)", "", content).strip()

    return {
        "student_message": student_message or content,
        "code_raw": code_raw,
        "terminal_output": terminal_output,
        "mode": mode,
    }


async def run_chat(
    messages: list[dict],
    model_name: str,
    settings: Settings,
    stream: bool = False,
) -> dict | AsyncIterator[bytes]:
    """Full chat pipeline: context extraction → RAG → prompt assembly → inference.

    Replaces the mocked backend/rag_client.py with real Qdrant + Cohere retrieval.
    """
    ctx = _extract_chat_context(messages)

    # Build a QueryPayload from the chat context so we can reuse run_retrieval
    query = QueryPayload(
        student_message=ctx["student_message"],
        code_raw=ctx["code_raw"] or None,
        terminal_output=ctx["terminal_output"] or None,
        mode=ctx["mode"],
    )

    retrieval_result = run_retrieval(query)
    rag_context = retrieval_result.formatted_context

    # Strip any existing system message injected by the extension
    api_messages = [m for m in messages if m.get("role") != "system"]

    system_prompt = get_system_prompt(ctx["mode"])
    full_system = f"{system_prompt}\n{rag_context}"
    api_messages.insert(0, {"role": "system", "content": full_system})

    return await run_inference(api_messages, model_name, settings, stream=stream)
