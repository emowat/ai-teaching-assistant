from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace

from rag_eng.chat_log_export import export_turn_snapshots_to_s3
from rag_eng.config import (
    InferenceConfig,
    ModelRouteConfig,
    OllamaInferenceConfig,
    OllamaOptions,
    SageMakerContextConfig,
    SageMakerGenerationConfig,
    SageMakerInferenceConfig,
)
from rag_eng.service import run_chat
from rag_eng.telemetry import SessionOrchestrationState, TraceContext


@dataclass
class _FakeS3Client:
    put_objects: list[dict[str, object]]

    def put_object(self, **kwargs):
        self.put_objects.append(kwargs)


@dataclass
class _FakeTelemetryStore:
    started: list[TraceContext]
    events: list[dict[str, object]]
    finished: list[dict[str, object]]
    snapshots: list[dict[str, object]]

    def start_turn(self, *, query, source: str, user_sub: str | None = None):
        trace = TraceContext(
            request_id=query.request_id or f"{source}-request",
            session_id=query.session_id or f"{source}-session",
            turn_id=query.turn_id or f"{source}-turn",
            turn_index=1,
            source=source,
            course_id=query.course_id or query.course_source.value,
            course_source=query.course_source.value,
            section_id=query.section_id,
            user_sub=user_sub,
            mode=str(query.mode.value),
            week=query.week,
            persisted=True,
        )
        self.started.append(trace)
        return trace

    def record_event(self, trace, **kwargs):
        self.events.append({"trace": trace, **kwargs})
        return True

    def get_session_orchestration_state(self, session_id: str):
        return SessionOrchestrationState()

    def update_session_orchestration_state(self, session_id: str, state):
        return True

    def finish_turn(self, trace, **kwargs):
        self.finished.append({"trace": trace, **kwargs})
        return True

    def record_turn_snapshot(self, trace, snapshot):
        self.snapshots.append({"trace": trace, "snapshot": snapshot})
        return True


def _runtime_config() -> InferenceConfig:
    return InferenceConfig(
        ollama=OllamaInferenceConfig(
            model="qwen3.5:9b",
            url="http://localhost:11434/api/chat",
            timeout_seconds=30.0,
            think=False,
            options=OllamaOptions(
                temperature=0.7,
                top_p=0.9,
                num_ctx=8192,
                num_predict=2048,
            ),
        ),
        sagemaker=SageMakerInferenceConfig(
            poll_interval_seconds=2.0,
            streaming_chunk_size=20,
            generation=SageMakerGenerationConfig(
                max_tokens=2048,
                temperature=0.7,
                top_p=0.9,
            ),
            context=SageMakerContextConfig(
                max_model_len=10240,
                reserved_output_tokens=2048,
                safety_tokens=128,
                chars_per_token=4.0,
            ),
        ),
        rag=ModelRouteConfig(provider="openai", model="gpt-5.4-mini"),
        chat=ModelRouteConfig(provider="openai", model="gpt-5.4-mini"),
        openai_base_url="https://api.openai.com/v1",
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        cohere_api_key="cohere",
        openai_api_key="sk-test",
        openai_base_url="https://api.openai.com/v1",
        sagemaker_inference_backend="vllm",
        sagemaker_endpoint="endpoint",
        sagemaker_poll_timeout_seconds=600,
        s3_data_bucket="codingrabbit-data-dev",
        aws_profile=None,
        aws_region="us-east-1",
        use_sagemaker=False,
        model_family="qwen",
        input_guardrails_codebert_checkpoint_dir="/tmp/input_guardrail",
    )


def _guardrail_pass_result() -> dict[str, object]:
    return {
        "stage": "input_guardrail",
        "action": "pass",
        "safe": True,
        "blocked": False,
        "violation_type": "none",
        "severity": "",
        "evidence": "rules passed",
        "final_answer": "",
        "latency_ms": 4,
        "rules": {
            "action": "PASS",
            "flag_reason": None,
            "confidence": 0.99,
            "processed_input": "How should I structure this loop?",
            "latency_ms": 1,
            "version": "input_guardrail_v1_rules",
        },
        "model": {
            "enabled": True,
            "available": True,
            "decision": "pass",
            "score": 0.12,
            "pass_below": 0.3,
            "block_above": 0.7,
            "checkpoint_dir": "/tmp/input_guardrail",
        },
    }


def test_full_pipeline_turn_snapshot_can_be_exported(monkeypatch) -> None:
    fake_telemetry = _FakeTelemetryStore(
        started=[],
        events=[],
        finished=[],
        snapshots=[],
    )
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(),
    )
    monkeypatch.setattr("rag_eng.service.get_settings", _settings)
    monkeypatch.setattr(
        "rag_eng.service.get_telemetry_store",
        lambda: fake_telemetry,
    )
    monkeypatch.setattr(
        "rag_eng.service.evaluate_input_guardrail",
        lambda **_kwargs: _guardrail_pass_result(),
    )
    monkeypatch.setattr(
        "rag_eng.service.run_retrieval",
        lambda query: SimpleNamespace(
            formatted_context="[ctx]",
            syllabus=None,
            strict_rules=[],
            pedagogical=[],
            supplementary=[],
            guidelines=[],
            harvard=[],
        ),
    )
    monkeypatch.setattr(
        "rag_eng.service.apply_all_guardrails",
        lambda answer, user_query, student_code, conversation_history: {
            "safe": True,
            "blocked": False,
            "violation_type": "none",
            "severity": "",
            "action": "pass",
            "evidence": "test pass",
            "final_answer": answer,
            "v2_score": 0.0,
            "stage": "v1+v2",
            "latency_ms": 5,
        },
    )

    async def fake_openai(messages, config):
        return "openai chat answer"

    monkeypatch.setattr(
        "rag_eng.service.ainvoke_openai_chat_completion",
        fake_openai,
    )

    response = asyncio.run(
        run_chat(
            [
                {
                    "role": "user",
                    "content": "Mode: Homework Assist\nWeek: 1\n[Student_Question]\nHow should I structure this loop?",
                }
            ],
            model_name="codingrabbit",
            settings=_settings(),
            stream=False,
            course_id="mit14",
            session_id="sess-1",
            request_id="req-1",
            turn_id="turn-1",
            section_id="week-1",
        )
    )

    assert response["message"]["content"] == "openai chat answer"
    assert len(fake_telemetry.snapshots) == 1
    snapshot = fake_telemetry.snapshots[0]["snapshot"]
    assert snapshot["trace"]["turn_id"] == "turn-1"
    assert snapshot["final_response"]["text"] == "openai chat answer"
    assert snapshot["student_phase"]["input_guardrail"]["blocked"] is False

    fake_s3 = _FakeS3Client(put_objects=[])

    def _query_turn_snapshots(*_args, **_kwargs):
        return [(datetime(2026, 6, 23, 19, 17, tzinfo=timezone.utc), snapshot)]

    monkeypatch.setattr(
        "rag_eng.chat_log_export._query_turn_snapshots",
        _query_turn_snapshots,
    )
    monkeypatch.setattr(
        "rag_eng.chat_log_export.boto3.Session",
        lambda **_kwargs: SimpleNamespace(client=lambda service_name: fake_s3),
    )

    exported = export_turn_snapshots_to_s3(
        database_url="postgresql://example",
        bucket="codingrabbit-data-dev",
        prefix="eval/chat_logs/turn_logs",
        start_date=date(2026, 6, 23),
        end_date=date(2026, 6, 23),
    )

    assert exported[0]["key"] == (
        "eval/chat_logs/turn_logs/course_id=mit14/date=2026-06-23/turn_snapshots.jsonl"
    )
    assert len(fake_s3.put_objects) == 1
    body_lines = fake_s3.put_objects[0]["Body"].decode("utf-8").strip().splitlines()
    exported_lines = [json.loads(line) for line in body_lines]
    assert exported_lines[0]["trace"]["turn_id"] == "turn-1"
    assert exported_lines[0]["final_response"]["text"] == "openai chat answer"
