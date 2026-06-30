"""Build canonical per-turn evaluation snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rag.schemas import QueryInput, RetrievalResult

from rag_eng.telemetry import TraceContext

TURN_SNAPSHOT_SCHEMA_VERSION = "v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return dict(value)
    return value


def _request_context(query: QueryInput) -> dict[str, Any]:
    ast_features = _model_dump(query.ast_features)
    return {
        "mode": str(query.mode.value),
        "week": query.week,
        "active_file": getattr(query, "active_file", None),
        "terminal_output": query.terminal_output or "",
        "exit_code": query.exit_code,
        "ast_features": ast_features if isinstance(ast_features, dict) else {},
        "code_raw": query.code_raw or "",
    }


def _retrieved_rag_chunks(retrieval_result: RetrievalResult | None) -> list[dict[str, Any]]:
    if retrieval_result is None:
        return []

    chunks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for attr in ("syllabus", "strict_rules", "pedagogical", "supplementary", "guidelines", "harvard"):
        value = getattr(retrieval_result, attr, None)
        if not value:
            continue
        docs = value if isinstance(value, list) else [value]
        for doc in docs:
            chunk_id = getattr(doc, "chunk_id", None)
            if chunk_id:
                chunk_id_text = str(chunk_id)
                if chunk_id_text in seen:
                    continue
                seen.add(chunk_id_text)

            chunk_data = {
                "chunk_id": chunk_id_text if chunk_id else None,
                "label": attr.title(),
                "Source": str(
                    getattr(doc, "source_type", "") or getattr(doc, "source_domain", "")
                ),
                "Content": getattr(doc, "content", ""),
                "score": getattr(doc, "score", 0.0),
            }
            chunks.append(chunk_data)
    return chunks


def _retrieval_phase(
    retrieval_result: RetrievalResult | None,
    *,
    retrieval_latency_ms: int | None = None,
    rerank_strategy: str | None = None,
) -> dict[str, Any] | None:
    if retrieval_result is None:
        return None

    chunks = _retrieved_rag_chunks(retrieval_result)
    return {
        "latency_ms": retrieval_latency_ms,
        "doc_count": len(chunks),
        "rerank_strategy": rerank_strategy,
        "retrieved_rag_chunks": chunks,
    }


def _legacy_retrieval_phase(
    retrieval_phase: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if retrieval_phase is None:
        return None

    retrieved_chunk_ids = [
        str(chunk.get("chunk_id"))
        for chunk in retrieval_phase.get("retrieved_rag_chunks", [])
        if chunk.get("chunk_id")
    ]
    return {
        "latency_ms": retrieval_phase.get("latency_ms"),
        "doc_count": retrieval_phase.get("doc_count", 0),
        "rerank_strategy": retrieval_phase.get("rerank_strategy"),
        "retrieved_chunk_ids": retrieved_chunk_ids,
        "retrieved_rag_chunks": retrieval_phase.get("retrieved_rag_chunks", []),
    }


def _student_phase(
    query: QueryInput,
    input_guardrail: dict[str, Any] | None,
) -> dict[str, Any]:
    rules = (input_guardrail or {}).get("rules") or {}
    processed_input = None
    if isinstance(rules, dict):
        processed_input = rules.get("processed_input")

    if not processed_input:
        processed_input = (query.student_message or "").strip()

    return {
        "raw_input": query.student_message or "",
        "processed_input": processed_input,
        "input_guardrail": input_guardrail,
    }


def _extract_cot_keys(raw_generation: str) -> dict[str, str]:
    cot_dict = {}
    if "<analysis>" in raw_generation and "</analysis>" in raw_generation:
        cot_text = raw_generation.split("</analysis>")[0].replace("<analysis>", "").strip()
        for line in cot_text.split('\n'):
            line = line.strip()
            if line.startswith('- '):
                parts = line[2:].split(':', 1)
                if len(parts) == 2:
                    cot_dict[parts[0].strip()] = parts[1].strip()
    return cot_dict


def _ta_generation_phase(
    *,
    raw_generation: str | None,
    guardrail: dict[str, Any] | None,
    model_provider: str | None,
    model_name: str | None,
    llm_latency_ms: int | None,
) -> dict[str, Any] | None:
    if raw_generation is None:
        return None

    generation_history = [
        {
            "attempt_id": 1,
            "model_provider": model_provider,
            "model_name": model_name,
            "generation_latency_ms": llm_latency_ms,
            "cot_keys": _extract_cot_keys(raw_generation),
            "raw_generation": raw_generation,
            "output_guardrail": guardrail,
        }
    ]
    return {
        "attempts_count": 1,
        "generation_latency_ms": llm_latency_ms,
        "raw_generation": raw_generation,
        "output_guardrail": guardrail,
        "generation_history": generation_history,
    }


def _legacy_output_guardrail_phase(
    guardrail: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if guardrail is None:
        return None
    return {
        "stage": guardrail.get("stage"),
        "action": guardrail.get("action"),
        "blocked": guardrail.get("blocked"),
        "safe": guardrail.get("safe"),
        "violation_type": guardrail.get("violation_type"),
        "severity": guardrail.get("severity"),
        "evidence": guardrail.get("evidence"),
        "final_answer": guardrail.get("final_answer"),
        "latency_ms": guardrail.get("latency_ms"),
        "v2_score": guardrail.get("v2_score"),
    }


def _orchestrator_phase(
    *,
    input_guardrail: dict[str, Any] | None,
    guardrail: dict[str, Any] | None,
    final_answer: str,
    orchestrator_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if input_guardrail and input_guardrail.get("blocked"):
        phase = {
            "violation_count_before": None,
            "violation_count_after": None,
            "action_taken": "CANNED_WARNING",
            "short_circuit_stage": "input_guardrail",
            "end_chat": False,
            "carrot_penalty_triggered": False,
            "final_rendered_text": final_answer,
        }
        if orchestrator_context:
            phase.update(orchestrator_context)
        return phase

    if guardrail and guardrail.get("action") == "replace":
        phase = {
            "violation_count_before": None,
            "violation_count_after": None,
            "action_taken": "OUTPUT_GUARDRAIL_REPLACE",
            "short_circuit_stage": "output_guardrail",
            "end_chat": False,
            "carrot_penalty_triggered": False,
            "final_rendered_text": final_answer,
        }
        if orchestrator_context:
            phase.update(orchestrator_context)
        return phase

    if guardrail and guardrail.get("action") == "log_only":
        phase = {
            "violation_count_before": None,
            "violation_count_after": None,
            "action_taken": "OUTPUT_GUARDRAIL_LOG_ONLY",
            "short_circuit_stage": None,
            "end_chat": False,
            "carrot_penalty_triggered": False,
            "final_rendered_text": final_answer,
        }
        if orchestrator_context:
            phase.update(orchestrator_context)
        return phase

    phase = {
        "violation_count_before": None,
        "violation_count_after": None,
        "action_taken": "PASS_THROUGH",
        "short_circuit_stage": None,
        "end_chat": False,
        "carrot_penalty_triggered": False,
        "final_rendered_text": final_answer,
    }
    if orchestrator_context:
        phase.update(orchestrator_context)
    return phase


def _final_response_source(
    *,
    input_guardrail: dict[str, Any] | None,
    guardrail: dict[str, Any] | None,
    orchestrator_context: dict[str, Any] | None = None,
) -> str:
    if orchestrator_context:
        response_source = orchestrator_context.get("response_source")
        if response_source:
            return str(response_source)
    if input_guardrail and input_guardrail.get("blocked"):
        return "input_guardrail"
    if guardrail and guardrail.get("action") == "replace":
        return "output_guardrail"
    return "model"


def build_turn_snapshot(
    *,
    trace: TraceContext,
    query: QueryInput,
    source: str,
    input_guardrail: dict[str, Any] | None,
    retrieval_result: RetrievalResult | None = None,
    guardrail: dict[str, Any] | None = None,
    raw_generation: str | None = None,
    final_answer: str | None = None,
    model_provider: str | None = None,
    model_name: str | None = None,
    retrieval_latency_ms: int | None = None,
    llm_latency_ms: int | None = None,
    policy_snapshot: dict[str, Any] | None = None,
    orchestrator_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a versioned, eval-friendly snapshot for one tutoring turn."""
    final_text = final_answer
    if final_text is None:
        if guardrail and guardrail.get("action") == "replace":
            final_text = guardrail.get("final_answer") or ""
        elif input_guardrail and input_guardrail.get("blocked"):
            final_text = input_guardrail.get("final_answer") or ""
        else:
            final_text = raw_generation or ""

    backend_retrieval_phase = _retrieval_phase(
        retrieval_result,
        retrieval_latency_ms=retrieval_latency_ms,
        rerank_strategy=getattr(query, "rerank_strategy", None),
    )
    ta_generation_phase = _ta_generation_phase(
        raw_generation=raw_generation,
        guardrail=guardrail,
        model_provider=model_provider,
        model_name=model_name,
        llm_latency_ms=llm_latency_ms,
    )
    output_guardrail_phase = _legacy_output_guardrail_phase(guardrail)

    snapshot = {
        "session_id": trace.session_id,
        "turn_id": trace.turn_id,
        "schema_version": TURN_SNAPSHOT_SCHEMA_VERSION,
        "timestamp": _utc_now_iso(),
        "trace": {
            "request_id": trace.request_id,
            "session_id": trace.session_id,
            "turn_id": trace.turn_id,
            "turn_index": trace.turn_index,
            "source": source,
        },
        "student": {
            "user_sub": trace.user_sub,
            "role": "student",
        },
        "course": {
            "course_id": trace.course_id,
            "course_source": trace.course_source,
            "section_id": trace.section_id,
        },
        "ide_context": {
            "mode": str(query.mode.value),
            "active_file": getattr(query, "active_file", None),
            "ast_metadata": _model_dump(query.ast_features) if isinstance(_model_dump(query.ast_features), dict) else {},
            "clipboard_event": _model_dump(query.clipboard_event) if query.clipboard_event else None,
            "engagement_metrics": _model_dump(query.engagement_metrics) if query.engagement_metrics else None,
            "raw_code_snippet": query.code_raw or "",
            "terminal_context": f"Exit_Code: {query.exit_code}\nOutput: \"{query.terminal_output or ''}\"",
        },
        "student_phase": _student_phase(query, input_guardrail),
        "backend_retrieval_phase": backend_retrieval_phase,
        "retrieval_phase": _legacy_retrieval_phase(backend_retrieval_phase),
        "orchestrator_phase": _orchestrator_phase(
            input_guardrail=input_guardrail,
            guardrail=guardrail,
            final_answer=final_text,
            orchestrator_context=orchestrator_context,
        ),
        "ta_generation_phase": ta_generation_phase,
        "output_guardrail_phase": output_guardrail_phase,
        "final_response": {
            "text": final_text,
            "source": _final_response_source(
                input_guardrail=input_guardrail,
                guardrail=guardrail,
                orchestrator_context=orchestrator_context,
            ),
        },
    }
    if policy_snapshot is not None:
        snapshot["policy_snapshot"] = policy_snapshot
    return snapshot
