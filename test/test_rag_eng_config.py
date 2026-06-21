from __future__ import annotations

from pathlib import Path

import pytest

from rag_eng.config import get_settings
from rag_eng.config import load_runtime_config, save_runtime_config, update_env_file
from rag_eng.schemas import ModelRouteConfig


def test_get_settings_uses_environment(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io")
    monkeypatch.setenv("QDRANT_API_KEY", "secret")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "capstone")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-secret")
    monkeypatch.setenv("APP_PORT", "9000")

    settings = get_settings()

    assert settings.qdrant_url == "https://example.qdrant.io"
    assert settings.qdrant_api_key == "secret"
    assert settings.qdrant_collection_name == "capstone"
    assert settings.cohere_api_key == "cohere-secret"
    assert settings.api_base_url == "http://127.0.0.1:9000"


def test_get_settings_reads_sagemaker_poll_timeout(monkeypatch) -> None:
    monkeypatch.setenv("SAGEMAKER_POLL_TIMEOUT_SECONDS", "900")

    settings = get_settings()

    assert settings.sagemaker_poll_timeout_seconds == 900


def test_runtime_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "runtime_config.yaml"
    payload = {
        "runtime": {
            "rag": {"provider": "openai", "model": "gpt-5.4-mini"},
            "chat": {"provider": "ollama", "model": "qwen3.5:9b"},
            "openai": {"base_url": "https://api.openai.com/v1"},
        }
    }

    save_runtime_config(payload, path)

    assert load_runtime_config(path) == payload


def test_model_route_config_allows_sagemaker_without_model() -> None:
    route = ModelRouteConfig(provider="sagemaker", model="")

    assert route.model == ""


def test_model_route_config_allows_bedrock() -> None:
    route = ModelRouteConfig(
        provider="bedrock",
        model="us.amazon.nova-2-lite-v1:0",
    )

    assert route.provider == "bedrock"
    assert route.model == "us.amazon.nova-2-lite-v1:0"


def test_model_route_config_requires_model_for_non_sagemaker() -> None:
    with pytest.raises(ValueError, match="model is required"):
        ModelRouteConfig(provider="openai", model="")


def test_update_env_file_preserves_comments_and_updates_values(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comment\nOPENAI_API_KEY=old\nOTHER=value\n",
        encoding="utf-8",
    )

    update_env_file(
        env_path,
        {
            "OPENAI_API_KEY": "new-secret",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
        },
    )

    text = env_path.read_text(encoding="utf-8")
    assert "# comment" in text
    assert "OPENAI_API_KEY=new-secret" in text
    assert "OPENAI_BASE_URL=https://api.openai.com/v1" in text
