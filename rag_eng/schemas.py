"""API-facing schemas for the `rag_eng` service."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_eng.config import bedrock_inference_profile_id
from rag_eng.config import is_deprecated_bedrock_model_id
from rag.schemas import CourseSource as RagCourseSource, QueryInput, RetrievalResult, EngagementMetrics

RetrievalRerankStrategy = Literal["similarity", "mmr_0.5", "mmr_0.7", "mmr_0.9"]
IngestionJobKind = Literal["parse", "chunk-index"]
IngestionJobStatus = Literal["queued", "running", "completed", "failed", "launch_failed"]
AppPrimaryRole = Literal["admin", "professor", "student"]
UserStatus = Literal["invited", "active", "disabled"]
SectionMembershipStatus = Literal["invited", "active", "dropped", "disabled"]
SectionMembershipRole = Literal["professor", "ta", "student"]
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


class TelemetryPayload(BaseModel):
    """Payload for out-of-band telemetry from the VS Code extension."""
    session_id: str
    mode: str
    engagement_metrics: EngagementMetrics


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
    evaluated_answer: str | None = None


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
    input_guardrail: dict[str, Any] | None = None
    session_id: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None


class QueryResponse(QueryResult):
    """Compatibility alias for callers that still import the old response name."""


class ChatMessage(BaseModel):
    """Minimal chat message payload returned by the pipeline endpoints."""

    content: str


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


class SectionMembershipSummary(BaseModel):
    """Nested section membership summary used by admin and professor views."""

    section_id: str
    user_id: str | None = None
    section_display_name: str = ""
    course_id: str
    course_display_name: str = ""
    role_in_section: SectionMembershipRole
    status: SectionMembershipStatus
    created_at: str = ""
    updated_at: str = ""


class AdminUser(BaseModel):
    """Application user record backed by Aurora."""

    user_id: str
    cognito_sub: str | None = None
    email: str
    display_name: str = ""
    primary_role: AppPrimaryRole
    status: UserStatus = "invited"
    section_memberships: list[SectionMembershipSummary] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class AdminUserCreate(BaseModel):
    """Payload used to create an application user in Aurora."""

    email: str = Field(min_length=1)
    display_name: str = ""
    primary_role: AppPrimaryRole
    status: UserStatus = "invited"


class AdminUserUpdate(BaseModel):
    """Payload used to update an application user in Aurora."""

    display_name: str | None = None
    primary_role: AppPrimaryRole | None = None
    status: UserStatus | None = None

    @model_validator(mode="after")
    def _validate_non_empty_update(self) -> "AdminUserUpdate":
        if (
            self.display_name is None
            and self.primary_role is None
            and self.status is None
        ):
            raise ValueError("At least one user field must be provided.")
        return self


class AdminSection(BaseModel):
    """Application section record backed by Aurora."""

    section_id: str
    course_id: str
    course_display_name: str = ""
    display_name: str
    term: str = ""
    is_active: bool = True
    professor_count: int = 0
    ta_count: int = 0
    student_count: int = 0
    memberships: list[SectionMembershipSummary] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class AdminSectionCreate(BaseModel):
    """Payload used to create a section in Aurora."""

    section_id: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    term: str = ""
    is_active: bool = True


class AdminSectionUpdate(BaseModel):
    """Payload used to update a section in Aurora."""

    display_name: str | None = None
    term: str | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_non_empty_update(self) -> "AdminSectionUpdate":
        if self.display_name is None and self.term is None and self.is_active is None:
            raise ValueError("At least one section field must be provided.")
        return self


class AdminSectionMembershipCreate(BaseModel):
    """Payload used to create a section membership in Aurora."""

    user_id: str = Field(min_length=1)
    role_in_section: SectionMembershipRole
    status: SectionMembershipStatus = "active"


class AdminSectionMembershipUpdate(BaseModel):
    """Payload used to update a section membership in Aurora."""

    role_in_section: SectionMembershipRole | None = None
    status: SectionMembershipStatus | None = None

    @model_validator(mode="after")
    def _validate_non_empty_update(self) -> "AdminSectionMembershipUpdate":
        if self.role_in_section is None and self.status is None:
            raise ValueError("At least one membership field must be provided.")
        return self


class ProfessorSectionSummary(BaseModel):
    """Professor-facing section summary with roster counts."""

    section_id: str
    course_id: str
    course_display_name: str = ""
    display_name: str
    term: str = ""
    is_active: bool = True
    professor_count: int = 0
    ta_count: int = 0
    student_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class ProfessorSectionStudent(BaseModel):
    """Professor-facing student roster row."""

    user_id: str
    cognito_sub: str | None = None
    email: str
    display_name: str = ""
    membership_status: SectionMembershipStatus
    role_in_section: SectionMembershipRole
    session_count: int = 0
    last_session_at: str = ""


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
        if self.provider == "bedrock" and is_deprecated_bedrock_model_id(self.model):
            profile_id = bedrock_inference_profile_id(self.model)
            raise ValueError(
                "Bedrock Claude Sonnet 4.6 must use an inference profile ID "
                f"such as '{profile_id}' or 'global.anthropic.claude-sonnet-4-6'; "
                "the foundation-model ID 'anthropic.claude-sonnet-4-6' is not supported."
            )
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


class DiagnosticTrace(BaseModel):
    """Trace identifiers returned by the admin diagnostics endpoints."""

    session_id: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None


class InputGuardrailDiagnosticResponse(BaseModel):
    """Response for the admin input-guardrail diagnostic endpoint."""

    diagnostic_source: str = "admin_diagnostic"
    trace: DiagnosticTrace
    input_guardrail: dict[str, Any]
    blocked: bool
    final_answer: str
    orchestrator_context: dict[str, Any] | None = None


class RagDiagnosticResponse(BaseModel):
    """Response for the admin RAG diagnostic endpoint."""

    diagnostic_source: str = "admin_diagnostic"
    trace: DiagnosticTrace
    answer: str
    retrieval_result: RetrievalResult
    formatted_context: str
    prompt_preview: str
    input_guardrail: dict[str, Any] | None = None


class OutputGuardrailReviewRequest(QueryPayload):
    """Payload for the admin output-guardrail diagnostic endpoint."""

    draft_answer: str
    conversation_history: list[dict[str, Any]] = Field(default_factory=list)


class OutputGuardrailDiagnosticResponse(BaseModel):
    """Response for the admin output-guardrail diagnostic endpoint."""

    diagnostic_source: str = "admin_diagnostic"
    trace: DiagnosticTrace
    draft_answer: str
    final_answer: str
    guardrail: GuardrailResult


class PipelineDiagnosticResponse(BaseModel):
    """Response for the admin full-pipeline diagnostic endpoint."""

    diagnostic_source: str = "admin_diagnostic"
    message: ChatMessage
    guardrail: GuardrailResult | None = None
    input_guardrail: dict[str, Any] | None = None
    session_id: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None


class AdminCourse(BaseModel):
    """Admin-facing course metadata for CRUD and dashboard views."""

    course_id: str
    display_name: str
    course_source: RagCourseSource
    collection_name: str
    is_active: bool
    has_ingestion_history: bool = False
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


class AdminCourseDocument(BaseModel):
    """S3-backed source document metadata for a course."""

    key: str
    file_name: str
    size_bytes: int
    last_modified: str = ""
    etag: str | None = None


class AdminCourseDocumentListResponse(BaseModel):
    """Course-scoped view of uploaded source documents in S3."""

    course_id: str
    bucket: str
    upload_prefix: str
    parsed_prefix: str
    prepared_prefix: str
    documents: list[AdminCourseDocument] = Field(default_factory=list)


class AdminCourseDocumentUploadRequest(BaseModel):
    """Payload used to request a presigned upload URL for a course document."""

    file_name: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _validate_file_name(self) -> "AdminCourseDocumentUploadRequest":
        cleaned = self.file_name.strip()
        if not cleaned:
            raise ValueError("file_name is required.")
        if "/" in cleaned or "\\" in cleaned:
            raise ValueError("file_name must be a single file name, not a path.")
        if cleaned in {".", ".."}:
            raise ValueError("file_name must name a real file.")
        self.file_name = cleaned
        if self.content_type is not None:
            self.content_type = self.content_type.strip() or None
        return self


class AdminCourseDocumentUploadResponse(BaseModel):
    """Presigned upload target for a course document."""

    course_id: str
    bucket: str
    key: str
    upload_prefix: str
    parsed_prefix: str
    prepared_prefix: str
    upload_url: str
    upload_method: str = "PUT"
    expires_in_seconds: int
    required_headers: dict[str, str] = Field(default_factory=dict)


class AdminCourseDocumentDeleteResponse(BaseModel):
    """Response returned after deleting a course document from S3."""

    course_id: str
    bucket: str
    key: str
    deleted: bool = True


class AdminCourseCorpusVersion(BaseModel):
    """Aurora-backed history entry for a course corpus build."""

    course_corpus_version_id: str
    course_id: str
    collection_name: str
    source_bucket: str
    source_prefix: str
    parsed_prefix: str | None = None
    prepared_prefix: str | None = None
    status: str
    active: bool
    recreate_collection: bool
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    completed_at: str | None = None


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
