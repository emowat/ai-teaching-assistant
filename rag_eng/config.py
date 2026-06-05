"""Environment-driven configuration for the `rag_eng` service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    qdrant_url: str | None
    qdrant_api_key: str | None
    qdrant_collection_name: str
    cohere_api_key: str | None
    embedding_model: str
    app_host: str
    app_port: int
    gradio_port: int
    admin_token: str | None
    log_level: str
    raw_data_path: str

    @property
    def api_base_url(self) -> str:
        return f"http://127.0.0.1:{self.app_port}"


def get_settings() -> Settings:
    """Load settings from the environment."""
    repo_root = Path(__file__).resolve().parent.parent
    return Settings(
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
        qdrant_collection_name=os.getenv(
            "QDRANT_COLLECTION_NAME",
            "course_knowledge",
        ),
        cohere_api_key=os.getenv("COHERE_API_KEY"),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL",
            "sentence-transformers/multi-qa-mpnet-base-dot-v1",
        ),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=int(os.getenv("APP_PORT", "8000")),
        gradio_port=int(os.getenv("GRADIO_PORT", "7860")),
        admin_token=os.getenv("ADMIN_TOKEN"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        raw_data_path=os.getenv("RAW_DATA_PATH", str(repo_root / "raw_data")),
    )
