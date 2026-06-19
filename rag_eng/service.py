"""Thin orchestration layer for the AWS-ready RAG service."""

from __future__ import annotations

import re
from types import SimpleNamespace
from typing import AsyncIterator

from rag import build_prompt, generate_response_from_result, run_retrieval
from rag.runtime import create_qdrant_client

from rag.course_registry import get_course_registry_status
from rag_eng.config import Settings, get_inference_config, get_settings
from rag_eng.indexing import ensure_index, rebuild_index
from rag_eng.inference import run_inference
from rag_eng.llm_clients import (
    OpenAIChatConfig,
    ainvoke_openai_chat_completion,
    chunk_text,
    invoke_openai_chat_completion,
)
from rag_eng.prompts import get_system_prompt
from rag_eng.schemas import (
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
    QueryPayload,
    QueryResponse,
)


class _PromptAdapter:
    """Simple sync adapter for prompt-based LLM calls."""

    def __init__(self, fn):
        self._fn = fn

    def invoke(self, prompt: str):
        return SimpleNamespace(content=self._fn(prompt))


def _build_llm():
    """Create the configured RAG chat model lazily."""
    settings = get_settings()
    route = get_inference_config().rag

    if route.provider == "cohere":
        from langchain_cohere import ChatCohere

        if not settings.cohere_api_key:
            raise ValueError("COHERE_API_KEY is not configured.")
        return ChatCohere(
            cohere_api_key=settings.cohere_api_key,
            model=route.model,
        )

    if route.provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        config = OpenAIChatConfig(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or get_inference_config().openai_base_url,
            model=route.model,
            timeout_seconds=120.0,
            temperature=0.3,
            top_p=0.9,
        )
        return _PromptAdapter(lambda prompt: invoke_openai_chat_completion(prompt, config))

    raise ValueError(f"Unsupported RAG provider: {route.provider}")


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
    runtime = get_inference_config()
    qdrant_configured = bool(
        settings.qdrant_url
        and settings.qdrant_api_key
        and settings.qdrant_collection_name
        and settings.qdrant_guidelines_collection_name
        and settings.qdrant_harvard_collection_name
    )
    cohere_configured = bool(settings.cohere_api_key)
    openai_configured = bool(settings.openai_api_key)
    course_registry_status = get_course_registry_status()
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

    def _provider_ready(provider: str) -> bool:
        if provider == "cohere":
            return cohere_configured
        if provider == "openai":
            return openai_configured
        if provider in {"ollama", "sagemaker"}:
            return True
        return False

    rag_ready = _provider_ready(runtime.rag.provider)
    chat_ready = _provider_ready(runtime.chat.provider)
    if message == "Ready." and not rag_ready:
        if runtime.rag.provider == "cohere":
            message = "Cohere API key is not configured."
        elif runtime.rag.provider == "openai":
            message = "OpenAI API key is not configured."
    if message == "Ready." and not chat_ready:
        if runtime.chat.provider == "cohere":
            message = "Cohere API key is not configured."
        elif runtime.chat.provider == "openai":
            message = "OpenAI API key is not configured."

    course_registry_ready = (
        not course_registry_status.configured or course_registry_status.reachable
    )
    if (
        message == "Ready."
        and course_registry_status.configured
        and not course_registry_status.reachable
    ):
        message = course_registry_status.message

    llm_ready = rag_ready and chat_ready
    ready = qdrant_configured and qdrant_reachable and llm_ready and course_registry_ready
    return HealthResponse(
        ready=ready,
        qdrant_configured=qdrant_configured,
        course_registry_configured=course_registry_status.configured,
        cohere_configured=cohere_configured,
        openai_configured=openai_configured,
        qdrant_reachable=qdrant_reachable,
        course_registry_reachable=course_registry_status.reachable,
        cohere_reachable=cohere_configured,
        openai_reachable=openai_configured,
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
    student_message = _block("Student_Question")
    if not student_message:
        student_message = re.sub(r"\[.*?\][\s\S]*?(?=\[|$)", "", content).strip()

    week_match = re.search(r"Week[:\s]+(\d+)", content, re.IGNORECASE)
    week = int(week_match.group(1)) if week_match else 1
    week = max(1, min(8, week))

    return {
        "student_message": student_message or content,
        "code_raw": code_raw,
        "terminal_output": terminal_output,
        "mode": mode,
        "week": week,
    }


async def run_chat(
    messages: list[dict],
    model_name: str,
    settings: Settings,
    stream: bool = False,
    course_id: str | None = None,
) -> dict | AsyncIterator[bytes]:
    """Full chat pipeline: context extraction -> RAG -> prompt assembly -> inference."""
    ctx = _extract_chat_context(messages)

    query = QueryPayload(
        student_message=ctx["student_message"],
        code_raw=ctx["code_raw"],
        terminal_output=ctx["terminal_output"],
        mode=ctx["mode"],
        week=ctx["week"],
        course_id=course_id,
    )

    retrieval_result = run_retrieval(query)
    rag_context = retrieval_result.formatted_context
    api_messages = [m for m in messages if m.get("role") != "system"]

    system_prompt = get_system_prompt(ctx["mode"])
    chat_route = get_inference_config().chat

    if chat_route.provider == "sagemaker":
        from rag_eng.prompt_budget import assemble_sagemaker_messages

        api_messages = assemble_sagemaker_messages(
            system_prompt,
            rag_context,
            api_messages,
            ctx["mode"],
            get_inference_config().sagemaker,
        )
        return await run_inference(api_messages, model_name, settings, stream=stream)

    if chat_route.provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        config = OpenAIChatConfig(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or get_inference_config().openai_base_url,
            model=chat_route.model,
            timeout_seconds=120.0,
            temperature=0.7,
            top_p=0.9,
        )
        full_system = f"{system_prompt}\n{rag_context}"
        api_messages.insert(0, {"role": "system", "content": full_system})
        text = await ainvoke_openai_chat_completion(api_messages, config)
        if stream:
            return chunk_text(text, get_inference_config().sagemaker.streaming_chunk_size)
        return {"message": {"content": text}}

    full_system = f"{system_prompt}\n{rag_context}"
    api_messages.insert(0, {"role": "system", "content": full_system})
    return await run_inference(api_messages, model_name, settings, stream=stream)
