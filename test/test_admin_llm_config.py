from __future__ import annotations

from pathlib import Path

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
    load_runtime_config,
    save_runtime_config,
)


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
        chat=ModelRouteConfig(provider="ollama", model="qwen3.5:9b"),
        openai_base_url="https://api.openai.com/v1",
    )


def _client() -> TestClient:
    return TestClient(create_app())


def test_admin_get_llm_config(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("rag_eng.api.get_inference_config", _runtime_config)

    client = _client()
    response = client.get("/admin/llm/config", headers={"X-Admin-Token": "admin-token"})

    assert response.status_code == 200
    body = response.json()
    assert body["rag"]["provider"] == "openai"
    assert body["rag"]["model"] == "gpt-5.4-mini"
    assert body["openai_api_key_configured"] is True


def test_admin_save_llm_config(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("OPENAI_API_KEY", "old-secret")
    runtime_state = {"config": _runtime_config()}
    monkeypatch.setattr("rag_eng.api.get_inference_config", lambda: runtime_state["config"])

    captured: dict[str, object] = {}

    def _config_from_payload(data) -> InferenceConfig:
        runtime = data["runtime"]
        return InferenceConfig(
            ollama=runtime_state["config"].ollama,
            sagemaker=runtime_state["config"].sagemaker,
            rag=ModelRouteConfig(
                provider=runtime["rag"]["provider"],
                model=runtime["rag"]["model"],
            ),
            chat=ModelRouteConfig(
                provider=runtime["chat"]["provider"],
                model=runtime["chat"]["model"],
            ),
            openai_base_url=runtime["openai"]["base_url"],
        )

    def fake_save_runtime_config(data, path=None):
        captured["data"] = data
        captured["path"] = path
        runtime_state["config"] = _config_from_payload(data)

    def fake_update_env_file(path, updates):
        captured["env_path"] = path
        captured["updates"] = updates

    monkeypatch.setattr("rag_eng.api.save_runtime_config", fake_save_runtime_config)
    monkeypatch.setattr("rag_eng.api.update_env_file", fake_update_env_file)
    monkeypatch.setattr("rag_eng.api.reload_inference_config", lambda: runtime_state["config"])
    monkeypatch.setattr("rag_eng.api.get_runtime_config_path", lambda: tmp_path / "runtime_config.yaml")

    client = _client()
    response = client.post(
        "/admin/llm/config",
        headers={"X-Admin-Token": "admin-token"},
        json={
            "rag": {"provider": "openai", "model": "gpt-5.4-mini"},
            "chat": {"provider": "openai", "model": "gpt-5.4-mini"},
            "openai_api_key": "new-secret",
            "openai_base_url": "https://api.openai.com/v1",
        },
    )

    assert response.status_code == 200
    assert captured["data"]["runtime"]["rag"]["model"] == "gpt-5.4-mini"
    assert captured["updates"]["OPENAI_API_KEY"] == "new-secret"
    assert response.json()["chat"]["provider"] == "openai"


def test_admin_save_llm_config_allows_bedrock(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    runtime_state = {"config": _runtime_config()}
    monkeypatch.setattr("rag_eng.api.get_inference_config", lambda: runtime_state["config"])
    monkeypatch.setattr("rag_eng.api.get_runtime_config_path", lambda: tmp_path / "runtime_config.yaml")

    def fake_save_runtime_config(data, path=None):
        runtime = data["runtime"]
        runtime_state["config"] = InferenceConfig(
            ollama=runtime_state["config"].ollama,
            sagemaker=runtime_state["config"].sagemaker,
            rag=ModelRouteConfig(
                provider=runtime["rag"]["provider"],
                model=runtime["rag"]["model"],
            ),
            chat=ModelRouteConfig(
                provider=runtime["chat"]["provider"],
                model=runtime["chat"]["model"],
            ),
            openai_base_url=runtime["openai"]["base_url"],
        )

    monkeypatch.setattr("rag_eng.api.save_runtime_config", fake_save_runtime_config)
    monkeypatch.setattr("rag_eng.api.update_env_file", lambda path, updates: None)
    monkeypatch.setattr("rag_eng.api.reload_inference_config", lambda: runtime_state["config"])

    client = _client()
    response = client.post(
        "/admin/llm/config",
        headers={"X-Admin-Token": "admin-token"},
        json={
            "rag": {"provider": "bedrock", "model": "us.amazon.nova-2-lite-v1:0"},
            "chat": {"provider": "bedrock", "model": "us.anthropic.claude-sonnet-4-6"},
            "openai_api_key": None,
            "openai_base_url": "https://api.openai.com/v1",
        },
    )

    assert response.status_code == 200
    assert response.json()["rag"]["provider"] == "bedrock"
    assert response.json()["chat"]["provider"] == "bedrock"
    assert response.json()["chat"]["model"] == "us.anthropic.claude-sonnet-4-6"


def test_admin_save_llm_config_rejects_raw_bedrock_sonnet_model(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("OPENAI_API_KEY", "old-secret")
    monkeypatch.setattr("rag_eng.api.get_inference_config", _runtime_config)

    client = _client()
    response = client.post(
        "/admin/llm/config",
        headers={"X-Admin-Token": "admin-token"},
        json={
            "rag": {"provider": "bedrock", "model": "us.amazon.nova-2-lite-v1:0"},
            "chat": {"provider": "bedrock", "model": "anthropic.claude-sonnet-4-6"},
            "openai_api_key": None,
            "openai_base_url": "https://api.openai.com/v1",
        },
    )

    assert response.status_code == 422
    assert "inference profile ID" in response.text


def test_admin_save_llm_config_allows_sagemaker_without_model(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    runtime_state = {"config": _runtime_config()}
    monkeypatch.setattr("rag_eng.api.get_inference_config", lambda: runtime_state["config"])
    monkeypatch.setattr("rag_eng.api.get_runtime_config_path", lambda: tmp_path / "runtime_config.yaml")

    def fake_save_runtime_config(data, path=None):
        runtime = data["runtime"]
        runtime_state["config"] = InferenceConfig(
            ollama=runtime_state["config"].ollama,
            sagemaker=runtime_state["config"].sagemaker,
            rag=ModelRouteConfig(
                provider=runtime["rag"]["provider"],
                model=runtime["rag"]["model"],
            ),
            chat=ModelRouteConfig(
                provider=runtime["chat"]["provider"],
                model=runtime["chat"].get("model", ""),
            ),
            openai_base_url=runtime["openai"]["base_url"],
        )

    monkeypatch.setattr("rag_eng.api.save_runtime_config", fake_save_runtime_config)
    monkeypatch.setattr("rag_eng.api.update_env_file", lambda path, updates: None)
    monkeypatch.setattr("rag_eng.api.reload_inference_config", lambda: runtime_state["config"])

    client = _client()
    response = client.post(
        "/admin/llm/config",
        headers={"X-Admin-Token": "admin-token"},
        json={
            "rag": {"provider": "openai", "model": "gpt-5.4-mini"},
            "chat": {"provider": "sagemaker", "model": ""},
            "openai_api_key": None,
            "openai_base_url": "https://api.openai.com/v1",
        },
    )

    assert response.status_code == 200
    assert response.json()["chat"]["provider"] == "sagemaker"
    assert response.json()["chat"]["model"] == ""


def test_admin_save_llm_config_preserves_other_runtime_sections(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    runtime_path = tmp_path / "runtime_config.yaml"
    save_runtime_config(
        {
            "runtime": {
                "rag": {"provider": "cohere", "model": "command-xlarge-nightly"},
                "chat": {"provider": "ollama", "model": "qwen3.5:9b"},
                "openai": {"base_url": "https://api.openai.com/v1"},
                "input_guardrail_orchestration": {
                    "enabled": True,
                    "warning_threshold": 1,
                    "end_chat_threshold": 2,
                    "session_termination_enabled": True,
                    "penalty": {"enabled": True, "amount": 5},
                },
                "aurora_retry": {
                    "interactive": {
                        "connect_timeout_seconds": 3,
                        "max_attempts": 5,
                        "retry_sleep_seconds": 1.0,
                    },
                    "reliable": {
                        "connect_timeout_seconds": 3,
                        "max_attempts": 8,
                        "retry_sleep_seconds": 1.0,
                    },
                },
                "chat_log_export": {"prefix": "eval/chat_logs/turn_logs"},
            },
            "unrelated_section": {"keep": True},
        },
        runtime_path,
    )

    monkeypatch.setattr("rag_eng.api.get_runtime_config_path", lambda: runtime_path)
    monkeypatch.setattr("rag_eng.api.get_inference_config", _runtime_config)
    monkeypatch.setattr("rag_eng.api.reload_inference_config", lambda: _runtime_config())

    client = _client()
    response = client.post(
        "/admin/llm/config",
        headers={"X-Admin-Token": "admin-token"},
        json={
            "rag": {"provider": "openai", "model": "gpt-5.4-mini"},
            "chat": {"provider": "openai", "model": "gpt-5.4-mini"},
            "openai_api_key": None,
            "openai_base_url": None,
        },
    )

    assert response.status_code == 200
    merged = load_runtime_config(runtime_path)
    assert merged["unrelated_section"] == {"keep": True}
    assert merged["runtime"]["rag"]["provider"] == "openai"
    assert merged["runtime"]["input_guardrail_orchestration"]["warning_threshold"] == 1
    assert merged["runtime"]["aurora_retry"]["interactive"]["max_attempts"] == 5


def test_admin_restart_uses_restart_command(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("RESTART_COMMAND", "echo restart")
    monkeypatch.setattr("rag_eng.api.reload_inference_config", lambda: _runtime_config())

    captured: dict[str, object] = {}

    class FakePopen:
        def __init__(self, command, shell, start_new_session, cwd):
            captured["command"] = command
            captured["shell"] = shell
            captured["start_new_session"] = start_new_session
            captured["cwd"] = cwd

    monkeypatch.setattr("rag_eng.api.subprocess.Popen", FakePopen)

    client = _client()
    response = client.post("/admin/restart", headers={"X-Admin-Token": "admin-token"})

    assert response.status_code == 200
    assert response.json()["scheduled"] is True
    assert captured["command"] == "echo restart"
