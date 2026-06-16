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
