from __future__ import annotations

import boto3

from rag_eng.llm_clients import BedrockChatConfig
from rag_eng.llm_clients import invoke_bedrock_chat_completion


class _FakeClient:
    def __init__(self, captured: dict[str, object]):
        self._captured = captured

    def converse(self, **payload):
        self._captured["payload"] = payload
        return {"output": {"message": {"content": [{"text": "bedrock reply"}]}}}


class _FakeSession:
    def __init__(self, captured: dict[str, object]):
        self._captured = captured

    def client(self, service_name, **kwargs):
        self._captured["service_name"] = service_name
        self._captured["client_kwargs"] = kwargs
        return _FakeClient(self._captured)


def _config(model_id: str) -> BedrockChatConfig:
    return BedrockChatConfig(
        region="us-east-1",
        model_id=model_id,
        timeout_seconds=3.0,
        temperature=0.3,
        top_p=0.9,
        max_tokens=128,
        profile_name="codingrabbit-dev",
    )


def test_invoke_bedrock_chat_completion_omits_top_p_for_claude_sonnet_4_6(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: _FakeSession(captured))

    text = invoke_bedrock_chat_completion(
        [{"role": "user", "content": "Hello"}],
        _config("us.anthropic.claude-sonnet-4-6"),
    )

    assert text == "bedrock reply"
    assert captured["service_name"] == "bedrock-runtime"
    assert captured["payload"]["modelId"] == "us.anthropic.claude-sonnet-4-6"
    assert captured["payload"]["inferenceConfig"] == {
        "maxTokens": 128,
        "temperature": 0.3,
    }


def test_invoke_bedrock_chat_completion_omits_top_p_for_claude_haiku_4_5(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: _FakeSession(captured))

    text = invoke_bedrock_chat_completion(
        [{"role": "user", "content": "Hello"}],
        _config("us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    )

    assert text == "bedrock reply"
    assert captured["service_name"] == "bedrock-runtime"
    assert captured["payload"]["modelId"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    assert captured["payload"]["inferenceConfig"] == {
        "maxTokens": 128,
        "temperature": 0.3,
    }


def test_invoke_bedrock_chat_completion_keeps_top_p_for_other_models(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(boto3, "Session", lambda **kwargs: _FakeSession(captured))

    text = invoke_bedrock_chat_completion(
        [{"role": "user", "content": "Hello"}],
        _config("us.amazon.nova-2-lite-v1:0"),
    )

    assert text == "bedrock reply"
    assert captured["payload"]["inferenceConfig"] == {
        "maxTokens": 128,
        "temperature": 0.3,
        "topP": 0.9,
    }
