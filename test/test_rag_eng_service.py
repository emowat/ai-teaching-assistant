from __future__ import annotations

import asyncio
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
from rag_eng.service import run_chat, run_query
from rag.schemas import AssistMode, QueryInput
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


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app())


def test_chat_endpoint_accepts_simple_message(monkeypatch, client: TestClient) -> None:
    async def fake_run_chat(messages, model_name, settings, stream=False):
        assert messages[0]["role"] == "user"
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
    assert captured["model"] == "gpt-5.4-mini"
    assert "Why does this crash?" in captured["prompt"]


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
