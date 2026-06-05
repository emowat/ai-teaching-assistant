"""API-facing schemas for the `rag_eng` service."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from rag.schemas import QueryInput, RetrievalResult


class QueryPayload(QueryInput):
    """Typed request payload for the RAG query endpoint.

    `result_count` lets the UI/API request a different number of final retrieved
    documents without changing the underlying retrieval modes.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "student_message": "Why does my program crash?",
                    "code_raw": "int* p; *p = 5;",
                    "terminal_output": "Segmentation fault (core dumped)",
                    "exit_code": 139,
                    "week": 3,
                    "mode": "Homework Assist",
                    "result_count": 5,
                    "ast_features": {
                        "has_pointer": True,
                        "has_reference": False,
                        "has_loop": False,
                        "has_new": False,
                        "has_delete": False,
                        "has_malloc": False,
                        "has_free": False,
                        "has_recursion": False,
                        "target_variables": [],
                    },
                }
            ]
        }
    )

    # Bound the override so the backend always knows the expected output size
    # stays in a sensible range for the UI and prompt formatting.
    result_count: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of final retrieved documents to return.",
    )


class QueryRequest(QueryPayload):
    """Compatibility alias for callers that still import the old request name."""


class QueryResult(BaseModel):
    """Typed response payload for a successful RAG query."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "answer": "Check the pointer before dereferencing it.",
                    "retrieval_result": {
                        "formatted_context": "[Pedagogical_Context]\\nPointers"
                    },
                    "formatted_context": "[Pedagogical_Context]\\nPointers",
                }
            ]
        }
    )

    answer: str
    retrieval_result: RetrievalResult
    formatted_context: str


class QueryResponse(QueryResult):
    """Compatibility alias for callers that still import the old response name."""


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
