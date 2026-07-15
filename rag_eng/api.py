"""FastAPI application for the AWS-ready RAG service."""

from __future__ import annotations

import os
import re
import subprocess
import uuid
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Optional


from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from rag_eng.auth.cognito import verify_cognito_access_token
from rag_eng.auth.dependencies import (
    require_authenticated_user,
    require_student_surface_user,
)
from rag_eng.auth.models import CurrentUser, MeResponse
from rag_eng.app_registry import (
    AppUserConflictError,
    AppUserDisabledError,
    AppUserNotFoundError,
    AppUserNotProvisionedError,
    CognitoInviteError,
    CognitoInviteNotConfiguredError,
    MembershipAccessDeniedError,
    MembershipConflictError,
    MembershipNotFoundError,
    SectionConflictError,
    SectionNotFoundError,
    get_student_bootstrap,
    create_admin_section,
    create_admin_user,
    create_section_membership,
    invite_professor_section_student,
    archive_professor_section_teaching_plan,
    list_admin_sections,
    list_admin_users,
    create_professor_section_teaching_plan_week,
    create_professor_section_teaching_plan_week_reference,
    get_professor_section_analytics,
    get_professor_section_student_analytics,
    list_professor_section_launch_configs,
    get_professor_section_teaching_plan,
    get_professor_section_teaching_plan_week,
    list_professor_section_teaching_plan_week_references,
    list_professor_section_students,
    list_professor_sections,
    require_student_section_access,
    sync_application_user,
    replace_professor_section_launch_configs,
    publish_professor_section_teaching_plan,
    get_professor_section_instruction_settings,
    upsert_professor_section_teaching_plan,
    upsert_professor_section_instruction_settings,
    update_admin_section,
    update_admin_user,
    delete_professor_section_teaching_plan_week,
    update_professor_section_teaching_plan_week,
    delete_professor_section_teaching_plan_week_reference,
    update_professor_section_teaching_plan_week_reference,
    update_section_membership,
)
from rag_eng.evaluation_jobs import (
    get_evaluation_config_payload,
    get_evaluation_overview,
    get_evaluation_run,
    launch_evaluation_run,
    list_evaluation_runs,
)
from rag_eng.course_admin import (
    CourseConflictError,
    CourseNotFoundError,
    add_admin_course_aliases,
    create_admin_course,
    deactivate_admin_course_alias,
    get_admin_course,
    list_admin_courses,
    update_admin_course,
)
from rag_eng.document_admin import (
    create_admin_course_upload_url,
    delete_admin_course_document,
    list_admin_course_corpus_versions,
    list_admin_course_documents,
)
from rag_eng.config import (
    Settings,
    get_inference_config,
    get_runtime_config_path,
    load_runtime_config,
    get_settings,
    reload_inference_config,
    save_runtime_config,
    update_env_file,
)
from rag_eng.schemas import (
    AdminLlmConfigResponse,
    AdminLlmConfigUpdate,
    AdminCourse,
    AdminCourseAliasCreate,
    ChatLogExportResponse,
    AdminCourseCreate,
    AdminCourseCorpusVersion,
    AdminCourseDocumentDeleteResponse,
    AdminCourseDocumentListResponse,
    AdminCourseDocumentUploadRequest,
    AdminCourseDocumentUploadResponse,
    AdminCourseUpdate,
    AdminSection,
    AdminSectionCreate,
    AdminSectionMembershipCreate,
    AdminSectionMembershipUpdate,
    AdminSectionUpdate,
    AdminUser,
    AdminUserCreate,
    AdminUserUpdate,
    InputGuardrailDiagnosticResponse,
    IngestionJobLaunchRequest,
    IngestionJobResponse,
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
    ProfessorSectionStudent,
    ProfessorSectionStudentInviteCreate,
    ProfessorSectionAnalytics,
    ProfessorSectionStudentAnalytics,
    ProfessorSectionSummary,
    ProfessorTeachingPlan,
    ProfessorTeachingPlanUpdate,
    ProfessorTeachingPlanWeek,
    ProfessorTeachingPlanWeekCreate,
    ProfessorTeachingPlanWeekReference,
    ProfessorTeachingPlanWeekReferenceCreate,
    ProfessorTeachingPlanWeekReferenceUpdate,
    ProfessorTeachingPlanWeekUpdate,
    SectionInstructionSettings,
    SectionInstructionSettingsUpdate,
    SectionLaunchConfig,
    EvaluationRunCreate,
    EvaluationRunSummary,
    OutputGuardrailDiagnosticResponse,
    OutputGuardrailReviewRequest,
    QueryPayload,
    QueryResult,
    PipelineDiagnosticResponse,
    RagDiagnosticResponse,
    RetrievalRerankStrategy,
    RestartResponse,
    StudentFeedbackPayload,
    StudentBootstrapResponse,
    StudentTelemetryPayload,
    TelemetryPayload,
)
from rag_eng.ingestion_jobs import (
    get_ingestion_job,
    launch_ingestion_job,
    list_ingestion_jobs,
)
from rag_eng.runner_client import RunnerError, run_cpp_job
from rag_eng.run_schemas import CompileRequest, CompileResponse
from rag_eng.service import (
    ensure_index_service,
    get_health,
    rebuild_index_service,
    run_input_guardrail_diagnostic,
    run_chat,
    run_output_guardrail_diagnostic,
    run_pipeline_diagnostic,
    run_rag_diagnostic,
    run_query,
)
from rag_eng.telemetry import TelemetryStore

logger = logging.getLogger(__name__)


class _ChatOptions(BaseModel):
    temperature: float = 0.7
    top_p: float = 0.9
    num_ctx: int = 8192
    num_predict: int = 2048


class ChatRequest(BaseModel):
    """Ollama-compatible chat request (sent by the VS Code extension)."""

    model: str = "codingrabbit-ta"
    course_id: str | None = None
    week: int | None = Field(default=None, ge=1, le=8)
    session_id: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    turn_index: int | None = None
    section_id: str | None = None
    result_count: int = Field(default=8, ge=1, le=20)
    rerank_strategy: RetrievalRerankStrategy = "similarity"
    messages: list[dict]
    stream: bool = False
    options: _ChatOptions = _ChatOptions()


class FeedbackPayload(BaseModel):
    session_id: str | None = None
    rating: str
    reason: str | None = None
    message_index: int | None = None
    turn_id: str | None = None


def _missing_payload_fields(payload: BaseModel, field_names: list[str]) -> list[str]:
    """Return the names of any required payload fields that are missing."""
    missing: list[str] = []
    for field_name in field_names:
        value = getattr(payload, field_name, None)
        if value in {None, ""}:
            missing.append(field_name)
    return missing


def _error_detail(exc: Exception) -> str:
    """Return a non-empty HTTP error message (httpx timeouts often str() to '')."""
    detail = str(exc).strip()
    if detail:
        return detail
    return type(exc).__name__


def _replace_request_header(
    headers: list[tuple[bytes, bytes]],
    header_name: bytes,
    value: bytes,
) -> list[tuple[bytes, bytes]]:
    """Replace a single ASGI header in-place-safe form."""
    normalized_name = header_name.lower()
    updated: list[tuple[bytes, bytes]] = []
    replaced = False

    for key, existing_value in headers:
        if key.lower() == normalized_name:
            if not replaced:
                updated.append((header_name, value))
                replaced = True
            continue
        updated.append((key, existing_value))

    if not replaced:
        updated.append((header_name, value))

    return updated


def _require_admin(
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


_admin_bearer = HTTPBearer(auto_error=False)


def _require_admin_access(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.admin_token and x_admin_token == settings.admin_token:
        return

    # Allow the static admin token to be passed as a Bearer token (for transitional frontend compatibility)
    if settings.admin_token and credentials and credentials.scheme.lower() == "bearer":
        if credentials.credentials == settings.admin_token:
            return

    if credentials is None or credentials.scheme.lower() != "bearer":
        logger.error(f"Missing admin credentials. credentials={credentials}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin credentials.",
        )

    try:
        current_user = verify_cognito_access_token(credentials.credentials, settings)
    except Exception:
        import traceback

        error_msg = traceback.format_exc()
        logger.error(
            f"Failed to verify cognito access token! Token was: {credentials.credentials[:20]}...\nException trace:\n{error_msg}"
        )
        raise

    if current_user.primary_role != "admin":
        logger.error(f"Insufficient role. Primary role: {current_user.primary_role}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for this operation.",
        )


def _require_admin_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_admin_bearer),
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> CurrentUser | None:
    if settings.admin_token and x_admin_token == settings.admin_token:
        return None

    # Allow the static admin token to be passed as a Bearer token (for transitional frontend compatibility)
    if settings.admin_token and credentials and credentials.scheme.lower() == "bearer":
        if credentials.credentials == settings.admin_token:
            return None

    if credentials is None or credentials.scheme.lower() != "bearer":
        logger.error(f"Missing admin credentials. credentials={credentials}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin credentials.",
        )

    try:
        current_user = verify_cognito_access_token(credentials.credentials, settings)
    except Exception:
        import traceback

        error_msg = traceback.format_exc()
        logger.error(
            f"Failed to verify cognito access token! Token was: {credentials.credentials[:20]}...\nException trace:\n{error_msg}"
        )
        raise

    if current_user.primary_role != "admin":
        logger.error(f"Insufficient role. Primary role: {current_user.primary_role}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for this operation.",
        )
    return current_user


def _runtime_config_payload() -> AdminLlmConfigResponse:
    settings = get_settings()
    runtime = get_inference_config()
    return AdminLlmConfigResponse(
        rag={"provider": runtime.rag.provider, "model": runtime.rag.model},
        chat={"provider": runtime.chat.provider, "model": runtime.chat.model},
        openai_api_key_configured=bool(settings.openai_api_key),
        openai_base_url=settings.openai_base_url or runtime.openai_base_url,
        restart_command_configured=bool(settings.restart_command),
    )


def _course_admin_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CourseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, CourseConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _app_registry_http_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc, (AppUserNotFoundError, SectionNotFoundError, MembershipNotFoundError)
    ):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(
        exc,
        (
            AppUserConflictError,
            SectionConflictError,
            MembershipConflictError,
        ),
    ):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(
        exc,
        (
            AppUserDisabledError,
            AppUserNotProvisionedError,
            MembershipAccessDeniedError,
        ),
    ):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, CognitoInviteNotConfiguredError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, CognitoInviteError):
        return HTTPException(status_code=502, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, CourseNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _evaluation_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _public_diagnostic_response(response: dict[str, Any]) -> dict[str, Any]:
    """Mark a diagnostic payload as coming from the public curl surface."""
    public_response = dict(response)
    public_response["diagnostic_source"] = "public_diagnostic"
    return public_response


def _should_mount_gradio() -> bool:
    value = os.getenv("RAG_ENG_MOUNT_GRADIO", "true").strip().lower()
    return value in {"1", "true", "yes", "on"}


def create_app() -> FastAPI:
    """Create the FastAPI app for the RAG service."""
    settings = get_settings()
    public_origin = settings.gradio_public_origin
    public_origin_parts = None
    if public_origin:
        parsed_origin = urlparse(public_origin.strip())
        if parsed_origin.scheme and parsed_origin.netloc:
            public_origin_parts = (parsed_origin.scheme, parsed_origin.netloc)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Run DB migrations on startup before serving any requests."""
        try:
            from rag_eng.telemetry import _connect_postgres
            from rag_eng.chat_log_export import _resolve_database_url

            database_url = _resolve_database_url(None)
            if database_url:
                with _connect_postgres(database_url, 10) as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS syllabus_matrix TEXT;"
                        )
                        cur.execute(
                            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS style_guide TEXT;"
                        )
                        cur.execute(
                            "ALTER TABLE courses ADD COLUMN IF NOT EXISTS launch_configs TEXT;"
                        )
                        cur.execute(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_status text "
                            "NOT NULL DEFAULT 'pending' "
                            "CHECK (consent_status IN ('pending', 'granted', 'withdrawn'));"
                        )
                        cur.execute(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_granted_at timestamptz;"
                        )
                        cur.execute(
                            "ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_withdrawn_at timestamptz;"
                        )
                    conn.commit()
                logger.info("Startup migration: consent columns ensured.")
        except Exception as exc:
            logger.warning(f"Startup migration skipped or failed: {exc}")
        yield

    app = FastAPI(
        title="rag_eng",
        description="AWS-ready FastAPI layer for the capstone RAG pipeline.",
        version="0.1.0",
        lifespan=lifespan,
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def forward_public_origin_for_gradio(
        request: Request,
        call_next,
    ):
        if public_origin_parts and request.url.path.startswith("/gradio"):
            scheme, netloc = public_origin_parts
            headers = list(request.scope.get("headers", []))
            headers = _replace_request_header(
                headers,
                b"x-forwarded-host",
                netloc.encode("latin-1"),
            )
            headers = _replace_request_header(
                headers,
                b"x-forwarded-proto",
                scheme.encode("latin-1"),
            )
            request.scope["headers"] = headers
        return await call_next(request)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return get_health()

    @app.get("/me", response_model=MeResponse)
    def me(current_user=Depends(require_authenticated_user)) -> MeResponse:
        if current_user.primary_role in {"professor", "student"}:
            try:
                sync_application_user(current_user)
            except Exception as exc:
                raise _app_registry_http_error(exc) from exc
        return MeResponse.from_current_user(current_user)

    @app.get(
        "/api/student/bootstrap",
        response_model=StudentBootstrapResponse,
    )
    def student_bootstrap(
        current_user=Depends(require_student_surface_user),
    ) -> StudentBootstrapResponse:
        try:
            return get_student_bootstrap(current_user)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post("/api/student/consent/grant")
    def student_consent_grant(
        current_user=Depends(require_student_surface_user),
    ) -> dict:
        """Grant consent for the authenticated student.

        Transitions consent_status from 'pending' → 'granted'. No-ops if
        already granted. Returns 403 if consent has been withdrawn — withdrawal
        is permanent and cannot be reversed via this endpoint.
        """
        try:
            app_user = sync_application_user(current_user)
            if not app_user:
                raise HTTPException(
                    status_code=404, detail="No provisioned user found."
                )
            if app_user.get("consent_status") == "withdrawn":
                raise HTTPException(
                    status_code=403,
                    detail="Consent has been permanently withdrawn and cannot be re-granted.",
                )
            from rag_eng.app_registry import grant_user_consent

            grant_user_consent(app_user["user_id"])
            return {"success": True, "consent_status": "granted"}
        except HTTPException:
            raise
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post("/query", response_model=QueryResult)
    def query(payload: QueryPayload) -> QueryResult:
        try:
            return run_query(payload)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/api/diagnostics/input-guardrail",
        response_model=InputGuardrailDiagnosticResponse,
    )
    def public_diagnostic_input_guardrail(
        payload: QueryPayload,
    ) -> InputGuardrailDiagnosticResponse:
        try:
            return _public_diagnostic_response(run_input_guardrail_diagnostic(payload))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/api/diagnostics/rag",
        response_model=RagDiagnosticResponse,
    )
    def public_diagnostic_rag(payload: QueryPayload) -> RagDiagnosticResponse:
        try:
            return _public_diagnostic_response(run_rag_diagnostic(payload))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/api/diagnostics/output-guardrail",
        response_model=OutputGuardrailDiagnosticResponse,
    )
    def public_diagnostic_output_guardrail(
        payload: OutputGuardrailReviewRequest,
    ) -> OutputGuardrailDiagnosticResponse:
        try:
            return _public_diagnostic_response(
                run_output_guardrail_diagnostic(
                    query=payload,
                    draft_answer=payload.draft_answer,
                    conversation_history=payload.conversation_history,
                )
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/api/diagnostics/pipeline",
        response_model=PipelineDiagnosticResponse,
    )
    async def public_diagnostic_pipeline(
        payload: ChatRequest,
        settings: Settings = Depends(get_settings),
    ):
        try:
            result = await run_pipeline_diagnostic(
                messages=payload.messages,
                model_name=payload.model,
                settings=settings,
                stream=payload.stream,
                course_id=payload.course_id,
                session_id=payload.session_id,
                request_id=payload.request_id,
                turn_id=payload.turn_id,
                turn_index=payload.turn_index,
                section_id=payload.section_id,
                result_count=payload.result_count,
                rerank_strategy=payload.rerank_strategy,
            )
            if payload.stream:
                return StreamingResponse(result, media_type="application/x-ndjson")
            if isinstance(result, dict):
                return _public_diagnostic_response(result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=_error_detail(exc)) from exc

    @app.post(
        "/admin/diagnostics/input-guardrail",
        response_model=InputGuardrailDiagnosticResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_diagnostic_input_guardrail(
        payload: QueryPayload,
    ) -> InputGuardrailDiagnosticResponse:
        try:
            return run_input_guardrail_diagnostic(payload)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/admin/diagnostics/rag",
        response_model=RagDiagnosticResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_diagnostic_rag(
        payload: QueryPayload,
    ) -> RagDiagnosticResponse:
        try:
            return run_rag_diagnostic(payload)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/admin/diagnostics/output-guardrail",
        response_model=OutputGuardrailDiagnosticResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_diagnostic_output_guardrail(
        payload: OutputGuardrailReviewRequest,
    ) -> OutputGuardrailDiagnosticResponse:
        try:
            return run_output_guardrail_diagnostic(
                query=payload,
                draft_answer=payload.draft_answer,
                conversation_history=payload.conversation_history,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/admin/index/ensure",
        response_model=IndexEnsureResponse,
        dependencies=[Depends(_require_admin)],
    )
    def admin_ensure_index() -> IndexEnsureResponse:
        try:
            return ensure_index_service()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/admin/index/rebuild",
        response_model=IndexRebuildResponse,
        dependencies=[Depends(_require_admin)],
    )
    def admin_rebuild_index() -> IndexRebuildResponse:
        try:
            return rebuild_index_service()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get(
        "/admin/courses",
        response_model=list[AdminCourse],
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_list_courses() -> list[AdminCourse]:
        try:
            return list_admin_courses()
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.get(
        "/admin/courses/{course_id}",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_get_course(course_id: str) -> AdminCourse:
        try:
            return get_admin_course(course_id)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.post(
        "/admin/courses",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_create_course(payload: AdminCourseCreate) -> AdminCourse:
        try:
            return create_admin_course(payload)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.patch(
        "/admin/courses/{course_id}",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_update_course(course_id: str, payload: AdminCourseUpdate) -> AdminCourse:
        try:
            return update_admin_course(course_id, payload)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.post(
        "/admin/courses/{course_id}/aliases",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_add_course_aliases(
        course_id: str,
        payload: AdminCourseAliasCreate,
    ) -> AdminCourse:
        try:
            return add_admin_course_aliases(course_id, payload)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.delete(
        "/admin/courses/{course_id}/aliases/{alias}",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_delete_course_alias(course_id: str, alias: str) -> AdminCourse:
        try:
            return deactivate_admin_course_alias(course_id, alias)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.get(
        "/admin/users",
        response_model=list[AdminUser],
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_list_users_endpoint() -> list[AdminUser]:
        try:
            return list_admin_users()
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/admin/users",
        response_model=AdminUser,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_create_user(payload: AdminUserCreate) -> AdminUser:
        try:
            return create_admin_user(payload)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.patch(
        "/admin/users/{user_id}",
        response_model=AdminUser,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_update_user(user_id: str, payload: AdminUserUpdate) -> AdminUser:
        try:
            return update_admin_user(user_id, payload)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/admin/sections",
        response_model=list[AdminSection],
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_list_sections_endpoint() -> list[AdminSection]:
        try:
            return list_admin_sections()
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/admin/sections",
        response_model=AdminSection,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_create_section(payload: AdminSectionCreate) -> AdminSection:
        try:
            return create_admin_section(payload)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.patch(
        "/admin/sections/{section_id}",
        response_model=AdminSection,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_update_section(
        section_id: str,
        payload: AdminSectionUpdate,
    ) -> AdminSection:
        try:
            return update_admin_section(section_id, payload)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/admin/sections/{section_id}/memberships",
        response_model=AdminSection,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_create_section_membership(
        section_id: str,
        payload: AdminSectionMembershipCreate,
    ) -> AdminSection:
        try:
            return create_section_membership(section_id, payload)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.patch(
        "/admin/sections/{section_id}/memberships/{user_id}",
        response_model=AdminSection,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_update_section_membership(
        section_id: str,
        user_id: str,
        payload: AdminSectionMembershipUpdate,
    ) -> AdminSection:
        try:
            return update_section_membership(section_id, user_id, payload)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections",
        response_model=list[ProfessorSectionSummary],
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_list_sections(
        current_user=Depends(require_authenticated_user),
    ) -> list[ProfessorSectionSummary]:
        try:
            return list_professor_sections(current_user)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/students",
        response_model=list[ProfessorSectionStudent],
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_list_section_students(
        section_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> list[ProfessorSectionStudent]:
        try:
            return list_professor_section_students(current_user, section_id)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/professor/sections/{section_id}/students",
        response_model=list[ProfessorSectionStudent],
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_invite_section_student(
        section_id: str,
        payload: ProfessorSectionStudentInviteCreate,
        current_user=Depends(require_authenticated_user),
    ) -> list[ProfessorSectionStudent]:
        try:
            return invite_professor_section_student(current_user, section_id, payload)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/analytics",
        response_model=ProfessorSectionAnalytics,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_get_section_analytics(
        section_id: str,
        tz: str = "America/Los_Angeles",
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorSectionAnalytics:
        try:
            return get_professor_section_analytics(current_user, section_id, tz=tz)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/students/{student_user_id}/analytics",
        response_model=ProfessorSectionStudentAnalytics,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_get_student_analytics(
        section_id: str,
        student_user_id: str,
        tz: str = "America/Los_Angeles",
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorSectionStudentAnalytics:
        try:
            return get_professor_section_student_analytics(
                current_user,
                section_id,
                student_user_id,
                tz=tz,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/launch-configs",
        response_model=list[SectionLaunchConfig],
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_list_section_launch_configs(
        section_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> list[SectionLaunchConfig]:
        try:
            return list_professor_section_launch_configs(current_user, section_id)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.put(
        "/professor/sections/{section_id}/launch-configs",
        response_model=list[SectionLaunchConfig],
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_replace_section_launch_configs(
        section_id: str,
        payload: list[SectionLaunchConfig],
        current_user=Depends(require_authenticated_user),
    ) -> list[SectionLaunchConfig]:
        try:
            return replace_professor_section_launch_configs(
                current_user, section_id, payload
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/instruction-settings",
        response_model=SectionInstructionSettings,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_get_section_instruction_settings(
        section_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> SectionInstructionSettings:
        try:
            return get_professor_section_instruction_settings(current_user, section_id)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.patch(
        "/professor/sections/{section_id}/instruction-settings",
        response_model=SectionInstructionSettings,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_update_section_instruction_settings(
        section_id: str,
        payload: SectionInstructionSettingsUpdate,
        current_user=Depends(require_authenticated_user),
    ) -> SectionInstructionSettings:
        try:
            return upsert_professor_section_instruction_settings(
                current_user, section_id, payload
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/teaching-plan",
        response_model=ProfessorTeachingPlan,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_get_section_teaching_plan(
        section_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlan:
        try:
            return get_professor_section_teaching_plan(current_user, section_id)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/professor/sections/{section_id}/teaching-plan",
        response_model=ProfessorTeachingPlan,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_upsert_section_teaching_plan(
        section_id: str,
        payload: ProfessorTeachingPlanUpdate,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlan:
        try:
            return upsert_professor_section_teaching_plan(
                current_user, section_id, payload
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/professor/sections/{section_id}/teaching-plan/publish",
        response_model=ProfessorTeachingPlan,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_publish_section_teaching_plan(
        section_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlan:
        try:
            return publish_professor_section_teaching_plan(current_user, section_id)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/professor/sections/{section_id}/teaching-plan/archive",
        response_model=ProfessorTeachingPlan,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_archive_section_teaching_plan(
        section_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlan:
        try:
            return archive_professor_section_teaching_plan(current_user, section_id)
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/professor/sections/{section_id}/teaching-plan/weeks",
        response_model=ProfessorTeachingPlan,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_create_section_teaching_plan_week(
        section_id: str,
        payload: ProfessorTeachingPlanWeekCreate,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlan:
        try:
            return create_professor_section_teaching_plan_week(
                current_user, section_id, payload
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/teaching-plan/weeks/{week_id}",
        response_model=ProfessorTeachingPlanWeek,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_get_section_teaching_plan_week(
        section_id: str,
        week_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlanWeek:
        try:
            return get_professor_section_teaching_plan_week(
                current_user, section_id, week_id
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.patch(
        "/professor/sections/{section_id}/teaching-plan/weeks/{week_id}",
        response_model=ProfessorTeachingPlan,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_update_section_teaching_plan_week(
        section_id: str,
        week_id: str,
        payload: ProfessorTeachingPlanWeekUpdate,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlan:
        try:
            return update_professor_section_teaching_plan_week(
                current_user,
                section_id,
                week_id,
                payload,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.delete(
        "/professor/sections/{section_id}/teaching-plan/weeks/{week_id}",
        response_model=ProfessorTeachingPlan,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_delete_section_teaching_plan_week(
        section_id: str,
        week_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlan:
        try:
            return delete_professor_section_teaching_plan_week(
                current_user, section_id, week_id
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/professor/sections/{section_id}/teaching-plan/weeks/{week_id}/references",
        response_model=list[ProfessorTeachingPlanWeekReference],
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_list_section_teaching_plan_week_references(
        section_id: str,
        week_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> list[ProfessorTeachingPlanWeekReference]:
        try:
            return list_professor_section_teaching_plan_week_references(
                current_user,
                section_id,
                week_id,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.post(
        "/professor/sections/{section_id}/teaching-plan/weeks/{week_id}/references",
        response_model=ProfessorTeachingPlanWeek,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_create_section_teaching_plan_week_reference(
        section_id: str,
        week_id: str,
        payload: ProfessorTeachingPlanWeekReferenceCreate,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlanWeek:
        try:
            return create_professor_section_teaching_plan_week_reference(
                current_user,
                section_id,
                week_id,
                payload,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.patch(
        "/professor/sections/{section_id}/teaching-plan/weeks/{week_id}/references/{reference_id}",
        response_model=ProfessorTeachingPlanWeek,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_update_section_teaching_plan_week_reference(
        section_id: str,
        week_id: str,
        reference_id: str,
        payload: ProfessorTeachingPlanWeekReferenceUpdate,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlanWeek:
        try:
            return update_professor_section_teaching_plan_week_reference(
                current_user,
                section_id,
                week_id,
                reference_id,
                payload,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.delete(
        "/professor/sections/{section_id}/teaching-plan/weeks/{week_id}/references/{reference_id}",
        response_model=ProfessorTeachingPlanWeek,
        dependencies=[Depends(require_authenticated_user)],
    )
    def professor_delete_section_teaching_plan_week_reference(
        section_id: str,
        week_id: str,
        reference_id: str,
        current_user=Depends(require_authenticated_user),
    ) -> ProfessorTeachingPlanWeek:
        try:
            return delete_professor_section_teaching_plan_week_reference(
                current_user,
                section_id,
                week_id,
                reference_id,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

    @app.get(
        "/admin/courses/{course_id}/documents",
        response_model=AdminCourseDocumentListResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_list_course_documents(course_id: str) -> AdminCourseDocumentListResponse:
        try:
            return list_admin_course_documents(course_id)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.post(
        "/admin/courses/{course_id}/documents/upload-url",
        response_model=AdminCourseDocumentUploadResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_create_course_document_upload_url(
        course_id: str,
        payload: AdminCourseDocumentUploadRequest,
    ) -> AdminCourseDocumentUploadResponse:
        try:
            return create_admin_course_upload_url(course_id, payload)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.delete(
        "/admin/courses/{course_id}/documents",
        response_model=AdminCourseDocumentDeleteResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_delete_course_document(
        course_id: str,
        key: str = Query(min_length=1),
    ) -> AdminCourseDocumentDeleteResponse:
        try:
            return delete_admin_course_document(course_id, key=key)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.get(
        "/admin/courses/{course_id}/corpus-versions",
        response_model=list[AdminCourseCorpusVersion],
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_list_course_corpus_versions(
        course_id: str,
        limit: int = Query(default=25, ge=1, le=100),
    ) -> list[AdminCourseCorpusVersion]:
        try:
            return list_admin_course_corpus_versions(course_id, limit=limit)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.get(
        "/admin/ingestion/jobs",
        response_model=list[IngestionJobResponse],
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_list_ingestion_jobs(
        course_id: str | None = None,
        limit: int = Query(default=25, ge=1, le=100),
    ) -> list[IngestionJobResponse]:
        try:
            return list_ingestion_jobs(course_id=course_id, limit=limit)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post(
        "/admin/ingestion/launch",
        response_model=IngestionJobResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_launch_ingestion(
        payload: IngestionJobLaunchRequest,
    ) -> IngestionJobResponse:
        try:
            return launch_ingestion_job(payload)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get(
        "/admin/ingestion/jobs/{job_id}",
        response_model=IngestionJobResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_get_ingestion_job(job_id: str) -> IngestionJobResponse:
        try:
            return get_ingestion_job(job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get(
        "/api/admin/evaluations/config",
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_get_evaluations_config() -> dict[str, Any]:
        try:
            return get_evaluation_config_payload()
        except Exception as exc:
            raise _evaluation_http_error(exc) from exc

    @app.post(
        "/api/admin/evaluations/runs",
        response_model=EvaluationRunSummary,
    )
    def admin_launch_evaluation_run(
        payload: EvaluationRunCreate,
        current_user: CurrentUser | None = Depends(_require_admin_context),
    ) -> EvaluationRunSummary:
        try:
            return launch_evaluation_run(payload, current_user=current_user)
        except Exception as exc:
            raise _evaluation_http_error(exc) from exc

    @app.get(
        "/api/admin/evaluations/runs",
        response_model=list[EvaluationRunSummary],
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_list_evaluation_runs(
        limit: int = Query(default=25, ge=1, le=100),
        status: str | None = None,
    ) -> list[EvaluationRunSummary]:
        try:
            return list_evaluation_runs(limit=limit, status=status)
        except Exception as exc:
            raise _evaluation_http_error(exc) from exc

    @app.get(
        "/api/admin/evaluations/runs/{run_id}",
        response_model=EvaluationRunSummary,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_get_evaluation_run(run_id: str) -> EvaluationRunSummary:
        try:
            return get_evaluation_run(run_id)
        except Exception as exc:
            raise _evaluation_http_error(exc) from exc

    @app.get(
        "/api/admin/evaluations/overview",
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_get_evaluation_overview(
        limit: int = Query(default=25, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return get_evaluation_overview(limit=limit)
        except Exception as exc:
            raise _evaluation_http_error(exc) from exc

    @app.get(
        "/api/admin/llm/config",
        response_model=AdminLlmConfigResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_get_llm_config() -> AdminLlmConfigResponse:
        return _runtime_config_payload()

    @app.post(
        "/api/admin/llm/config",
        response_model=AdminLlmConfigResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_save_llm_config(payload: AdminLlmConfigUpdate) -> AdminLlmConfigResponse:
        runtime_path = get_runtime_config_path()
        runtime = get_inference_config()
        existing = load_runtime_config(runtime_path)
        runtime_block = dict(existing.get("runtime", {}))
        runtime_block["rag"] = payload.rag.model_dump()
        runtime_block["chat"] = payload.chat.model_dump()
        runtime_block["openai"] = {
            "base_url": (
                payload.openai_base_url
                if payload.openai_base_url is not None
                else runtime.openai_base_url
            ),
        }
        existing["runtime"] = runtime_block
        updated = existing
        save_runtime_config(updated, runtime_path)

        env_updates: dict[str, str | None] = {}
        if payload.openai_api_key is not None:
            env_updates["OPENAI_API_KEY"] = payload.openai_api_key
            os.environ["OPENAI_API_KEY"] = payload.openai_api_key
        if payload.openai_base_url is not None:
            env_updates["OPENAI_BASE_URL"] = payload.openai_base_url
            os.environ["OPENAI_BASE_URL"] = payload.openai_base_url
        if env_updates:
            repo_root = Path(__file__).resolve().parent.parent
            update_env_file(repo_root / ".env", env_updates)

        reload_inference_config()
        return _runtime_config_payload()

    @app.post(
        "/admin/run-migration",
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_run_migration() -> dict:
        from rag_eng.telemetry import _connect_postgres
        from rag_eng.chat_log_export import _resolve_database_url

        database_url = _resolve_database_url(None)
        if not database_url:
            raise HTTPException(status_code=500, detail="No database URL configured.")

        try:
            with _connect_postgres(database_url, 5) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS syllabus_matrix TEXT;"
                    )
                    cursor.execute(
                        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS style_guide TEXT;"
                    )
                    cursor.execute(
                        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS launch_configs TEXT;"
                    )
                    # Consent columns (Issue 3 — mandatory opt-in)
                    cursor.execute(
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_status text "
                        "NOT NULL DEFAULT 'pending' "
                        "CHECK (consent_status IN ('pending', 'granted', 'withdrawn'));"
                    )
                    cursor.execute(
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_granted_at timestamptz;"
                    )
                    cursor.execute(
                        "ALTER TABLE users ADD COLUMN IF NOT EXISTS consent_withdrawn_at timestamptz;"
                    )
                connection.commit()
            return {"success": True, "message": "Migration complete."}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post(
        "/api/admin/restart",
        response_model=RestartResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_restart_backend() -> RestartResponse:
        settings = get_settings()
        reload_inference_config()

        if settings.restart_command:
            subprocess.Popen(
                settings.restart_command,
                shell=True,
                start_new_session=True,
                cwd=str(Path(__file__).resolve().parent.parent),
            )
            return RestartResponse(
                success=True,
                scheduled=True,
                message="Restart command scheduled in the background.",
            )

        return RestartResponse(
            success=True,
            scheduled=False,
            message="Configuration reloaded in process. No restart command is configured.",
        )

    @app.post("/run/compile", response_model=CompileResponse)
    def compile_code(
        payload: CompileRequest,
        _user=Depends(require_authenticated_user),
        settings: Settings = Depends(get_settings),
    ) -> CompileResponse:
        job_id = f"job_{uuid.uuid4().hex}"
        try:
            result = run_cpp_job(
                {
                    "job_id": job_id,
                    "files": payload.files,
                    "entrypoint": payload.entrypoint,
                    "mode": payload.mode,
                    "stdin": payload.stdin,
                },
                settings=settings,
            )
            status = "completed" if result.compile.success else "failed"
            return CompileResponse(job_id=job_id, status=status, result=result)
        except RunnerError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=_error_detail(exc)) from exc

    @app.post("/api/feedback")
    async def feedback_endpoint(payload: FeedbackPayload):
        from datetime import datetime
        import json
        from rag_eng.telemetry import TelemetryStore

        try:
            feedback_data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "session_id": payload.session_id,
                "rating": payload.rating,
                "reason": payload.reason,
                "message_index": payload.message_index,
            }
            logger.warning("Feedback received: " + json.dumps(feedback_data))

            if payload.session_id and payload.message_index:
                telemetry = TelemetryStore.from_env()
                telemetry.record_feedback(
                    session_id=payload.session_id,
                    message_index=payload.message_index,
                    rating=payload.rating,
                    reason=payload.reason,
                    turn_id=payload.turn_id,
                )

            return {"status": "success"}
        except Exception as exc:
            logger.exception("Feedback logging failed")
            raise HTTPException(status_code=500, detail=str(exc))

    # Basic in-memory telemetry queue
    @app.post("/api/telemetry")
    async def telemetry_endpoint(payload: TelemetryPayload):
        from datetime import datetime
        import json
        from rag_eng.telemetry import TelemetryStore

        try:
            telemetry_data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "session_id": payload.session_id,
                "mode": payload.mode,
                "engagement_metrics": payload.engagement_metrics.model_dump(),
            }
            logger.info(json.dumps(telemetry_data))

            if payload.session_id:
                telemetry = TelemetryStore.from_env()
                telemetry.record_out_of_band_telemetry(
                    session_id=payload.session_id,
                    mode=payload.mode,
                    engagement_metrics=payload.engagement_metrics.model_dump(),
                )

            return {"status": "success"}
        except Exception as exc:
            logger.exception("Telemetry logging failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/chat")
    async def chat(
        payload: ChatRequest,
        settings: Settings = Depends(get_settings),
    ):
        """VS Code extension endpoint (Ollama-compatible format).

        No Cognito auth required here — the extension runs in student Codespaces
        without a browser session. Auth will be added in a future sprint when
        the extension supports Cognito tokens.
        """
        try:
            result = await run_chat(
                messages=payload.messages,
                model_name=payload.model,
                settings=settings,
                stream=payload.stream,
                course_id=payload.course_id,
                week_override=payload.week,
                session_id=payload.session_id,
                request_id=payload.request_id,
                turn_id=payload.turn_id,
                turn_index=payload.turn_index,
                section_id=payload.section_id,
                result_count=payload.result_count,
                rerank_strategy=payload.rerank_strategy,
            )
            if payload.stream:
                return StreamingResponse(result, media_type="application/x-ndjson")
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=_error_detail(exc)) from exc

    @app.post("/api/student/chat")
    async def student_chat(
        payload: ChatRequest,
        settings: Settings = Depends(get_settings),
        current_user=Depends(require_student_surface_user),
    ):
        """Authenticated student chat endpoint backed by Aurora membership."""
        missing_fields = _missing_payload_fields(
            payload,
            ["section_id", "request_id", "turn_id", "turn_index"],
        )
        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail=(
                    "/api/student/chat requires " + ", ".join(missing_fields) + "."
                ),
            )

        try:
            app_user = require_student_section_access(
                current_user,
                payload.section_id,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

        try:
            result = await run_chat(
                messages=payload.messages,
                model_name=payload.model,
                settings=settings,
                stream=payload.stream,
                course_id=payload.course_id,
                week_override=payload.week,
                session_id=payload.session_id,
                request_id=payload.request_id,
                turn_id=payload.turn_id,
                turn_index=payload.turn_index,
                section_id=payload.section_id,
                result_count=payload.result_count,
                rerank_strategy=payload.rerank_strategy,
                user_sub=current_user.cognito_sub,
                app_user_id=app_user["user_id"],
                current_user=current_user,
            )
            if payload.stream:
                return StreamingResponse(result, media_type="application/x-ndjson")
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=_error_detail(exc)) from exc

    @app.post("/api/student/telemetry")
    async def student_telemetry(
        payload: StudentTelemetryPayload,
        current_user=Depends(require_student_surface_user),
    ):
        """Authenticated student telemetry routed through Aurora."""
        missing_fields = _missing_payload_fields(
            payload,
            ["session_id", "section_id", "request_id", "turn_id", "turn_index"],
        )
        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail=(
                    "/api/student/telemetry requires " + ", ".join(missing_fields) + "."
                ),
            )

        try:
            app_user = require_student_section_access(
                current_user,
                payload.section_id,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

        try:
            telemetry = TelemetryStore.from_env()
            telemetry.record_out_of_band_telemetry(
                session_id=payload.session_id,
                mode=payload.mode,
                engagement_metrics=payload.engagement_metrics.model_dump(),
                request_id=payload.request_id,
                turn_id=payload.turn_id,
                turn_index=payload.turn_index,
                section_id=payload.section_id,
                user_sub=current_user.cognito_sub,
                app_user_id=app_user["user_id"],
                course_id=payload.course_id,
            )
            return {"status": "success"}
        except Exception as exc:
            logger.exception("Student telemetry logging failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post("/api/student/feedback")
    async def student_feedback(
        payload: StudentFeedbackPayload,
        current_user=Depends(require_student_surface_user),
    ):
        """Authenticated student feedback routed through Aurora."""
        missing_fields = _missing_payload_fields(
            payload,
            ["session_id", "section_id", "request_id", "turn_id", "turn_index"],
        )
        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail=(
                    "/api/student/feedback requires " + ", ".join(missing_fields) + "."
                ),
            )

        try:
            app_user = require_student_section_access(
                current_user,
                payload.section_id,
            )
        except Exception as exc:
            raise _app_registry_http_error(exc) from exc

        try:
            telemetry = TelemetryStore.from_env()
            telemetry.record_feedback(
                session_id=payload.session_id,
                message_index=payload.turn_index,
                rating=payload.rating,
                reason=payload.reason,
                turn_id=payload.turn_id,
                user_sub=current_user.cognito_sub,
                app_user_id=app_user["user_id"],
            )
            return {"status": "success"}
        except Exception as exc:
            logger.exception("Student feedback logging failed")
            raise HTTPException(status_code=500, detail=str(exc))

    @app.post(
        "/admin/diagnostics/pipeline",
        response_model=PipelineDiagnosticResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    async def admin_diagnostic_pipeline(
        payload: ChatRequest,
        settings: Settings = Depends(get_settings),
    ):
        try:
            result = await run_pipeline_diagnostic(
                messages=payload.messages,
                model_name=payload.model,
                settings=settings,
                stream=payload.stream,
                course_id=payload.course_id,
                session_id=payload.session_id,
                request_id=payload.request_id,
                turn_id=payload.turn_id,
                section_id=payload.section_id,
                result_count=payload.result_count,
                rerank_strategy=payload.rerank_strategy,
            )
            if payload.stream:
                return StreamingResponse(result, media_type="application/x-ndjson")
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=_error_detail(exc)) from exc

    @app.post(
        "/api/admin/export-chat-logs",
        response_model=ChatLogExportResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def export_chat_logs(
        start_date: str | None = Query(
            default=None, description="UTC start date (YYYY-MM-DD). Defaults to today."
        ),
        end_date: str | None = Query(
            default=None,
            description="UTC end date (YYYY-MM-DD). Defaults to start_date.",
        ),
        course_id: str | None = Query(
            default=None, description="Optional course ID filter."
        ),
        tz: str = Query(
            default="America/Los_Angeles",
            description="Timezone to use for resolving 'today' defaults",
        ),
    ) -> ChatLogExportResponse:
        from datetime import date as date_type, datetime
        from rag_eng.chat_log_export import (
            export_turn_snapshots_to_s3,
            _resolve_database_url,
        )

        database_url = _resolve_database_url(None)
        if not database_url:
            raise HTTPException(
                status_code=500,
                detail="No database URL configured for chat log export.",
            )

        import pytz

        if tz not in pytz.all_timezones:
            raise HTTPException(status_code=400, detail="Invalid timezone")

        pt_tz = pytz.timezone(tz)
        parsed_start = (
            date_type.fromisoformat(start_date)
            if start_date
            else datetime.now(pt_tz).date()
        )
        parsed_end = date_type.fromisoformat(end_date) if end_date else parsed_start

        try:
            partitions = export_turn_snapshots_to_s3(
                database_url=database_url,
                start_date=parsed_start,
                end_date=parsed_end,
                course_id=course_id,
                tz=tz,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500, detail=f"Export failed: {exc}"
            ) from exc

        total = sum(p["record_count"] for p in partitions)
        return ChatLogExportResponse(
            partitions=partitions,
            total_records=total,
            message=f"Exported {total} turn snapshots across {len(partitions)} partitions.",
        )

    @app.get(
        "/api/admin/dashboard/stats",
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_dashboard_stats(
        course_id: str | None = None, tz: str = "America/Los_Angeles"
    ):
        import pytz

        if tz not in pytz.all_timezones:
            raise HTTPException(status_code=400, detail="Invalid timezone")

        from rag_eng.telemetry import _connect_postgres
        from rag_eng.chat_log_export import _resolve_database_url

        database_url = _resolve_database_url(None)
        if not database_url:
            raise HTTPException(
                status_code=500, detail="No database URL configured for telemetry."
            )

        try:
            with _connect_postgres(database_url, 5) as connection:
                with connection.cursor() as cursor:
                    # 1. Daily Rewards, Nudges, & Engagement
                    course_filter = "AND course_id = %s" if course_id else ""
                    params = (course_id,) if course_id else ()

                    cursor.execute(
                        f"""
                        WITH combined AS (
                            SELECT
                                metadata->>'rewards_given' as r,
                                metadata->>'style_nudges' as n,
                                metadata->>'active_chat_seconds' as c,
                                metadata->>'active_editor_seconds' as e,
                                metadata->>'active_shell_seconds' as s
                            FROM telemetry_events
                            WHERE event_type = 'out_of_band_telemetry'
                            AND DATE((created_at AT TIME ZONE '{tz}')) = (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE
                            {course_filter}
                        )
                        SELECT
                            SUM(COALESCE(CAST(r AS INTEGER), 0)) as total_rewards,
                            SUM(COALESCE(CAST(n AS INTEGER), 0)) as total_style_nudges,
                            SUM(COALESCE(CAST(c AS INTEGER), 0)) as chat_seconds,
                            SUM(COALESCE(CAST(e AS INTEGER), 0)) as editor_seconds,
                            SUM(COALESCE(CAST(s AS INTEGER), 0)) as terminal_seconds
                        FROM combined
                    """,
                        params,
                    )
                    row = cursor.fetchone()
                    total_rewards = row[0] if row and row[0] else 0
                    total_style_nudges = row[1] if row and row[1] else 0
                    chat_seconds = row[2] if row and row[2] else 0
                    editor_seconds = row[3] if row and row[3] else 0
                    terminal_seconds = row[4] if row and row[4] else 0

                    # 2. Sessions Today
                    cursor.execute(
                        f"""
                        SELECT
                            COUNT(DISTINCT session_id),
                            COUNT(*)
                        FROM tutor_turn_snapshots
                        WHERE DATE((created_at AT TIME ZONE '{tz}')) = (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE
                        {course_filter}
                    """,
                        params,
                    )
                    row = cursor.fetchone()
                    sessions_today = row[0] if row else 0
                    requests_today = row[1] if row else 0

                    # 3. Request Volume (Last 7 days, by mode and pedagogical action)
                    cursor.execute(
                        f"""
                        SELECT
                            TO_CHAR((created_at AT TIME ZONE '{tz}'), 'Dy') as day,
                            COALESCE(snapshot->'ide_context'->>'mode', 'unknown') as mode,
                            COALESCE(INITCAP(REPLACE(SUBSTRING(snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys'->>'Pedagogical_Action' FROM '([A-Z_]{{2,}})'), '_', ' ')), 'None') as category,
                            COUNT(*) as count
                        FROM tutor_turn_snapshots
                        WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                        {course_filter}
                        GROUP BY DATE((created_at AT TIME ZONE '{tz}')), day, mode, category
                        ORDER BY DATE((created_at AT TIME ZONE '{tz}')) ASC
                    """,
                        params,
                    )
                    volume_rows = cursor.fetchall()

                    from datetime import datetime, timedelta
                    import pytz

                    pt_tz = pytz.timezone(tz)
                    volume_data = {}
                    for i in range(6, -1, -1):
                        d = (datetime.now(pt_tz) - timedelta(days=i)).strftime("%a")
                        volume_data[d] = {"day": d, "sessions": 0}

                    normalized_rows = []
                    for row in volume_rows:
                        day, mode, cat, count = row

                        # Normalize old/broken mode strings so they render in the UI
                        mode_lower = str(mode).lower().replace("_", " ")
                        if "study" in mode_lower:
                            mode = "Study Assist"
                        else:
                            mode = "Homework Assist"  # Fallback

                        normalized_rows.append((day, mode, cat, count))

                        if day not in volume_data:
                            volume_data[day] = {"day": day, "sessions": 0}
                        volume_data[day]["sessions"] += count
                        key = f"{mode}: {cat}"
                        if key not in volume_data[day]:
                            volume_data[day][key] = 0
                        volume_data[day][key] += count
                    session_data = list(volume_data.values())

                    homework_keys = list(
                        set(
                            [
                                f"{r[1]}: {r[2]}"
                                for r in normalized_rows
                                if r[1] == "Homework Assist"
                            ]
                        )
                    )
                    study_keys = list(
                        set(
                            [
                                f"{r[1]}: {r[2]}"
                                for r in normalized_rows
                                if r[1] == "Study Assist"
                            ]
                        )
                    )

                    # 4. Guardrail Interventions (Input/Output blocks)
                    cursor.execute(
                        f"""
                        SELECT
                            COUNT(CASE WHEN snapshot->'input_guardrail_phase'->>'action' = 'block' THEN 1 END) as input_blocks,
                            COUNT(CASE WHEN snapshot->'output_guardrail_phase'->>'action' IN ('block', 'replace') THEN 1 END) as output_blocks,
                            COUNT(CASE WHEN snapshot->'input_guardrail_phase'->>'wouldBlock' = 'true' THEN 1 END) as input_dry_runs,
                            COUNT(CASE WHEN snapshot->'output_guardrail_phase'->>'wouldBlock' = 'true' THEN 1 END) as output_dry_runs
                        FROM tutor_turn_snapshots
                        WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                        {course_filter}
                    """,
                        params,
                    )
                    row = cursor.fetchone()
                    input_blocks = row[0] if row else 0
                    output_blocks = row[1] if row else 0
                    input_dry_runs = row[2] if row else 0
                    output_dry_runs = row[3] if row else 0

                    # 5. Violation Types (Pie Chart)
                    cursor.execute(
                        f"""
                        SELECT
                            COALESCE(
                                NULLIF(snapshot->'input_guardrail_phase'->>'violation_type', 'none'),
                                snapshot->'output_guardrail_phase'->>'violation_type'
                            ) as violation_type,
                            COUNT(*) as count
                        FROM tutor_turn_snapshots
                        WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                        {course_filter}
                        AND (
                            (snapshot->'input_guardrail_phase'->>'action' IN ('block', 'log_only')) OR
                            (snapshot->'output_guardrail_phase'->>'action' IN ('block', 'replace', 'log_only'))
                        )
                        GROUP BY violation_type
                    """,
                        params,
                    )
                    violation_rows = cursor.fetchall()
                    violation_types = [
                        {"name": r[0] or "unknown", "value": r[1]}
                        for r in violation_rows
                    ]

                    # 6. Latency Metrics (P50, P90, P99)
                    cursor.execute(
                        f"""
                        SELECT
                            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY (snapshot->'backend_retrieval_phase'->>'latency_ms')::numeric), 0) as rag_p50,
                            COALESCE(percentile_cont(0.9) WITHIN GROUP (ORDER BY (snapshot->'backend_retrieval_phase'->>'latency_ms')::numeric), 0) as rag_p90,
                            COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY (snapshot->'backend_retrieval_phase'->>'latency_ms')::numeric), 0) as rag_p99,
                            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY (snapshot->'ta_generation_phase'->'generation_history'->-1->>'generation_latency_ms')::numeric), 0) as llm_p50,
                            COALESCE(percentile_cont(0.9) WITHIN GROUP (ORDER BY (snapshot->'ta_generation_phase'->'generation_history'->-1->>'generation_latency_ms')::numeric), 0) as llm_p90,
                            COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY (snapshot->'ta_generation_phase'->'generation_history'->-1->>'generation_latency_ms')::numeric), 0) as llm_p99,
                            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY (snapshot->'input_guardrail_phase'->>'latency_ms')::numeric), 0) as input_p50,
                            COALESCE(percentile_cont(0.9) WITHIN GROUP (ORDER BY (snapshot->'input_guardrail_phase'->>'latency_ms')::numeric), 0) as input_p90,
                            COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY (snapshot->'input_guardrail_phase'->>'latency_ms')::numeric), 0) as input_p99,
                            COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY (snapshot->'output_guardrail_phase'->>'latency_ms')::numeric), 0) as output_p50,
                            COALESCE(percentile_cont(0.9) WITHIN GROUP (ORDER BY (snapshot->'output_guardrail_phase'->>'latency_ms')::numeric), 0) as output_p90,
                            COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY (snapshot->'output_guardrail_phase'->>'latency_ms')::numeric), 0) as output_p99
                        FROM tutor_turn_snapshots
                        WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                        {course_filter}
                    """,
                        params,
                    )
                    row = cursor.fetchone()
                    latencies = {
                        "rag": {
                            "p50": int(row[0]),
                            "p90": int(row[1]),
                            "p99": int(row[2]),
                        }
                        if row
                        else {},
                        "llm": {
                            "p50": int(row[3]),
                            "p90": int(row[4]),
                            "p99": int(row[5]),
                        }
                        if row
                        else {},
                        "input_guardrail": {
                            "p50": int(row[6]),
                            "p90": int(row[7]),
                            "p99": int(row[8]),
                        }
                        if row
                        else {},
                        "output_guardrail": {
                            "p50": int(row[9]),
                            "p90": int(row[10]),
                            "p99": int(row[11]),
                        }
                        if row
                        else {},
                    }

                    # 7. Retry Loop Health & System Errors
                    cursor.execute(
                        f"""
                        SELECT
                            COUNT(*) as total_turns,
                            COUNT(CASE WHEN (snapshot->'ta_generation_phase'->>'attempts_count')::int > 1 THEN 1 END) as retry_turns
                        FROM tutor_turn_snapshots
                        WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                        {course_filter}
                    """,
                        params,
                    )
                    row = cursor.fetchone()
                    total_turns = row[0] if row else 0
                    retry_turns = row[1] if row else 0
                    retry_health_pct = (
                        round((retry_turns / total_turns * 100), 1)
                        if total_turns > 0
                        else 0.0
                    )

                    cursor.execute(
                        f"""
                        SELECT COUNT(*)
                        FROM tutor_turns
                        WHERE status = 'failed'
                        AND DATE((created_at AT TIME ZONE '{tz}')) = (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE
                        {course_filter}
                    """,
                        params,
                    )
                    row = cursor.fetchone()
                    system_errors = row[0] if row else 0

                    # 8. Models Used
                    cursor.execute(
                        f"""
                        SELECT
                            snapshot->'ta_generation_phase'->>'model_name' as model,
                            COUNT(*) as count
                        FROM tutor_turn_snapshots
                        WHERE created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                          AND snapshot->'ta_generation_phase'->>'model_name' IS NOT NULL
                          {course_filter}
                        GROUP BY model
                    """,
                        params,
                    )
                    model_rows = cursor.fetchall()
                    model_share = [
                        {"name": r[0] or "unknown", "value": r[1]} for r in model_rows
                    ]

                    # 9. Weekly Rewards & Nudges
                    cursor.execute(
                        f"""
                        WITH combined AS (
                            SELECT
                                created_at,
                                metadata->>'rewards_given' as r,
                                metadata->>'style_nudges' as n
                            FROM telemetry_events
                            WHERE event_type = 'out_of_band_telemetry'
                            AND created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                            {course_filter}
                        )
                        SELECT
                            TO_CHAR((created_at AT TIME ZONE '{tz}'), 'Dy') as day,
                            SUM(COALESCE(CAST(r AS INTEGER), 0)) as total_rewards,
                            SUM(COALESCE(CAST(n AS INTEGER), 0)) as total_style_nudges
                        FROM combined
                        GROUP BY DATE((created_at AT TIME ZONE '{tz}')), day
                        ORDER BY DATE((created_at AT TIME ZONE '{tz}')) ASC
                    """,
                        params,
                    )
                    rewards_rows = cursor.fetchall()

                    # 10. Weekly Engagement Metrics
                    cursor.execute(
                        f"""
                        WITH combined AS (
                            SELECT
                                created_at,
                                metadata->>'active_chat_seconds' as c,
                                metadata->>'active_editor_seconds' as e,
                                metadata->>'active_shell_seconds' as s
                            FROM telemetry_events
                            WHERE event_type = 'out_of_band_telemetry'
                            AND created_at >= (CURRENT_TIMESTAMP AT TIME ZONE '{tz}')::DATE - INTERVAL '6 days'
                            {course_filter}
                        )
                        SELECT
                            TO_CHAR((created_at AT TIME ZONE '{tz}'), 'Dy') as day,
                            SUM(COALESCE(CAST(c AS INTEGER), 0)) as chat_seconds,
                            SUM(COALESCE(CAST(e AS INTEGER), 0)) as editor_seconds,
                            SUM(COALESCE(CAST(s AS INTEGER), 0)) as terminal_seconds
                        FROM combined
                        GROUP BY DATE((created_at AT TIME ZONE '{tz}')), day
                        ORDER BY DATE((created_at AT TIME ZONE '{tz}')) ASC
                    """,
                        params,
                    )
                    engagement_rows = cursor.fetchall()

                    weekly_rewards = []
                    weekly_engagement = []

                    for i in range(6, -1, -1):
                        d = (datetime.now(pt_tz) - timedelta(days=i)).strftime("%a")
                        weekly_rewards.append(
                            {"day": d, "rewards_given": 0, "style_nudges": 0}
                        )
                        weekly_engagement.append(
                            {
                                "day": d,
                                "chat_seconds": 0,
                                "editor_seconds": 0,
                                "terminal_seconds": 0,
                            }
                        )

                    for row in rewards_rows:
                        day, r, n = row
                        for item in weekly_rewards:
                            if item["day"] == day:
                                item["rewards_given"] = r
                                item["style_nudges"] = n

                    for row in engagement_rows:
                        day, c, e, s = row
                        for item in weekly_engagement:
                            if item["day"] == day:
                                item["chat_seconds"] = c
                                item["editor_seconds"] = e
                                item["terminal_seconds"] = s

            return {
                "sessions_today": sessions_today,
                "requests_today": requests_today,
                "chat_seconds_today": chat_seconds,
                "editor_seconds_today": editor_seconds,
                "terminal_seconds_today": terminal_seconds,
                "total_rewards_given": total_rewards,
                "total_style_nudges": total_style_nudges,
                "weekly_rewards": weekly_rewards,
                "weekly_engagement": weekly_engagement,
                "session_data": session_data,
                "homework_keys": homework_keys,
                "study_keys": study_keys,
                "model_share": model_share,
                "guardrails": {
                    "input_blocks": input_blocks,
                    "output_blocks": output_blocks,
                    "input_dry_runs": input_dry_runs,
                    "output_dry_runs": output_dry_runs,
                    "violation_types": violation_types,
                },
                "latencies": latencies,
                "retry_health_pct": retry_health_pct,
                "system_errors": system_errors,
                "status": "ok",
            }
        except Exception as exc:
            import traceback

            traceback.print_exc()
            raise HTTPException(
                status_code=500, detail=f"Database query failed: {exc}"
            ) from exc

    @app.get(
        "/api/admin/dashboard/feedback",
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_dashboard_feedback(
        course_id: str | None = None,
        limit: int = 50,
        start_date: str | None = None,
        end_date: str | None = None,
        tz: str = "America/Los_Angeles",
    ):
        from rag_eng.telemetry import _connect_postgres
        from rag_eng.chat_log_export import _resolve_database_url

        database_url = _resolve_database_url(None)
        if not database_url:
            raise HTTPException(status_code=500, detail="No database URL configured.")

        try:
            with _connect_postgres(database_url, 5) as connection:
                with connection.cursor() as cursor:
                    course_filter = "AND course_id = %s" if course_id else ""
                    date_filter = ""
                    params_list = []
                    if course_id:
                        params_list.append(course_id)
                    if start_date:
                        date_filter += (
                            f" AND DATE((created_at AT TIME ZONE '{tz}')) >= %s"
                        )
                        params_list.append(start_date)
                    if end_date:
                        date_filter += (
                            f" AND DATE((created_at AT TIME ZONE '{tz}')) <= %s"
                        )
                        params_list.append(end_date)

                    params_list.append(limit)
                    params = tuple(params_list)

                    cursor.execute(
                        f"""
                        SELECT
                            session_id,
                            turn_index,
                            snapshot->'feedback'->>'thumbs_up' as rating,
                            snapshot->'feedback'->>'explanation' as explanation,
                            created_at,
                            COALESCE(snapshot->'student_phase'->>'raw_input', '') as student_message,
                            CASE
                                WHEN (snapshot->'ta_generation_phase'->'output_guardrail'->>'blocked')::boolean = true THEN
                                    '[BLOCKED: ' || COALESCE(snapshot->'ta_generation_phase'->'output_guardrail'->>'final_answer', '') || ']

' || COALESCE(snapshot->'ta_generation_phase'->'generation_history'->-1->>'raw_generation', '')
                                ELSE
                                    COALESCE(snapshot->'ta_generation_phase'->'generation_history'->-1->>'raw_generation', '')
                            END as ai_message,
                            snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys' as cot,
                            snapshot->'backend_retrieval_phase'->'retrieved_rag_chunks' as rag_sources
                        FROM tutor_turn_snapshots
                        WHERE snapshot->'feedback' IS NOT NULL
                        {course_filter}
                        {date_filter}
                        ORDER BY created_at DESC
                        LIMIT %s
                    """,
                        params,
                    )

                    rows = cursor.fetchall()
                    feedback_entries = []
                    for row in rows:
                        rag_files = row[8]
                        unique_sources = []
                        if rag_files and isinstance(rag_files, list):
                            for f_data in rag_files:
                                src = f_data.get("Source", f_data.get("source"))
                                if src and src not in unique_sources:
                                    unique_sources.append(src)

                        raw_ai_message = row[6] if row[6] else ""
                        clean_ai_message = re.sub(
                            r"<analysis>.*?</analysis>",
                            "",
                            raw_ai_message,
                            flags=re.DOTALL,
                        ).strip()

                        extracted_cot = (
                            row[7] if row[7] and isinstance(row[7], dict) else {}
                        )

                        feedback_entries.append(
                            {
                                "session_id": row[0],
                                "turn_index": row[1],
                                "rating": row[2],
                                "explanation": row[3],
                                "created_at": row[4].isoformat() if row[4] else None,
                                "student_message": row[5] if row[5] else None,
                                "ai_message": clean_ai_message
                                if clean_ai_message
                                else None,
                                "cot": extracted_cot,
                                "rag_sources": unique_sources,
                            }
                        )

            return {"feedback": feedback_entries, "status": "ok"}
        except Exception as exc:
            import traceback

            traceback.print_exc()
            raise HTTPException(
                status_code=500, detail=f"Database query failed: {exc}"
            ) from exc

    @app.get(
        "/api/student/dashboard/stats",
        dependencies=[Depends(require_student_surface_user)],
    )
    def student_dashboard_stats(
        course_id: Optional[str] = None,
        tz: str = "America/Los_Angeles",
        current_user: CurrentUser = Depends(require_student_surface_user),
    ):
        import pytz

        if tz not in pytz.all_timezones:
            raise HTTPException(status_code=400, detail="Invalid timezone")

        from rag_eng.app_registry import sync_application_user
        from rag_eng.telemetry import _connect_postgres
        from rag_eng.chat_log_export import _resolve_database_url

        app_user = sync_application_user(current_user)
        user_id = str(app_user["user_id"])

        database_url = _resolve_database_url(None)
        if not database_url:
            raise HTTPException(
                status_code=500, detail="No database URL configured for telemetry."
            )

        try:
            with _connect_postgres(database_url, 5) as connection:
                with connection.cursor() as cursor:
                    # Get available courses for this student
                    cursor.execute(
                        """
                        SELECT DISTINCT course_id
                        FROM tutor_turn_snapshots
                        WHERE app_user_id = %s AND course_id != ''
                    """,
                        (user_id,),
                    )
                    available_courses = [row[0] for row in cursor.fetchall()]

                    # If no course is specified, but there are multiple, maybe filter?
                    # For now, if course_id is provided, filter by it.
                    course_filter_sql = " AND course_id = %s " if course_id else ""
                    course_filter_params = [course_id] if course_id else []

                    # 1. Operational stats for student
                    cursor.execute(
                        """
                        SELECT
                            SUM(COALESCE(CAST(metadata->>'rewards_given' AS INTEGER), 0)) as total_rewards,
                            SUM(COALESCE(CAST(metadata->>'style_nudges' AS INTEGER), 0)) as total_style_nudges
                        FROM telemetry_events
                        WHERE event_type = 'out_of_band_telemetry'
                        AND app_user_id = %s
                        """ + course_filter_sql,
                        (user_id, *course_filter_params),
                    )
                    row = cursor.fetchone()
                    total_rewards = row[0] if row and row[0] else 0
                    total_style_nudges = row[1] if row and row[1] else 0

                    cursor.execute(
                        "SELECT COUNT(*) FROM tutor_turn_snapshots WHERE app_user_id = %s" + course_filter_sql,
                        (user_id, *course_filter_params),
                    )
                    row = cursor.fetchone()
                    requests_today = row[0] if row else 0

                    # 2. Cognitive Progression
                    cursor.execute(
                        """
                        SELECT
                            COALESCE('Week ' || (snapshot->'instructional_context_phase'->>'effective_week'), 'Week Unknown') as week,
                            COALESCE(INITCAP(REPLACE(SUBSTRING(snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys'->>'Cognitive_Stage' FROM '([a-zA-Z]{5,})'), '_', ' ')), 'Unknown') as stage,
                            COUNT(*) as count
                        FROM tutor_turn_snapshots
                        WHERE app_user_id = %s """ + course_filter_sql + """
                          AND snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys'->>'Cognitive_Stage' IS NOT NULL
                        GROUP BY week, stage
                    """,
                        (user_id, *course_filter_params),
                    )
                    cognitive_rows = cursor.fetchall()

                    # 3. Time Utilization
                    cursor.execute(
                        """
                        SELECT
                            COALESCE('Week ' || (s.snapshot->'instructional_context_phase'->>'effective_week'), 'Week Unknown') as assignment,
                            SUM(COALESCE(CAST(t.metadata->>'active_chat_seconds' AS INTEGER), 0)) as chat_seconds,
                            SUM(COALESCE(CAST(t.metadata->>'active_editor_seconds' AS INTEGER), 0)) as editor_seconds,
                            SUM(COALESCE(CAST(t.metadata->>'active_shell_seconds' AS INTEGER), 0)) as terminal_seconds
                        FROM telemetry_events t
                        LEFT JOIN tutor_turn_snapshots s ON t.turn_id = s.turn_id
                        WHERE t.event_type = 'out_of_band_telemetry'
                        AND t.app_user_id = %s
                        """ + course_filter_sql.replace('course_id', 't.course_id') + """
                        GROUP BY assignment
                    """,
                        (user_id, *course_filter_params),
                    )
                    time_rows = cursor.fetchall()

                    # 4. Pedagogical Actions
                    cursor.execute(
                        """
                        SELECT
                            COALESCE(INITCAP(REPLACE(SUBSTRING(snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys'->>'Cognitive_Stage' FROM '([a-zA-Z]{5,})'), '_', ' ')), 'Unknown') as stage,
                            COALESCE(INITCAP(REPLACE(SUBSTRING(snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys'->>'Pedagogical_Action' FROM '([A-Z_]{2,})'), '_', ' ')), 'None') as category,
                            COUNT(*) as count
                        FROM tutor_turn_snapshots
                        WHERE app_user_id = %s """ + course_filter_sql + """
                          AND snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys'->>'Pedagogical_Action' IS NOT NULL
                        GROUP BY stage, category
                    """,
                        (user_id, *course_filter_params),
                    )
                    pedagogical_rows = cursor.fetchall()
                    # 5. Frustration By Week
                    cursor.execute(
                        """
                        SELECT
                            COALESCE('Week ' || (snapshot->'instructional_context_phase'->>'effective_week'), 'Week Unknown') as week,
                            COALESCE(CAST(SUBSTRING(snapshot->'ta_generation_phase'->'generation_history'->-1->'cot_keys'->>'Escalation_State' FROM 'Frustration Level: ([0-9]+)') AS INTEGER), 1) as frustration,
                            COUNT(*) as count
                        FROM tutor_turn_snapshots
                        WHERE app_user_id = %s """ + course_filter_sql + """
                        GROUP BY week, frustration
                    """,
                        (user_id, *course_filter_params),
                    )
                    frustration_rows = cursor.fetchall()

            # Parse responses
            cognitive_data = [
                {"x": r[0], "stage_name": r[1], "count": r[2]} for r in cognitive_rows
            ]
            time_data = [
                {
                    "assignment": r[0],
                    "chat": r[1] / 3600.0,
                    "editor": r[2] / 3600.0,
                    "terminal": r[3] / 3600.0,
                }
                for r in time_rows
            ]
            pedagogical_data = [
                {"stage_name": r[0], "scaffold_name": r[1], "count": r[2]}
                for r in pedagogical_rows
            ]
            frustration_data = [
                {"week": r[0], "frustration": r[1], "queries": r[2]}
                for r in frustration_rows
            ]

            return {
                "available_courses": available_courses,
                "live_stats": {
                    "requests": requests_today,
                    "rewards": total_rewards,
                    "nudges": total_style_nudges,
                },
                "cognitive_progression": cognitive_data,
                "time_utilization": time_data,
                "pedagogical_actions": pedagogical_data,
                "frustration_by_week": frustration_data,
            }
        except Exception as exc:
            import traceback

            traceback.print_exc()
            raise HTTPException(
                status_code=500, detail=f"Database query failed: {exc}"
            ) from exc

    if _should_mount_gradio():
        from rag_eng.ui import mount_gradio_consoles

        return mount_gradio_consoles(app)

    return app
