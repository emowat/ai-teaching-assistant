"""FastAPI application for the AWS-ready RAG service."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from rag_eng.auth.cognito import verify_cognito_access_token
from rag_eng.auth.dependencies import require_authenticated_user
from rag_eng.auth.models import MeResponse
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
from rag_eng.config import (
    Settings,
    get_inference_config,
    get_runtime_config_path,
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
    AdminCourseCreate,
    AdminCourseUpdate,
    IngestionJobLaunchRequest,
    IngestionJobResponse,
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
    QueryPayload,
    QueryResult,
    RetrievalRerankStrategy,
    RestartResponse,
)
from rag_eng.ingestion_jobs import get_ingestion_job, launch_ingestion_job
from rag_eng.runner_client import RunnerError, run_cpp_job
from rag_eng.run_schemas import CompileRequest, CompileResponse
from rag_eng.service import (
    ensure_index_service,
    get_health,
    rebuild_index_service,
    run_chat,
    run_query,
)


class _ChatOptions(BaseModel):
    temperature: float = 0.7
    top_p: float = 0.9
    num_ctx: int = 8192
    num_predict: int = 2048


class ChatRequest(BaseModel):
    """Ollama-compatible chat request (sent by the VS Code extension)."""
    model: str = "codingrabbit-ta"
    course_id: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    turn_id: str | None = None
    section_id: str | None = None
    result_count: int = Field(default=8, ge=1, le=20)
    rerank_strategy: RetrievalRerankStrategy = "similarity"
    messages: list[dict]
    stream: bool = False
    options: _ChatOptions = _ChatOptions()


def _error_detail(exc: Exception) -> str:
    """Return a non-empty HTTP error message (httpx timeouts often str() to '')."""
    detail = str(exc).strip()
    if detail:
        return detail
    return type(exc).__name__


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

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing admin credentials.",
        )

    current_user = verify_cognito_access_token(credentials.credentials, settings)
    if current_user.primary_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for this operation.",
        )


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


def create_app() -> FastAPI:
    """Create the FastAPI app for the RAG service."""
    settings = get_settings()
    app = FastAPI(
        title="rag_eng",
        description="AWS-ready FastAPI layer for the capstone RAG pipeline.",
        version="0.1.0",
    )

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return get_health()

    @app.get("/me", response_model=MeResponse)
    def me(current_user=Depends(require_authenticated_user)) -> MeResponse:
        return MeResponse.from_current_user(current_user)

    @app.post("/query", response_model=QueryResult)
    def query(payload: QueryPayload) -> QueryResult:
        try:
            return run_query(payload)
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
        dependencies=[Depends(_require_admin)],
    )
    def admin_list_courses() -> list[AdminCourse]:
        try:
            return list_admin_courses()
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.get(
        "/admin/courses/{course_id}",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin)],
    )
    def admin_get_course(course_id: str) -> AdminCourse:
        try:
            return get_admin_course(course_id)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.post(
        "/admin/courses",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin)],
    )
    def admin_create_course(payload: AdminCourseCreate) -> AdminCourse:
        try:
            return create_admin_course(payload)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.patch(
        "/admin/courses/{course_id}",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin)],
    )
    def admin_update_course(course_id: str, payload: AdminCourseUpdate) -> AdminCourse:
        try:
            return update_admin_course(course_id, payload)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.post(
        "/admin/courses/{course_id}/aliases",
        response_model=AdminCourse,
        dependencies=[Depends(_require_admin)],
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
        dependencies=[Depends(_require_admin)],
    )
    def admin_delete_course_alias(course_id: str, alias: str) -> AdminCourse:
        try:
            return deactivate_admin_course_alias(course_id, alias)
        except Exception as exc:
            raise _course_admin_http_error(exc) from exc

    @app.post(
        "/admin/ingestion/launch",
        response_model=IngestionJobResponse,
        dependencies=[Depends(_require_admin)],
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
        dependencies=[Depends(_require_admin)],
    )
    def admin_get_ingestion_job(job_id: str) -> IngestionJobResponse:
        try:
            return get_ingestion_job(job_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get(
        "/admin/llm/config",
        response_model=AdminLlmConfigResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_get_llm_config() -> AdminLlmConfigResponse:
        return _runtime_config_payload()

    @app.post(
        "/admin/llm/config",
        response_model=AdminLlmConfigResponse,
        dependencies=[Depends(_require_admin_access)],
    )
    def admin_save_llm_config(payload: AdminLlmConfigUpdate) -> AdminLlmConfigResponse:
        runtime_path = get_runtime_config_path()
        runtime = get_inference_config()
        updated = {
            "runtime": {
                "rag": payload.rag.model_dump(),
                "chat": payload.chat.model_dump(),
                "openai": {
                    "base_url": (
                        payload.openai_base_url
                        if payload.openai_base_url is not None
                        else runtime.openai_base_url
                    ),
                },
            }
        }
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
        "/admin/restart",
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

    from rag_eng.ui import mount_gradio_consoles

    return mount_gradio_consoles(app)
