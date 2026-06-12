"""FastAPI application for the AWS-ready RAG service."""

from __future__ import annotations

import uuid

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from rag_eng.auth.dependencies import require_authenticated_user
from rag_eng.auth.models import MeResponse
from rag_eng.config import Settings, get_settings
from rag_eng.schemas import (
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
    QueryPayload,
    QueryResult,
)
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
    messages: list[dict]
    stream: bool = False
    options: _ChatOptions = _ChatOptions()


def _require_admin(
    x_admin_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.admin_token and x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token.")


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
            raise HTTPException(status_code=500, detail=str(exc)) from exc

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
            )
            if payload.stream:
                return StreamingResponse(result, media_type="application/x-ndjson")
            return result
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app
