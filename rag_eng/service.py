"""Thin orchestration layer for the AWS-ready RAG service."""

from __future__ import annotations

import logging
import json
import os
import re
import time
from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any, AsyncIterator

from rag import build_prompt, generate_response_from_result, run_retrieval
from rag.runtime import create_qdrant_client

from rag.course_registry import get_course_registry_status, get_course_registry

from rag_eng.config import Settings, get_inference_config, get_settings
from rag_eng.config import get_runtime_policy_config
from rag_eng.indexing import ensure_index, rebuild_index
from rag_eng.inference import run_inference
from rag_eng.llm_clients import (
    BedrockChatConfig,
    ainvoke_bedrock_chat_completion,
    OpenAIChatConfig,
    invoke_bedrock_chat_completion,
    ainvoke_openai_chat_completion,
    chunk_text,
    invoke_openai_chat_completion,
)
from rag_eng.prompts import get_system_prompt
from rag_eng.telemetry import (
    SessionOrchestrationState,
    TraceContext,
    TelemetryStore,
    get_telemetry_store,
)
from rag_eng.turn_snapshot import build_turn_snapshot
from input_guardrails.runtime import evaluate_input_guardrail
from input_guardrails.responses import repeated_violation_response, response_for
from output_guardrails.combined import apply_all_guardrails
from rag_eng.schemas import (
    HealthResponse,
    IndexEnsureResponse,
    IndexRebuildResponse,
    QueryPayload,
    QueryResponse,
)
from rag.schemas import RetrievalResult


logger = logging.getLogger(__name__)
_GUARDRAIL_MODEL_NAME = "codebert_v2_1"


class _PromptAdapter:
    """Simple sync adapter for prompt-based LLM calls."""

    def __init__(self, fn):
        self._fn = fn

    def invoke(self, prompt: str):
        return SimpleNamespace(content=self._fn(prompt))


def _build_bedrock_config(
    *,
    model_id: str,
    settings: Settings,
    temperature: float,
    top_p: float,
    max_tokens: int,
) -> BedrockChatConfig:
    """Create a Bedrock runtime config from the current app settings."""
    return BedrockChatConfig(
        region=settings.aws_region,
        model_id=model_id,
        timeout_seconds=120.0,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        profile_name=settings.aws_profile,
    )


def _bedrock_ready(settings: Settings) -> bool:
    """Return whether the app can create a Bedrock client with credentials."""
    import boto3

    try:
        session = boto3.Session(
            profile_name=settings.aws_profile or None,
            region_name=settings.aws_region,
        )
        return session.get_credentials() is not None
    except Exception:
        return False


def _trace_payload(trace: TraceContext) -> dict[str, Any]:
    """Return the public trace identifiers attached to chat/query responses."""
    return {
        "session_id": trace.session_id,
        "request_id": trace.request_id,
        "turn_id": trace.turn_id,
        "turn_index": trace.turn_index,
    }


def _chat_response_payload(answer: str, trace: TraceContext) -> dict[str, Any]:
    """Return the standard response payload for non-streaming chat calls."""
    return {"message": {"content": answer}, **_trace_payload(trace)}


def _chat_response_payload_with_guardrail(
    answer: str,
    trace: TraceContext,
    guardrail: dict[str, Any] | None,
    input_guardrail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _chat_response_payload(answer, trace)
    if guardrail is not None:
        payload["guardrail"] = guardrail
    if input_guardrail is not None:
        payload["input_guardrail"] = input_guardrail
    return payload


def _retrieval_summary(retrieval_result) -> dict[str, int]:
    """Summarize retrieval output without storing raw content."""
    return {
        "syllabus": 1 if getattr(retrieval_result, "syllabus", None) else 0,
        "strict_rules": len(getattr(retrieval_result, "strict_rules", []) or []),
        "pedagogical": len(getattr(retrieval_result, "pedagogical", []) or []),
        "supplementary": len(
            getattr(retrieval_result, "supplementary", []) or []
        ),
        "guidelines": len(getattr(retrieval_result, "guidelines", []) or []),
        "harvard": len(getattr(retrieval_result, "harvard", []) or []),
    }


def _guardrail_summary(guardrail_result: dict[str, Any]) -> dict[str, Any]:
    """Summarize guardrail output for telemetry and response metadata."""
    summary = {
        "guardrail_stage": guardrail_result.get("stage"),
        "guardrail_action": guardrail_result.get("action"),
        "guardrail_would_block": guardrail_result.get("wouldBlock"),
        "guardrail_violation_type": guardrail_result.get("violation_type"),
        "guardrail_severity": guardrail_result.get("severity"),
        "guardrail_evidence": guardrail_result.get("evidence"),
    }
    if guardrail_result.get("v2_score") is not None:
        summary["guardrail_v2_score"] = guardrail_result.get("v2_score")
    return summary


def _input_guardrail_summary(input_guardrail_result: dict[str, Any]) -> dict[str, Any]:
    """Summarize input guardrail output for telemetry and response metadata."""
    summary = {
        "input_guardrail_stage": input_guardrail_result.get("stage"),
        "input_guardrail_action": input_guardrail_result.get("action"),
        "input_guardrail_safe": input_guardrail_result.get("safe"),
        "input_guardrail_blocked": input_guardrail_result.get("blocked"),
        "input_guardrail_would_block": input_guardrail_result.get("wouldBlock"),
        "input_guardrail_violation_type": input_guardrail_result.get("violation_type"),
        "input_guardrail_severity": input_guardrail_result.get("severity"),
        "input_guardrail_evidence": input_guardrail_result.get("evidence"),
    }
    rules = input_guardrail_result.get("rules") or {}
    if isinstance(rules, dict):
        summary["input_guardrail_rule_action"] = rules.get("action")
        summary["input_guardrail_rule_flag_reason"] = rules.get("flag_reason")
        summary["input_guardrail_rule_confidence"] = rules.get("confidence")
        summary["input_guardrail_rule_latency_ms"] = rules.get("latency_ms")
    model = input_guardrail_result.get("model") or {}
    if isinstance(model, dict):
        summary["input_guardrail_model_enabled"] = model.get("enabled")
        summary["input_guardrail_model_available"] = model.get("available")
        summary["input_guardrail_model_decision"] = model.get("decision")
        summary["input_guardrail_model_score"] = model.get("score")
    return summary


def _policy_snapshot() -> dict[str, Any]:
    """Serialize the active input-guardrail orchestration policy."""
    return asdict(get_runtime_policy_config().input_guardrail_orchestration)


def _input_guardrail_flag_reason(input_guardrail_result: dict[str, Any] | None) -> str:
    rules = (input_guardrail_result or {}).get("rules") or {}
    if isinstance(rules, dict):
        flag_reason = rules.get("flag_reason")
        if flag_reason:
            return str(flag_reason)
    violation_type = (input_guardrail_result or {}).get("violation_type")
    return str(violation_type or "")


def _session_state_snapshot(state: SessionOrchestrationState) -> dict[str, Any]:
    return state.to_snapshot_dict()


def _build_orchestrator_context(
    *,
    input_guardrail_result: dict[str, Any] | None,
    state_before: SessionOrchestrationState,
    state_after: SessionOrchestrationState,
    action_taken: str,
    short_circuit_stage: str | None,
    response_source: str,
    policy_snapshot: dict[str, Any],
    answer: str,
) -> dict[str, Any]:
    return {
        "session_state_before": _session_state_snapshot(state_before),
        "session_state_after": _session_state_snapshot(state_after),
        "policy_snapshot": policy_snapshot,
        "input_guardrail_flag_reason": _input_guardrail_flag_reason(
            input_guardrail_result
        )
        or None,
        "response_source": response_source,
        "violation_count_before": state_before.adversarial_warnings,
        "violation_count_after": state_after.adversarial_warnings,
        "action_taken": action_taken,
        "short_circuit_stage": short_circuit_stage,
        "end_chat": state_after.terminated,
        "carrot_penalty_triggered": (
            state_after.terminated and not state_before.terminated
        ),
        "final_rendered_text": answer,
    }


def _maybe_handle_orchestrator_short_circuit(
    *,
    trace: TraceContext,
    telemetry_store: TelemetryStore,
    input_guardrail_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Resolve session-level warning state and short-circuit when needed."""
    policy = get_runtime_policy_config().input_guardrail_orchestration
    policy_snapshot = _policy_snapshot()
    state_before = telemetry_store.get_session_orchestration_state(trace.session_id)
    flag_reason = _input_guardrail_flag_reason(input_guardrail_result)

    if state_before.terminated:
        state_after = replace(
            state_before,
            last_flag_reason=flag_reason or state_before.last_flag_reason,
            last_action_taken="SESSION_ALREADY_TERMINATED",
        )
        answer = repeated_violation_response()
        action_taken = "SESSION_ALREADY_TERMINATED"
        short_circuit_stage = "session_state"
        response_source = "orchestrator"
    elif not policy.enabled:
        if not (input_guardrail_result or {}).get("blocked"):
            return None
        state_after = replace(
            state_before,
            last_flag_reason=flag_reason,
            last_action_taken="CANNED_WARNING",
        )
        answer = (input_guardrail_result or {}).get("final_answer") or response_for(
            flag_reason
        )
        action_taken = "CANNED_WARNING"
        short_circuit_stage = "input_guardrail"
        response_source = "input_guardrail"
    elif (input_guardrail_result or {}).get("blocked"):
        next_warning_count = state_before.adversarial_warnings + 1
        terminated = (
            policy.session_termination_enabled
            and next_warning_count >= policy.end_chat_threshold
        )
        state_after = replace(
            state_before,
            adversarial_warnings=next_warning_count,
            terminated=terminated,
            termination_reason=(
                "end_chat_threshold_reached" if terminated else ""
            ),
            last_flag_reason=flag_reason,
            last_action_taken=(
                "CANNED_END_CHAT" if terminated else "CANNED_WARNING"
            ),
        )
        if terminated:
            answer = repeated_violation_response()
            action_taken = "CANNED_END_CHAT"
            response_source = "orchestrator"
        else:
            answer = (input_guardrail_result or {}).get("final_answer") or response_for(
                flag_reason
            )
            action_taken = "CANNED_WARNING"
            response_source = "input_guardrail"
        short_circuit_stage = "input_guardrail"
    else:
        return None

    if state_after != state_before:
        telemetry_store.update_session_orchestration_state(trace.session_id, state_after)

    telemetry_store.record_event(
        trace,
        event_type="orchestrator_decision",
        stage="orchestrator",
        status="completed",
        model_provider="orchestrator",
        model_name="input_guardrail_orchestrator",
        metadata=_build_orchestrator_context(
            input_guardrail_result=input_guardrail_result,
            state_before=state_before,
            state_after=state_after,
            action_taken=action_taken,
            short_circuit_stage=short_circuit_stage,
            response_source=response_source,
            policy_snapshot=policy_snapshot,
            answer=answer,
        ),
    )
    return {
        "answer": answer,
        "orchestrator_context": _build_orchestrator_context(
            input_guardrail_result=input_guardrail_result,
            state_before=state_before,
            state_after=state_after,
            action_taken=action_taken,
            short_circuit_stage=short_circuit_stage,
            response_source=response_source,
            policy_snapshot=policy_snapshot,
            answer=answer,
        ),
        "session_terminated": state_after.terminated,
        "policy_snapshot": policy_snapshot,
    }


def _build_input_guardrail_context(query) -> tuple[str, str]:
    """Synthesize the input-guardrail model fields from a query."""
    course_topic = query.course_id or query.course_source.value
    assignment_context_bits = [
        f"course_source={query.course_source.value}",
        f"mode={query.mode.value}",
        f"week={query.week}",
    ]
    if query.section_id:
        assignment_context_bits.append(f"section_id={query.section_id}")
    if query.terminal_output:
        assignment_context_bits.append(
            f"terminal_output={query.terminal_output.strip()[:240]}"
        )
    return course_topic, " | ".join(assignment_context_bits)


def _run_input_guardrail(
    *,
    query,
    trace: TraceContext,
    telemetry_store: TelemetryStore,
) -> dict[str, Any]:
    """Evaluate the pre-RAG input guardrail and emit telemetry."""
    settings = get_settings()
    course_topic, assignment_context = _build_input_guardrail_context(query)
    started_at = time.perf_counter()
    base_metadata = {
        "source": trace.source,
        "mode": trace.mode,
        "week": trace.week,
        "course_id": trace.course_id,
        "course_source": trace.course_source,
        "student_message_chars": len(query.student_message or ""),
        "student_code_chars": len(query.code_raw or ""),
    }

    telemetry_store.record_event(
        trace,
        event_type="input_guardrail_started",
        stage="input_guardrail",
        status="started",
        model_provider="input_guardrail",
        model_name="codebert_v1",
        metadata=base_metadata,
    )

    try:
        result = evaluate_input_guardrail(
            student_message=query.student_message or "",
            student_code=query.code_raw or "",
            course_topic=course_topic,
            assignment_context=assignment_context,
            checkpoint_dir=getattr(
                settings,
                "input_guardrails_codebert_checkpoint_dir",
                None,
            ),
        )
        
        is_log_only = os.environ.get("GUARDRAILS_LOG_ONLY", "false").lower() == "true"
        if is_log_only:
            result["wouldBlock"] = result.get("blocked", False)
            result["blocked"] = False
            if result.get("action") == "block":
                result["action"] = "log_only"
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Input guardrail evaluation failed; continuing to RAG: %s", exc)
        result = {
            "stage": "input_guardrail_error",
            "action": "pass",
            "safe": True,
            "blocked": False,
            "violation_type": "input_guardrail_error",
            "severity": "low",
            "evidence": f"input guardrail error: {type(exc).__name__}",
            "final_answer": "",
            "version": "input_guardrail_error",
            "rules": {},
            "model": {
                "enabled": False,
                "available": False,
                "decision": "pass",
                "score": None,
                "pass_below": None,
                "block_above": None,
                "checkpoint_dir": getattr(
                    settings,
                    "input_guardrails_codebert_checkpoint_dir",
                    "",
                ),
            },
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
        }

    guardrail_status = (
        "blocked"
        if result.get("blocked")
        else "log_only"
        if result.get("action") == "log_only"
        else "passed"
    )
    telemetry_store.record_event(
        trace,
        event_type="input_guardrail_finished",
        stage="input_guardrail",
        status=guardrail_status,
        latency_ms=int((time.perf_counter() - started_at) * 1000),
        model_provider="input_guardrail",
        model_name="codebert_v1",
        metadata={
            **base_metadata,
            **_input_guardrail_summary(result),
        },
    )
    return result


def _persist_turn_snapshot(
    *,
    telemetry_store: TelemetryStore,
    trace: TraceContext,
    query,
    source: str,
    input_guardrail: dict[str, Any] | None,
    retrieval_result: RetrievalResult | None = None,
    generation_attempts: list[dict[str, Any]] | None = None,
    final_answer: str | None = None,
    retrieval_latency_ms: int | None = None,
    policy_snapshot: dict[str, Any] | None = None,
    orchestrator_context: dict[str, Any] | None = None,
) -> None:
    snapshot = build_turn_snapshot(
        trace=trace,
        query=query,
        source=source,
        input_guardrail=input_guardrail,
        retrieval_result=retrieval_result,
        generation_attempts=generation_attempts,
        final_answer=final_answer,
        retrieval_latency_ms=retrieval_latency_ms,
        policy_snapshot=policy_snapshot,
        orchestrator_context=orchestrator_context,
    )
    telemetry_store.record_turn_snapshot(trace, snapshot)


async def _collect_stream_answer(stream: AsyncIterator[bytes]) -> str:
    """Buffer NDJSON stream chunks into one assistant draft."""
    answer_parts: list[str] = []
    async for chunk in stream:
        try:
            decoded = chunk.decode("utf-8").strip()
            for line in decoded.splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                content = payload.get("message", {}).get("content")
                if isinstance(content, str):
                    answer_parts.append(content)
        except Exception:
            # Streaming telemetry should never interfere with the client stream.
            pass
    return "".join(answer_parts)


def _apply_pipeline_guardrails(
    *,
    trace: TraceContext,
    telemetry_store: TelemetryStore,
    answer: str,
    user_query: str,
    student_code: str,
    conversation_history: list[dict],
    retrieval_metadata: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Run output guardrails and emit telemetry without breaking the chat path."""
    telemetry_store.record_event(
        trace,
        event_type="guardrail_started",
        stage="guardrail",
        status="started",
        model_provider="guardrail",
        model_name=_GUARDRAIL_MODEL_NAME,
        metadata={
            **retrieval_metadata,
            "draft_answer_chars": len(answer),
            "conversation_turns": len(conversation_history),
        },
    )
    import re
    visible_answer = re.sub(r"<analysis>.*?</analysis>", "", answer, flags=re.DOTALL).strip()

    guardrail_started = time.perf_counter()
    try:
        guardrail = apply_all_guardrails(
            visible_answer,
            user_query,
            student_code,
            conversation_history,
        )
        
        is_log_only = os.environ.get("GUARDRAILS_LOG_ONLY", "false").lower() == "true"
        if is_log_only and guardrail.get("stage") == "v2":
            guardrail["wouldBlock"] = guardrail.get("blocked", False)
            guardrail["blocked"] = False
            if guardrail.get("action") == "replace":
                guardrail["action"] = "log_only"
                
        guardrail["evaluated_answer"] = visible_answer
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Guardrail evaluation failed; returning draft answer: %s", exc)
        guardrail = {
            "safe": True,
            "blocked": False,
            "violation_type": "guardrail_error",
            "severity": "low",
            "action": "pass",
            "evidence": f"guardrail error: {type(exc).__name__}",
            "final_answer": answer,
            "v2_score": None,
            "stage": "guardrail_error",
        }
        guardrail_status = "failed"
    else:
        guardrail_status = guardrail.get("action", "pass")

    # If the guardrail replaced the text, use its fallback. 
    # Otherwise, return the original answer (which includes the CoT).
    if guardrail_status in ("pass", "log_only"):
        final_answer = answer
        guardrail["final_answer"] = answer
    else:
        final_answer = guardrail.get("final_answer") or answer
    guardrail_latency_ms = int((time.perf_counter() - guardrail_started) * 1000)
    guardrail = {
        **guardrail,
        "latency_ms": guardrail_latency_ms,
    }
    telemetry_store.record_event(
        trace,
        event_type="guardrail_finished",
        stage="guardrail",
        status=guardrail_status,
        latency_ms=guardrail_latency_ms,
        model_provider="guardrail",
        model_name=_GUARDRAIL_MODEL_NAME,
        metadata={
            **retrieval_metadata,
            "draft_answer_chars": len(answer),
            "final_answer_chars": len(final_answer),
            **_guardrail_summary(guardrail),
        },
    )
    return final_answer, guardrail


async def _trace_stream_response(
    stream: AsyncIterator[bytes],
    *,
    telemetry_store: TelemetryStore,
    trace: TraceContext,
    stage_provider: str,
    model_name: str,
    started_at: float,
    llm_started_at: float,
    base_metadata: dict[str, Any],
) -> AsyncIterator[bytes]:
    """Proxy a streaming response while closing out telemetry when complete."""
    answer_parts: list[str] = []
    try:
        async for chunk in stream:
            try:
                decoded = chunk.decode("utf-8").strip()
                for line in decoded.splitlines():
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    content = payload.get("message", {}).get("content")
                    if isinstance(content, str):
                        answer_parts.append(content)
            except Exception:
                # Streaming telemetry should never interfere with the client stream.
                pass
            yield chunk
    except Exception as exc:
        telemetry_store.finish_turn(
            trace,
            status="failed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider=stage_provider,
            model_name=model_name,
            metadata={**base_metadata, "error": type(exc).__name__},
        )
        raise
    else:
        answer_text = "".join(answer_parts)
        llm_latency_ms = int((time.perf_counter() - llm_started_at) * 1000)
        telemetry_store.record_event(
            trace,
            event_type="llm_finished",
            stage="llm_inference",
            status="completed",
            latency_ms=llm_latency_ms,
            model_provider=stage_provider,
            model_name=model_name,
            metadata={**base_metadata, "answer_chars": len(answer_text)},
        )
        telemetry_store.finish_turn(
            trace,
            status="completed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider=stage_provider,
            model_name=model_name,
            answer_chars=len(answer_text),
            metadata={
                **base_metadata,
                "llm_latency_ms": llm_latency_ms,
                "answer_chars": len(answer_text),
            },
        )


async def _single_chunk_stream(payload: dict[str, Any]) -> AsyncIterator[bytes]:
    """Return a one-chunk NDJSON stream for short-circuited requests."""
    yield (json.dumps(payload) + "\n").encode("utf-8")


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

    if route.provider == "bedrock":
        config = _build_bedrock_config(
            model_id=route.model,
            settings=settings,
            temperature=0.3,
            top_p=0.9,
            max_tokens=2048,
        )
        return _PromptAdapter(
            lambda prompt: invoke_bedrock_chat_completion(
                [{"role": "user", "content": prompt}],
                config,
            )
        )

    raise ValueError(f"Unsupported RAG provider: {route.provider}")


def run_query(
    query,
    telemetry_store: TelemetryStore | None = None,
) -> QueryResponse:
    """Execute retrieval once, then generate the TA answer from that result."""
    if query.course_id:
        try:
            registry = get_course_registry()
            course_def = registry.get_course(query.course_id)
            if course_def:
                query.syllabus_matrix = course_def.syllabus_matrix
                query.style_guide = course_def.style_guide
        except Exception:
            pass

    telemetry_store = telemetry_store or get_telemetry_store()
    trace = telemetry_store.start_turn(query=query, source="query")
    runtime = get_inference_config()
    model_provider = runtime.rag.provider
    model_name = runtime.rag.model
    started_at = time.perf_counter()
    input_guardrail = _run_input_guardrail(
        query=query,
        trace=trace,
        telemetry_store=telemetry_store,
    )
    base_metadata = {
        "source": "query",
        "mode": str(query.mode.value),
        "week": query.week,
        "course_id": trace.course_id,
        "course_source": trace.course_source,
        "result_count": getattr(query, "result_count", None),
        "rerank_strategy": getattr(query, "rerank_strategy", None),
        **_input_guardrail_summary(input_guardrail),
    }
    policy_snapshot = _policy_snapshot()
    orchestration_result = _maybe_handle_orchestrator_short_circuit(
        trace=trace,
        telemetry_store=telemetry_store,
        input_guardrail_result=input_guardrail,
    )

    if orchestration_result is not None:
        answer = orchestration_result["answer"]
        telemetry_store.finish_turn(
            trace,
            status="completed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider="orchestrator",
            model_name="input_guardrail_orchestrator",
            answer_chars=len(answer),
            metadata={
                **base_metadata,
                "answer_chars": len(answer),
                "session_terminated": orchestration_result["session_terminated"],
            },
        )
        _persist_turn_snapshot(
            telemetry_store=telemetry_store,
            trace=trace,
            query=query,
            source="query",
            input_guardrail=input_guardrail,
            final_answer=answer,
            policy_snapshot=policy_snapshot,
            orchestrator_context=orchestration_result["orchestrator_context"],
        )
        return QueryResponse(
            answer=answer,
            retrieval_result=RetrievalResult(),
            formatted_context="",
            input_guardrail=input_guardrail,
            session_id=trace.session_id,
            request_id=trace.request_id,
            turn_id=trace.turn_id,
            turn_index=trace.turn_index,
        )

    telemetry_store.record_event(
        trace,
        event_type="retrieval_started",
        stage="retrieval",
        status="started",
        model_provider=model_provider,
        model_name=model_name,
        metadata=base_metadata,
    )

    try:
        retrieval_started = time.perf_counter()
        retrieval_result = run_retrieval(query)
        retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)
        telemetry_store.record_event(
            trace,
            event_type="retrieval_finished",
            stage="retrieval",
            status="completed",
            latency_ms=retrieval_latency_ms,
            model_provider=model_provider,
            model_name=model_name,
            metadata={**base_metadata, **_retrieval_summary(retrieval_result)},
        )

        telemetry_store.record_event(
            trace,
            event_type="llm_started",
            stage="llm_inference",
            status="started",
            model_provider=model_provider,
            model_name=model_name,
            metadata=base_metadata,
        )
        llm_started = time.perf_counter()
        llm = _build_llm()
        answer = generate_response_from_result(
            query=query,
            result=retrieval_result,
            llm=llm,
        )
        llm_latency_ms = int((time.perf_counter() - llm_started) * 1000)
        telemetry_store.record_event(
            trace,
            event_type="llm_finished",
            stage="llm_inference",
            status="completed",
            latency_ms=llm_latency_ms,
            model_provider=model_provider,
            model_name=model_name,
            metadata={**base_metadata, "answer_chars": len(answer)},
        )
        telemetry_store.finish_turn(
            trace,
            status="completed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider=model_provider,
            model_name=model_name,
            answer_chars=len(answer),
            metadata={
                **base_metadata,
                **_retrieval_summary(retrieval_result),
                "retrieval_latency_ms": retrieval_latency_ms,
                "llm_latency_ms": llm_latency_ms,
                "answer_chars": len(answer),
            },
        )
        _persist_turn_snapshot(
            telemetry_store=telemetry_store,
            trace=trace,
            query=query,
            source="query",
            input_guardrail=input_guardrail,
            retrieval_result=retrieval_result,
            generation_attempts=[{
                "model_provider": model_provider,
                "model_name": model_name,
                "llm_latency_ms": llm_latency_ms,
                "raw_generation": answer,
                "guardrail": None,
            }],
            final_answer=answer,
            retrieval_latency_ms=retrieval_latency_ms,
            policy_snapshot=policy_snapshot,
        )
        return QueryResponse(
            answer=answer,
            retrieval_result=retrieval_result,
            formatted_context=retrieval_result.formatted_context,
            input_guardrail=input_guardrail,
            session_id=trace.session_id,
            request_id=trace.request_id,
            turn_id=trace.turn_id,
            turn_index=trace.turn_index,
        )
    except Exception as exc:
        telemetry_store.finish_turn(
            trace,
            status="failed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider=model_provider,
            model_name=model_name,
            metadata={**base_metadata, "error": type(exc).__name__},
        )
        raise


def run_input_guardrail_diagnostic(query) -> dict[str, Any]:
    """Inspect the input guardrail and the current orchestration response."""
    telemetry_store = TelemetryStore(database_url=None)
    trace = telemetry_store.start_turn(query=query, source="diagnostic_input_guardrail")
    input_guardrail = _run_input_guardrail(
        query=query,
        trace=trace,
        telemetry_store=telemetry_store,
    )
    orchestration_result = _maybe_handle_orchestrator_short_circuit(
        trace=trace,
        telemetry_store=telemetry_store,
        input_guardrail_result=input_guardrail,
    )

    response: dict[str, Any] = {
        "diagnostic_source": "admin_diagnostic",
        "trace": _trace_payload(trace),
        "input_guardrail": input_guardrail,
        "blocked": bool(input_guardrail.get("blocked")),
        "final_answer": input_guardrail.get("final_answer") or "",
        "orchestrator_context": None,
    }
    if orchestration_result is not None:
        response["final_answer"] = orchestration_result["answer"]
        response["orchestrator_context"] = orchestration_result["orchestrator_context"]
    return response


def run_rag_diagnostic(query) -> dict[str, Any]:
    """Run the RAG stage without persisting telemetry."""
    telemetry_store = TelemetryStore(database_url=None)
    result = run_query(query, telemetry_store=telemetry_store)
    prompt_preview = build_prompt(query=query, result=result.retrieval_result)
    return {
        "diagnostic_source": "admin_diagnostic",
        "trace": {
            "session_id": result.session_id,
            "request_id": result.request_id,
            "turn_id": result.turn_id,
            "turn_index": result.turn_index,
        },
        "answer": result.answer,
        "retrieval_result": result.retrieval_result,
        "formatted_context": result.formatted_context,
        "prompt_preview": prompt_preview,
        "input_guardrail": result.input_guardrail,
    }


def run_output_guardrail_diagnostic(
    *,
    query,
    draft_answer: str,
    conversation_history: list[dict],
) -> dict[str, Any]:
    """Inspect the output guardrail without persisting telemetry."""
    telemetry_store = TelemetryStore(database_url=None)
    trace = telemetry_store.start_turn(query=query, source="diagnostic_output_guardrail")
    final_answer, guardrail = _apply_pipeline_guardrails(
        trace=trace,
        telemetry_store=telemetry_store,
        answer=draft_answer,
        user_query=query.student_message,
        student_code=query.code_raw,
        conversation_history=conversation_history,
        retrieval_metadata={},
    )
    return {
        "diagnostic_source": "admin_diagnostic",
        "trace": _trace_payload(trace),
        "draft_answer": draft_answer,
        "final_answer": final_answer,
        "guardrail": guardrail,
    }


async def run_pipeline_diagnostic(
    messages: list[dict],
    model_name: str,
    settings: Settings,
    stream: bool = False,
    course_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    turn_id: str | None = None,
    section_id: str | None = None,
    result_count: int | None = None,
    rerank_strategy: str | None = None,
) -> dict | AsyncIterator[bytes]:
    """Run the full pipeline without persisting any telemetry rows."""
    diagnostic_store = TelemetryStore(database_url=None)
    return await run_chat(
        messages=messages,
        model_name=model_name,
        settings=settings,
        stream=stream,
        course_id=course_id,
        session_id=session_id,
        request_id=request_id,
        turn_id=turn_id,
        section_id=section_id,
        result_count=result_count,
        rerank_strategy=rerank_strategy,
        telemetry_store=diagnostic_store,
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
    bedrock_configured = _bedrock_ready(settings)
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
        if provider == "bedrock":
            return bedrock_configured
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
        elif runtime.rag.provider == "bedrock":
            message = "AWS credentials for Bedrock are not configured."
    if message == "Ready." and not chat_ready:
        if runtime.chat.provider == "cohere":
            message = "Cohere API key is not configured."
        elif runtime.chat.provider == "openai":
            message = "OpenAI API key is not configured."
        elif runtime.chat.provider == "bedrock":
            message = "AWS credentials for Bedrock are not configured."

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
        bedrock_configured=bedrock_configured,
        qdrant_reachable=qdrant_reachable,
        course_registry_reachable=course_registry_status.reachable,
        cohere_reachable=cohere_configured,
        openai_reachable=openai_configured,
        bedrock_reachable=bedrock_configured,
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

    likely_paste = "Likely_Paste_Detected: true" in content
    
    pasted_char_count = 0
    if likely_paste:

        match = re.search(r"Pasted_Char_Count:\s*(\d+)", content)
        if match:
            pasted_char_count = int(match.group(1))

    clipboard_event = {"external_paste_detected": likely_paste, "pasted_char_count": pasted_char_count} if likely_paste else None

    def _extract_int(key: str) -> int:
        m = re.search(rf"{key}:\s*(\d+)", content)
        return int(m.group(1)) if m else 0

    engagement_metrics = {
        "active_editor_seconds": _extract_int("Active_Editor_Time_Sec"),
        "active_shell_seconds": _extract_int("Active_Shell_Time_Sec"),
        "active_chat_seconds": _extract_int("Active_Chat_Time_Sec"),
    }

    return {
        "student_message": student_message or content,
        "code_raw": code_raw,
        "terminal_output": terminal_output,
        "mode": mode,
        "week": week,
        "clipboard_event": clipboard_event,
        "engagement_metrics": engagement_metrics,
    }


async def _generate_llm_response(
    chat_route,
    base_api_messages,
    system_prompt,
    rag_context,
    ctx,
    runtime,
    settings,
    stream,
    model_name,
) -> tuple[str, list[dict], Any | None]:
    api_messages = list(base_api_messages)
    
    if chat_route.provider == "sagemaker":
        from rag_eng.prompt_budget import assemble_sagemaker_messages
        api_messages = assemble_sagemaker_messages(
            system_prompt,
            rag_context,
            api_messages,
            ctx["mode"],
            runtime.sagemaker,
        )
        result = await run_inference(api_messages, model_name, settings, stream=stream)
        if stream:
            return "", api_messages, result
        text = result["message"]["content"] if isinstance(result, dict) else str(result)
        return text, api_messages, None

    if chat_route.provider == "bedrock":
        config = _build_bedrock_config(
            model_id=chat_route.model,
            settings=settings,
            temperature=0.7,
            top_p=0.9,
            max_tokens=2048,
        )
        full_system = f"{system_prompt}\n{rag_context}"
        api_messages.insert(0, {"role": "system", "content": full_system})
        text = await ainvoke_bedrock_chat_completion(api_messages, config)
        return text, api_messages, None

    if chat_route.provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")
        config = OpenAIChatConfig(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or runtime.openai_base_url,
            model=chat_route.model,
            timeout_seconds=120.0,
            temperature=0.7,
            top_p=0.9,
        )
        full_system = f"{system_prompt}\n{rag_context}"
        api_messages.insert(0, {"role": "system", "content": full_system})
        text = await ainvoke_openai_chat_completion(api_messages, config)
        return text, api_messages, None

        
    raise ValueError(f"Unknown chat provider: {chat_route.provider}")


async def run_chat(
    messages: list[dict],
    model_name: str,
    settings: Settings,
    stream: bool = False,
    course_id: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    turn_id: str | None = None,
    turn_index: int | None = None,
    section_id: str | None = None,
    result_count: int | None = None,
    rerank_strategy: str | None = None,
    telemetry_store: TelemetryStore | None = None,
) -> dict | AsyncIterator[bytes]:
    """Full chat pipeline: context extraction -> RAG -> prompt assembly -> inference."""
    ctx = _extract_chat_context(messages)

    query_kwargs: dict[str, object] = {
        "student_message": ctx["student_message"],
        "code_raw": ctx["code_raw"],
        "terminal_output": ctx["terminal_output"],
        "mode": ctx["mode"],
        "week": ctx["week"],
        "clipboard_event": ctx["clipboard_event"],
        "engagement_metrics": ctx["engagement_metrics"],
        "course_id": course_id,
        "session_id": session_id,
        "request_id": request_id,
        "turn_id": turn_id,
        "turn_index": turn_index,
        "section_id": section_id,
    }

    if course_id:
        try:
            registry = get_course_registry()
            course_def = registry.get_course(course_id)
            if course_def:
                query_kwargs["syllabus_matrix"] = course_def.syllabus_matrix
                query_kwargs["style_guide"] = course_def.style_guide
        except Exception:
            pass

    if result_count is not None:
        query_kwargs["result_count"] = result_count
    if rerank_strategy is not None:
        query_kwargs["rerank_strategy"] = rerank_strategy

    query = QueryPayload(**query_kwargs)

    telemetry_store = telemetry_store or get_telemetry_store()
    trace = telemetry_store.start_turn(query=query, source="chat")
    runtime = get_inference_config()
    chat_route = runtime.chat
    telemetry_model_name = (
        model_name if chat_route.provider == "sagemaker" else chat_route.model
    )
    started_at = time.perf_counter()
    input_guardrail = _run_input_guardrail(
        query=query,
        trace=trace,
        telemetry_store=telemetry_store,
    )
    base_metadata = {
        "source": "chat",
        "mode": str(query.mode.value),
        "week": query.week,
        "course_id": trace.course_id,
        "course_source": trace.course_source,
        "result_count": getattr(query, "result_count", None),
        "rerank_strategy": getattr(query, "rerank_strategy", None),
        **_input_guardrail_summary(input_guardrail),
    }
    conversation_history = [
        message
        for message in messages[:-1]
        if message.get("role") in {"user", "assistant"}
    ]
    policy_snapshot = _policy_snapshot()
    orchestration_result = _maybe_handle_orchestrator_short_circuit(
        trace=trace,
        telemetry_store=telemetry_store,
        input_guardrail_result=input_guardrail,
    )

    if orchestration_result is not None:
        answer = orchestration_result["answer"]
        payload = _chat_response_payload_with_guardrail(
            answer,
            trace,
            None,
            input_guardrail=input_guardrail,
        )
        telemetry_store.finish_turn(
            trace,
            status="completed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider="orchestrator",
            model_name="input_guardrail_orchestrator",
            answer_chars=len(answer),
            metadata={
                **base_metadata,
                "answer_chars": len(answer),
                "session_terminated": orchestration_result["session_terminated"],
            },
        )
        _persist_turn_snapshot(
            telemetry_store=telemetry_store,
            trace=trace,
            query=query,
            source="chat",
            input_guardrail=input_guardrail,
            final_answer=answer,
            policy_snapshot=policy_snapshot,
            orchestrator_context=orchestration_result["orchestrator_context"],
        )
        if stream:
            return _single_chunk_stream(payload)
        return payload

    telemetry_store.record_event(
        trace,
        event_type="retrieval_started",
        stage="retrieval",
        status="started",
        model_provider=chat_route.provider,
        model_name=telemetry_model_name,
        metadata=base_metadata,
    )

    try:
        retrieval_started = time.perf_counter()
        retrieval_result = run_retrieval(query)
        retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)
        retrieval_metadata = {**base_metadata, **_retrieval_summary(retrieval_result)}
        telemetry_store.record_event(
            trace,
            event_type="retrieval_finished",
            stage="retrieval",
            status="completed",
            latency_ms=retrieval_latency_ms,
            model_provider=chat_route.provider,
            model_name=telemetry_model_name,
            metadata=retrieval_metadata,
        )

        rag_context = retrieval_result.formatted_context
        generation_attempts = []
        base_api_messages = [m for m in messages if m.get("role") != "system"]
        max_attempts = 2
        
        for attempt_idx in range(max_attempts):
            telemetry_store.record_event(
                trace,
                event_type="llm_started",
                stage="llm_inference",
                status="started",
                model_provider=chat_route.provider,
                model_name=telemetry_model_name,
                metadata=retrieval_metadata,
            )
            llm_started = time.perf_counter()
            
            raw_text, _, stream_result = await _generate_llm_response(
                chat_route,
                base_api_messages,
                get_system_prompt(ctx["mode"]),
                rag_context,
                ctx,
                runtime,
                settings,
                stream,
                telemetry_model_name,
            )
            
            if stream and stream_result:
                raw_text = await _collect_stream_answer(stream_result)
                
            answer, guardrail = _apply_pipeline_guardrails(
                trace=trace,
                telemetry_store=telemetry_store,
                answer=raw_text,
                user_query=ctx["student_message"],
                student_code=ctx["code_raw"],
                conversation_history=conversation_history,
                retrieval_metadata=retrieval_metadata,
            )
            
            llm_latency_ms = int((time.perf_counter() - llm_started) * 1000)
            
            telemetry_store.record_event(
                trace,
                event_type="llm_finished",
                stage="llm_inference",
                status="completed",
                latency_ms=llm_latency_ms,
                model_provider=chat_route.provider,
                model_name=telemetry_model_name,
                metadata={
                    **retrieval_metadata,
                    "answer_chars": len(answer),
                    **_guardrail_summary(guardrail),
                    **_input_guardrail_summary(input_guardrail),
                },
            )
            
            generation_attempts.append({
                "model_provider": chat_route.provider,
                "model_name": telemetry_model_name,
                "llm_latency_ms": llm_latency_ms,
                "raw_generation": raw_text,
                "guardrail": guardrail,
            })
            
            if guardrail.get("action") == "replace" and guardrail.get("violation_type") == "code_leakage" and attempt_idx < max_attempts - 1:
                # Self-correction prompt injected for the next iteration
                base_api_messages.append({"role": "assistant", "content": raw_text})
                base_api_messages.append({
                    "role": "user", 
                    "content": "Your previous response was rejected by safety guardrails due to code leakage. Please generate a new response that strictly adheres to the pedagogical rules, ensuring no direct code leakage."
                })
                continue
            
            # Break on success, or on hard fails (v2_unsafe, etc)
            break
            
        telemetry_store.finish_turn(
            trace,
            status="completed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider=chat_route.provider,
            model_name=telemetry_model_name,
            answer_chars=len(answer),
            metadata={
                **retrieval_metadata,
                "retrieval_latency_ms": retrieval_latency_ms,
                "llm_latency_ms": llm_latency_ms,
                "answer_chars": len(answer),
                **_guardrail_summary(guardrail),
                **_input_guardrail_summary(input_guardrail),
            },
        )
        
        _persist_turn_snapshot(
            telemetry_store=telemetry_store,
            trace=trace,
            query=query,
            source="chat",
            input_guardrail=input_guardrail,
            retrieval_result=retrieval_result,
            generation_attempts=generation_attempts,
            final_answer=answer,
            retrieval_latency_ms=retrieval_latency_ms,
            policy_snapshot=policy_snapshot,
        )
        
        if stream:
            return chunk_text(answer, runtime.sagemaker.streaming_chunk_size if chat_route.provider == "sagemaker" else 100)
            
        return _chat_response_payload_with_guardrail(
            answer,
            trace,
            guardrail,
            input_guardrail=input_guardrail,
        )
    except Exception as exc:
        telemetry_store.finish_turn(
            trace,
            status="failed",
            latency_ms=int((time.perf_counter() - started_at) * 1000),
            model_provider=chat_route.provider,
            model_name=telemetry_model_name,
            metadata={**base_metadata, "error": type(exc).__name__},
        )
        raise
