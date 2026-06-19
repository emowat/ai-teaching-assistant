from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from rag_eng.api import create_app
from rag_eng.config import (
    InferenceConfig,
    ModelRouteConfig,
    OllamaInferenceConfig,
    OllamaOptions,
    SageMakerContextConfig,
    SageMakerGenerationConfig,
    SageMakerInferenceConfig,
)
from rag_eng.service import _extract_chat_context
from rag_eng.service import get_health
from rag_eng.service import run_chat, run_query
from rag_eng.telemetry import TraceContext
from rag.schemas import QueryInput
from rag.schemas import RetrievalResult


def test_extract_chat_context_defaults_week_and_empty_strings() -> None:
    ctx = _extract_chat_context(
        [{"role": "user", "content": "Why does my pointer segfault?"}]
    )

    assert ctx["student_message"] == "Why does my pointer segfault?"
    assert ctx["code_raw"] == ""
    assert ctx["terminal_output"] == ""
    assert ctx["week"] == 1
    assert ctx["mode"] == "Homework Assist"


def test_extract_chat_context_parses_extension_blocks() -> None:
    content = """[State_Tracking]
Mode: Study Assist
[Code_Context]
int* p;
[Terminal_Context]
Segmentation fault
Week: 4

[Student_Question]
Why does my pointer segfault?"""

    ctx = _extract_chat_context([{"role": "user", "content": content}])

    assert ctx["student_message"] == "Why does my pointer segfault?"
    assert "int* p" in ctx["code_raw"]
    assert "Segmentation fault" in ctx["terminal_output"]
    assert ctx["week"] == 4
    assert ctx["mode"] == "Study Assist"


def test_get_health_reports_course_registry_status_when_unconfigured(monkeypatch):
    class _FakeQdrantClient:
        def get_collections(self):
            return []

        def close(self):
            return None

    monkeypatch.setattr("rag_eng.service.get_settings", lambda: _health_settings())
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(rag_provider="cohere", chat_provider="ollama"),
    )
    monkeypatch.setattr(
        "rag_eng.service.create_qdrant_client",
        lambda: _FakeQdrantClient(),
    )
    monkeypatch.setattr(
        "rag_eng.service.get_course_registry_status",
        lambda: SimpleNamespace(
            configured=False,
            reachable=False,
            message="Aurora course registry is not configured; using local fallback.",
        ),
    )

    health = get_health()

    assert health.ready is True
    assert health.course_registry_configured is False
    assert health.course_registry_reachable is False


def test_get_health_marks_course_registry_unreachable_when_configured(monkeypatch):
    class _FakeQdrantClient:
        def get_collections(self):
            return []

        def close(self):
            return None

    monkeypatch.setattr("rag_eng.service.get_settings", lambda: _health_settings())
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(rag_provider="cohere", chat_provider="ollama"),
    )
    monkeypatch.setattr(
        "rag_eng.service.create_qdrant_client",
        lambda: _FakeQdrantClient(),
    )
    monkeypatch.setattr(
        "rag_eng.service.get_course_registry_status",
        lambda: SimpleNamespace(
            configured=True,
            reachable=False,
            message="Aurora course registry connectivity check failed: timeout",
        ),
    )

    health = get_health()

    assert health.ready is False
    assert health.course_registry_configured is True
    assert health.course_registry_reachable is False
    assert "Aurora course registry connectivity check failed" in health.message


def _runtime_config(*, rag_provider: str, chat_provider: str) -> InferenceConfig:
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
        rag=ModelRouteConfig(provider=rag_provider, model="gpt-5.4-mini"),
        chat=ModelRouteConfig(provider=chat_provider, model="gpt-5.4-mini"),
        openai_base_url="https://api.openai.com/v1",
    )


def _health_settings():
    return SimpleNamespace(
        qdrant_url="https://qdrant.example",
        qdrant_api_key="qdrant-key",
        qdrant_collection_name="mit13_course",
        qdrant_guidelines_collection_name="cpp_guidelines",
        qdrant_harvard_collection_name="cs50_course",
        cohere_api_key="cohere",
        openai_api_key="sk-test",
        openai_base_url="https://api.openai.com/v1",
        restart_command=None,
    )


class _FakeTelemetryStore:
    def __init__(self) -> None:
        self.started: list[TraceContext] = []
        self.events: list[dict[str, object]] = []
        self.finished: list[dict[str, object]] = []

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

    def finish_turn(self, trace, **kwargs):
        self.finished.append({"trace": trace, **kwargs})
        return True


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_chat_endpoint_accepts_simple_message(monkeypatch, client: TestClient) -> None:
    async def fake_run_chat(
        messages,
        model_name,
        settings,
        stream=False,
        course_id=None,
        session_id=None,
        request_id=None,
        turn_id=None,
        section_id=None,
        result_count=None,
        rerank_strategy=None,
    ):
        assert messages[0]["role"] == "user"
        assert course_id is None
        return {"message": {"content": "Try checking whether the pointer is initialized."}}

    monkeypatch.setattr("rag_eng.api.run_chat", fake_run_chat)

    response = client.post(
        "/api/chat",
        json={
            "model": "codingrabbit",
            "messages": [{"role": "user", "content": "Why does my pointer segfault?"}],
        },
    )

    assert response.status_code == 200
    assert "pointer" in response.json()["message"]["content"].lower()


def test_run_chat_forwards_course_id_to_query_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(rag_provider="cohere", chat_provider="openai"),
    )
    monkeypatch.setattr(
        "rag_eng.service.get_settings",
        lambda: SimpleNamespace(
            cohere_api_key="cohere",
            openai_api_key="sk-test",
            openai_base_url="https://api.openai.com/v1",
            sagemaker_inference_backend="vllm",
            sagemaker_endpoint="endpoint",
            sagemaker_poll_timeout_seconds=600,
            s3_data_bucket="bucket",
            aws_profile=None,
            aws_region="us-east-1",
            use_sagemaker=False,
            model_family="qwen",
        ),
    )
    fake_telemetry = _FakeTelemetryStore()
    monkeypatch.setattr(
        "rag_eng.service.get_telemetry_store",
        lambda: fake_telemetry,
    )
    captured: dict[str, object] = {}

    def fake_run_retrieval(query):
        captured["course_id"] = query.course_id
        captured["result_count"] = query.result_count
        captured["rerank_strategy"] = query.rerank_strategy
        return SimpleNamespace(formatted_context="[ctx]")

    monkeypatch.setattr("rag_eng.service.run_retrieval", fake_run_retrieval)
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
                    "content": "Mode: Homework Assist\nWeek: 1\n[Student_Question]\nWhy?",
                }
            ],
            model_name="codingrabbit",
            settings=SimpleNamespace(
                cohere_api_key="cohere",
                openai_api_key="sk-test",
                openai_base_url="https://api.openai.com/v1",
                sagemaker_inference_backend="vllm",
                sagemaker_endpoint="endpoint",
                sagemaker_poll_timeout_seconds=600,
                s3_data_bucket="bucket",
                aws_profile=None,
                aws_region="us-east-1",
                use_sagemaker=False,
                model_family="qwen",
            ),
            stream=False,
            course_id="mit14",
            result_count=8,
            rerank_strategy="mmr_0.7",
        )
    )

    assert response["message"]["content"] == "openai chat answer"
    assert captured["course_id"] == "mit14"
    assert captured["result_count"] == 8
    assert captured["rerank_strategy"] == "mmr_0.7"
    assert response["session_id"] == "chat-session"
    assert response["guardrail"]["action"] == "pass"
    assert fake_telemetry.started
    assert fake_telemetry.finished


def test_run_query_uses_openai_rag_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(rag_provider="openai", chat_provider="ollama"),
    )
    monkeypatch.setattr(
        "rag_eng.service.get_settings",
        lambda: SimpleNamespace(
            cohere_api_key=None,
            openai_api_key="sk-test",
            openai_base_url="https://api.openai.com/v1",
        ),
    )
    monkeypatch.setattr(
        "rag_eng.service.run_retrieval",
        lambda query: RetrievalResult(formatted_context="[ctx]"),
    )
    fake_telemetry = _FakeTelemetryStore()
    monkeypatch.setattr(
        "rag_eng.service.get_telemetry_store",
        lambda: fake_telemetry,
    )
    captured: dict[str, str] = {}

    def fake_invoke(prompt: str, config) -> str:
        captured["model"] = config.model
        captured["prompt"] = prompt
        return "openai answer"

    monkeypatch.setattr(
        "rag_eng.service.invoke_openai_chat_completion",
        fake_invoke,
    )

    result = run_query(
        QueryInput(
            student_message="Why does this crash?",
            week=1,
        )
    )

    assert result.answer == "openai answer"
    assert result.session_id == "query-session"
    assert result.request_id == "query-request"
    assert result.turn_id == "query-turn"
    assert captured["model"] == "gpt-5.4-mini"
    assert "Why does this crash?" in captured["prompt"]
    assert fake_telemetry.started
    assert fake_telemetry.finished


def test_run_chat_uses_openai_provider(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(rag_provider="cohere", chat_provider="openai"),
    )
    monkeypatch.setattr(
        "rag_eng.service.get_settings",
        lambda: SimpleNamespace(
            cohere_api_key="cohere",
            openai_api_key="sk-test",
            openai_base_url="https://api.openai.com/v1",
            sagemaker_inference_backend="vllm",
            sagemaker_endpoint="endpoint",
            sagemaker_poll_timeout_seconds=600,
            s3_data_bucket="bucket",
            aws_profile=None,
            aws_region="us-east-1",
            use_sagemaker=False,
            model_family="qwen",
        ),
    )
    monkeypatch.setattr(
        "rag_eng.service.run_retrieval",
        lambda query: SimpleNamespace(formatted_context="[ctx]"),
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
        },
    )
    fake_telemetry = _FakeTelemetryStore()
    monkeypatch.setattr(
        "rag_eng.service.get_telemetry_store",
        lambda: fake_telemetry,
    )

    captured: dict[str, object] = {}

    async def fake_openai(messages, config):
        captured["model"] = config.model
        captured["messages"] = messages
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
                    "content": "Mode: Homework Assist\nWeek: 1\n[Student_Question]\nWhy?",
                }
            ],
            model_name="codingrabbit",
            settings=SimpleNamespace(
                cohere_api_key="cohere",
                openai_api_key="sk-test",
                openai_base_url="https://api.openai.com/v1",
                sagemaker_inference_backend="vllm",
                sagemaker_endpoint="endpoint",
                sagemaker_poll_timeout_seconds=600,
                s3_data_bucket="bucket",
                aws_profile=None,
                aws_region="us-east-1",
                use_sagemaker=False,
                model_family="qwen",
            ),
            stream=False,
        )
    )

    assert response["message"]["content"] == "openai chat answer"
    assert captured["model"] == "gpt-5.4-mini"
    assert isinstance(captured["messages"], list)
    assert response["session_id"] == "chat-session"
    assert fake_telemetry.started
    assert fake_telemetry.finished


def test_run_chat_applies_guardrails_to_sagemaker_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(rag_provider="cohere", chat_provider="sagemaker"),
    )
    monkeypatch.setattr(
        "rag_eng.service.get_settings",
        lambda: SimpleNamespace(
            cohere_api_key="cohere",
            openai_api_key="sk-test",
            openai_base_url="https://api.openai.com/v1",
            sagemaker_inference_backend="vllm",
            sagemaker_endpoint="endpoint",
            sagemaker_poll_timeout_seconds=600,
            s3_data_bucket="bucket",
            aws_profile=None,
            aws_region="us-east-1",
            use_sagemaker=True,
            model_family="qwen",
        ),
    )
    monkeypatch.setattr(
        "rag_eng.service.run_retrieval",
        lambda query: SimpleNamespace(formatted_context="[ctx]"),
    )
    monkeypatch.setattr(
        "rag_eng.service.apply_all_guardrails",
        lambda answer, user_query, student_code, conversation_history: {
            "safe": False,
            "blocked": True,
            "violation_type": "v2_unsafe",
            "severity": "medium",
            "action": "replace",
            "evidence": "v2 score=0.835 > 0.7",
            "final_answer": "Guarded answer",
            "v2_score": 0.835,
            "stage": "v2",
        },
    )
    fake_telemetry = _FakeTelemetryStore()
    monkeypatch.setattr(
        "rag_eng.service.get_telemetry_store",
        lambda: fake_telemetry,
    )

    async def fake_run_inference(messages, model_name, settings, stream=False):
        return {"message": {"content": "draft answer"}}

    monkeypatch.setattr("rag_eng.service.run_inference", fake_run_inference)

    response = asyncio.run(
        run_chat(
            [
                {
                    "role": "user",
                    "content": "Mode: Homework Assist\nWeek: 1\n[Student_Question]\nWhy?",
                }
            ],
            model_name="codingrabbit",
            settings=SimpleNamespace(
                cohere_api_key="cohere",
                openai_api_key="sk-test",
                openai_base_url="https://api.openai.com/v1",
                sagemaker_inference_backend="vllm",
                sagemaker_endpoint="endpoint",
                sagemaker_poll_timeout_seconds=600,
                s3_data_bucket="bucket",
                aws_profile=None,
                aws_region="us-east-1",
                use_sagemaker=True,
                model_family="qwen",
            ),
            stream=False,
        )
    )

    assert response["message"]["content"] == "Guarded answer"
    assert response["guardrail"]["action"] == "replace"
    event_types = [event["event_type"] for event in fake_telemetry.events]
    assert "guardrail_started" in event_types
    assert "guardrail_finished" in event_types


def test_run_chat_streams_guardrailed_sagemaker_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        "rag_eng.service.get_inference_config",
        lambda: _runtime_config(rag_provider="cohere", chat_provider="sagemaker"),
    )
    monkeypatch.setattr(
        "rag_eng.service.get_settings",
        lambda: SimpleNamespace(
            cohere_api_key="cohere",
            openai_api_key="sk-test",
            openai_base_url="https://api.openai.com/v1",
            sagemaker_inference_backend="vllm",
            sagemaker_endpoint="endpoint",
            sagemaker_poll_timeout_seconds=600,
            s3_data_bucket="bucket",
            aws_profile=None,
            aws_region="us-east-1",
            use_sagemaker=True,
            model_family="qwen",
        ),
    )
    monkeypatch.setattr(
        "rag_eng.service.run_retrieval",
        lambda query: SimpleNamespace(formatted_context="[ctx]"),
    )
    monkeypatch.setattr(
        "rag_eng.service.apply_all_guardrails",
        lambda answer, user_query, student_code, conversation_history: {
            "safe": False,
            "blocked": True,
            "violation_type": "v2_unsafe",
            "severity": "medium",
            "action": "replace",
            "evidence": "v2 score=0.835 > 0.7",
            "final_answer": "Guarded answer",
            "v2_score": 0.835,
            "stage": "v2",
        },
    )
    fake_telemetry = _FakeTelemetryStore()
    monkeypatch.setattr(
        "rag_eng.service.get_telemetry_store",
        lambda: fake_telemetry,
    )

    async def fake_run_inference(messages, model_name, settings, stream=False):
        async def _gen():
            yield b'{"message":{"content":"draft answer"}}\n'

        return _gen()

    monkeypatch.setattr("rag_eng.service.run_inference", fake_run_inference)

    async def _collect() -> str:
        stream = await run_chat(
            [
                {
                    "role": "user",
                    "content": "Mode: Homework Assist\nWeek: 1\n[Student_Question]\nWhy?",
                }
            ],
            model_name="codingrabbit",
            settings=SimpleNamespace(
                cohere_api_key="cohere",
                openai_api_key="sk-test",
                openai_base_url="https://api.openai.com/v1",
                sagemaker_inference_backend="vllm",
                sagemaker_endpoint="endpoint",
                sagemaker_poll_timeout_seconds=600,
                s3_data_bucket="bucket",
                aws_profile=None,
                aws_region="us-east-1",
                use_sagemaker=True,
                model_family="qwen",
            ),
            stream=True,
        )

        chunks: list[str] = []
        async for chunk in stream:
            payload = json.loads(chunk.decode("utf-8").strip())
            chunks.append(payload["message"]["content"])
        return "".join(chunks)

    answer = asyncio.run(_collect())

    assert answer == "Guarded answer"
    event_types = [event["event_type"] for event in fake_telemetry.events]
    assert "guardrail_started" in event_types
    assert "guardrail_finished" in event_types
