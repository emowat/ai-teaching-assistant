from __future__ import annotations

from rag_eng.config import get_settings


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
