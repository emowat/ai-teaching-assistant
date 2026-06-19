"""API-facing schemas for the `rag_eng` service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
                    "course_id": "mit13",
                    "course_source": "mit13",
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
    course_registry_configured: bool = False
    cohere_configured: bool
    openai_configured: bool = False
    qdrant_reachable: bool
    course_registry_reachable: bool = False
    cohere_reachable: bool = False
    openai_reachable: bool = False
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


class ModelRouteConfig(BaseModel):
    """Non-secret provider/model pair saved by the admin UI."""

    provider: Literal["cohere", "openai", "ollama", "sagemaker"]
    model: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _validate_model_for_provider(self) -> "ModelRouteConfig":
        if self.provider == "sagemaker":
            return self
        if not self.model.strip():
            raise ValueError(f"model is required for provider '{self.provider}'")
        return self


class AdminLlmConfigResponse(BaseModel):
    """Editable LLM configuration exposed to admins."""

    rag: ModelRouteConfig
    chat: ModelRouteConfig
    openai_api_key_configured: bool
    openai_base_url: str
    restart_command_configured: bool = False


class AdminLlmConfigUpdate(BaseModel):
    """Payload used by the admin UI to persist LLM configuration changes."""

    rag: ModelRouteConfig
    chat: ModelRouteConfig
    openai_api_key: str | None = Field(default=None, max_length=2000)
    openai_base_url: str | None = Field(default=None, max_length=500)


class RestartResponse(BaseModel):
    """Response returned when the backend is asked to reload or restart."""

    success: bool
    scheduled: bool
    message: str
