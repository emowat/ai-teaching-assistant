"""Thin orchestration layer for the AWS-ready RAG service."""

from __future__ import annotations

from rag import (
    build_prompt,
    generate_response_from_result,
    run_retrieval,
)
from rag.runtime import create_qdrant_client

from rag_eng.config import get_settings
from rag_eng.indexing import ensure_index, rebuild_index
from rag_eng.schemas import (
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
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
