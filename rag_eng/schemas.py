"""API-facing schemas for the `rag_eng` service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag.schemas import CourseSource as RagCourseSource, QueryInput, RetrievalResult

RetrievalRerankStrategy = Literal["similarity", "mmr_0.5", "mmr_0.7", "mmr_0.9"]
IngestionJobKind = Literal["parse", "chunk-index"]
IngestionJobStatus = Literal["queued", "running", "completed", "failed", "launch_failed"]
RERANK_STRATEGY_CHOICES: tuple[str, ...] = (
    "similarity",
    "mmr_0.5",
    "mmr_0.7",
    "mmr_0.9",
)


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
                    "result_count": 8,
                    "rerank_strategy": "similarity",
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
        default=8,
        ge=1,
        le=20,
        description="Number of final retrieved documents to return.",
    )
    rerank_strategy: RetrievalRerankStrategy = Field(
        default="similarity",
        description="Reranking strategy used to diversify retrieved context.",
    )


class QueryRequest(QueryPayload):
    """Compatibility alias for callers that still import the old request name."""


class GuardrailResult(BaseModel):
    """Structured guardrail outcome returned alongside pipeline answers."""

    stage: str = ""
    safe: bool
    blocked: bool
    violation_type: str
    severity: str
    action: str
    evidence: str
    final_answer: str
    v2_score: float | None = None


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
    guardrail: GuardrailResult | None = None
    session_id: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None


class QueryResponse(QueryResult):
    """Compatibility alias for callers that still import the old response name."""


class HealthResponse(BaseModel):
    """Operational readiness information for the service."""

    ready: bool
    qdrant_configured: bool
    course_registry_configured: bool = False
    cohere_configured: bool
    openai_configured: bool = False
    bedrock_configured: bool = False
    qdrant_reachable: bool
    course_registry_reachable: bool = False
    cohere_reachable: bool = False
    openai_reachable: bool = False
    bedrock_reachable: bool = False
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

    provider: Literal["cohere", "openai", "ollama", "sagemaker", "bedrock"]
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


class AdminCourse(BaseModel):
    """Admin-facing course metadata for CRUD and dashboard views."""

    course_id: str
    display_name: str
    course_source: RagCourseSource
    collection_name: str
    is_active: bool
    aliases: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class AdminCourseCreate(BaseModel):
    """Payload used to create a course in Aurora."""

    course_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    course_source: RagCourseSource
    collection_name: str = Field(min_length=1)
    is_active: bool = True
    aliases: list[str] = Field(default_factory=list)


class AdminCourseUpdate(BaseModel):
    """Payload used to update a course in Aurora."""

    display_name: str | None = None
    course_source: RagCourseSource | None = None
    collection_name: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_non_empty_update(self) -> "AdminCourseUpdate":
        if (
            self.display_name is None
            and self.course_source is None
            and self.collection_name is None
            and self.is_active is None
        ):
            raise ValueError("At least one course field must be provided.")
        return self


class AdminCourseAliasCreate(BaseModel):
    """Payload used to add one or more aliases to a course."""

    aliases: list[str] = Field(min_length=1)


class IngestionJobLaunchRequest(BaseModel):
    """Request to launch an on-demand ECS ingestion task."""

    course_id: str = Field(min_length=1)
    job_kind: IngestionJobKind
    bucket: str = Field(min_length=1)
    input_prefix: str = Field(min_length=1)
    output_prefix: str | None = None
    prepared_output_prefix: str | None = None
    collection_name: str | None = None
    recreate_collection: bool = False

    @model_validator(mode="after")
    def _validate_job_specific_fields(self) -> "IngestionJobLaunchRequest":
        if self.job_kind == "parse" and not self.output_prefix:
            raise ValueError("output_prefix is required for parse jobs")
        return self


class IngestionJobResponse(BaseModel):
    """Status returned for ECS ingestion job launches and lookups."""

    job_id: str
    course_id: str
    job_kind: IngestionJobKind
    status: IngestionJobStatus
    message: str = ""
    registered: bool = False
    course_corpus_version_id: str | None = None
    ecs_cluster: str = ""
    ecs_task_definition: str = ""
    ecs_container_name: str = ""
    ecs_task_arn: str | None = None
    collection_name: str | None = None
    bucket: str = ""
    input_prefix: str = ""
    output_prefix: str | None = None
    prepared_output_prefix: str | None = None
    request_payload: dict[str, str | int | bool | None] = Field(default_factory=dict)
    ecs_response: dict[str, object] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None
