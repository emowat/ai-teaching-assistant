"""API-facing schemas for the `rag_eng` service."""

from __future__ import annotations

from pydantic import BaseModel, Field

from rag.schemas import QueryInput, RetrievalResult


class QueryRequest(QueryInput):
    """FastAPI request model for RAG queries.

    `result_count` lets the UI/API request a different number of final retrieved
    documents without changing the underlying retrieval modes.
    """

    # Bound the override so the backend always knows the expected output size
    # stays in a sensible range for the UI and prompt formatting.
    result_count: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of final retrieved documents to return.",
    )


class QueryResponse(BaseModel):
    """FastAPI response for a query that includes answer and retrieval context."""

    answer: str
    retrieval_result: RetrievalResult
    formatted_context: str


class HealthResponse(BaseModel):
    """Operational readiness information for the service."""

    ready: bool
    qdrant_configured: bool
    cohere_configured: bool
    qdrant_reachable: bool
    cohere_reachable: bool = False
    message: str = ""


class IndexEnsureResponse(BaseModel):
    """Response for the idempotent ensure-index flow."""

    success: bool
    collection_name: str
    created_collection: bool
    indexed_documents: int
    message: str


class IndexRebuildResponse(BaseModel):
    """Response for the destructive rebuild-index flow."""

    success: bool
    collection_name: str
    indexed_documents: int
    message: str = Field(
        default="Collection rebuilt successfully.",
    )
