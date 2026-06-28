from __future__ import annotations

from pathlib import Path

import pytest

import rag_eng.config as rag_config
from rag_eng.config import get_settings
from rag_eng.config import (
    load_runtime_config,
    load_runtime_policy_config,
    save_runtime_config,
    update_env_file,
)
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


def test_get_settings_defaults_app_port_to_8001(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_URL", "https://example.qdrant.io")
    monkeypatch.setenv("QDRANT_API_KEY", "secret")
    monkeypatch.setenv("QDRANT_COLLECTION_NAME", "capstone")
    monkeypatch.setenv("COHERE_API_KEY", "cohere-secret")
    monkeypatch.delenv("APP_PORT", raising=False)

    settings = get_settings()

    assert settings.app_port == 8001
    assert settings.api_base_url == "http://127.0.0.1:8001"


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
            "chat_log_export": {
                "prefix": "eval/chat_logs/turn_logs",
                "bucket": "codingrabbit-data-dev",
                "connect_timeout_seconds": 3,
            },
        }
    }

    save_runtime_config(payload, path)

    assert load_runtime_config(path) == payload


def test_save_runtime_config_syncs_to_s3_when_configured(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime_config.yaml"
    payload = {
        "runtime": {
            "rag": {"provider": "openai", "model": "gpt-5.4-mini"},
            "chat": {"provider": "ollama", "model": "qwen3.5:9b"},
        }
    }

    class FakeS3Client:
        def __init__(self) -> None:
            self.put_calls: list[dict[str, object]] = []

        def put_object(self, **kwargs) -> None:
            self.put_calls.append(kwargs)

    fake_client = FakeS3Client()
    monkeypatch.setenv("RUNTIME_CONFIG_S3_URI", "s3://demo-bucket/config/runtime_config.yaml")
    monkeypatch.setattr(rag_config, "_build_s3_client", lambda: fake_client)

    save_runtime_config(payload, path)

    assert load_runtime_config(path) == payload
    assert fake_client.put_calls == [
        {
            "Bucket": "demo-bucket",
            "Key": "config/runtime_config.yaml",
            "Body": path.read_text(encoding="utf-8"),
            "ContentType": "text/yaml",
        }
    ]


def test_restore_runtime_config_from_s3_downloads_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime_config.yaml"
    payload = {
        "runtime": {
            "rag": {"provider": "bedrock", "model": "us.amazon.nova-2-lite-v1:0"},
            "chat": {"provider": "openai", "model": "gpt-5.4-mini"},
        }
    }

    class FakeS3Client:
        def __init__(self) -> None:
            self.download_calls: list[tuple[str, str, str]] = []

        def download_file(self, bucket: str, key: str, destination: str) -> None:
            self.download_calls.append((bucket, key, destination))
            Path(destination).write_text(
                "runtime:\n  rag:\n    provider: bedrock\n    model: us.amazon.nova-2-lite-v1:0\n  chat:\n    provider: openai\n    model: gpt-5.4-mini\n",
                encoding="utf-8",
            )

    fake_client = FakeS3Client()
    monkeypatch.setenv("RUNTIME_CONFIG_S3_URI", "s3://demo-bucket/config/runtime_config.yaml")
    monkeypatch.setattr(rag_config, "_build_s3_client", lambda: fake_client)

    restored = rag_config.restore_runtime_config_from_s3(path)

    assert restored is True
    assert fake_client.download_calls == [
        ("demo-bucket", "config/runtime_config.yaml", str(path))
    ]
    assert load_runtime_config(path) == payload


def test_load_runtime_policy_config_reads_nested_sections(tmp_path: Path) -> None:
    path = tmp_path / "runtime_config.yaml"
    payload = {
        "runtime": {
            "input_guardrail_orchestration": {
                "enabled": True,
                "warning_threshold": 3,
                "end_chat_threshold": 4,
                "session_termination_enabled": False,
                "penalty": {"enabled": False, "amount": 7},
            },
            "aurora_retry": {
                "interactive": {
                    "connect_timeout_seconds": 11,
                    "max_attempts": 2,
                    "retry_sleep_seconds": 0.5,
                },
                "reliable": {
                    "connect_timeout_seconds": 13,
                    "max_attempts": 4,
                    "retry_sleep_seconds": 0.25,
                },
            },
            "chat_log_export": {
                "prefix": "eval/custom",
                "bucket": "codingrabbit-data-dev",
                "connect_timeout_seconds": 11,
            },
        }
    }

    save_runtime_config(payload, path)

    policy = load_runtime_policy_config(path)

    assert policy.input_guardrail_orchestration.enabled is True
    assert policy.input_guardrail_orchestration.warning_threshold == 3
    assert policy.input_guardrail_orchestration.end_chat_threshold == 4
    assert policy.input_guardrail_orchestration.session_termination_enabled is False
    assert policy.input_guardrail_orchestration.penalty.enabled is False
    assert policy.input_guardrail_orchestration.penalty.amount == 7
    assert policy.aurora_retry.interactive.connect_timeout_seconds == 11
    assert policy.aurora_retry.interactive.max_attempts == 2
    assert policy.aurora_retry.interactive.retry_sleep_seconds == 0.5
    assert policy.aurora_retry.reliable.connect_timeout_seconds == 13
    assert policy.aurora_retry.reliable.max_attempts == 4
    assert policy.aurora_retry.reliable.retry_sleep_seconds == 0.25
    assert policy.chat_log_export.prefix == "eval/custom"
    assert policy.chat_log_export.bucket == "codingrabbit-data-dev"
    assert policy.chat_log_export.connect_timeout_seconds == 11


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


def test_model_route_config_rejects_raw_bedrock_sonnet_model() -> None:
    with pytest.raises(ValueError, match="inference profile ID"):
        ModelRouteConfig(
            provider="bedrock",
            model="anthropic.claude-sonnet-4-6",
        )


def test_model_route_config_requires_model_for_non_sagemaker() -> None:
    with pytest.raises(ValueError, match="model is required"):
        ModelRouteConfig(provider="openai", model="")


def test_load_inference_config_normalizes_legacy_bedrock_sonnet_model(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime_config.yaml"
    path.write_text(
        "runtime:\n"
        "  rag:\n"
        "    provider: openai\n"
        "    model: gpt-5.4-mini\n"
        "  chat:\n"
        "    provider: bedrock\n"
        "    model: anthropic.claude-sonnet-4-6\n"
        "  openai:\n"
        "    base_url: https://api.openai.com/v1\n",
        encoding="utf-8",
    )

    config = rag_config.load_inference_config(path)

    assert config.chat.provider == "bedrock"
    assert config.chat.model == "us.anthropic.claude-sonnet-4-6"


def test_load_inference_config_normalizes_legacy_bedrock_haiku_model(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime_config.yaml"
    path.write_text(
        "runtime:\n"
        "  rag:\n"
        "    provider: openai\n"
        "    model: gpt-5.4-mini\n"
        "  chat:\n"
        "    provider: bedrock\n"
        "    model: us.anthropic.claude-haiku-4-5\n"
        "  openai:\n"
        "    base_url: https://api.openai.com/v1\n",
        encoding="utf-8",
    )

    config = rag_config.load_inference_config(path)

    assert config.chat.provider == "bedrock"
    assert config.chat.model == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


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
