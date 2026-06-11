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
    qdrant_guidelines_collection_name: str
    cohere_api_key: str | None
    embedding_model: str
    app_host: str
    app_port: int
    gradio_port: int
    admin_token: str | None
    log_level: str
    raw_data_path: str
    cognito_region: str | None
    cognito_user_pool_id: str | None
    cognito_app_client_id: str | None
    cognito_issuer: str | None
    cognito_jwks_url: str | None
    runner_mode: str
    runner_image: str
    cors_origins: tuple[str, ...]

    @property
    def api_base_url(self) -> str:
        return f"http://127.0.0.1:{self.app_port}"

    @property
    def cognito_configured(self) -> bool:
        return bool(
            self.cognito_region
            and self.cognito_user_pool_id
            and self.cognito_app_client_id
        )


def get_settings() -> Settings:
    """Load settings from the environment."""
    repo_root = Path(__file__).resolve().parent.parent
    cognito_region = os.getenv("COGNITO_REGION")
    cognito_user_pool_id = os.getenv("COGNITO_USER_POOL_ID")
    cognito_app_client_id = os.getenv("COGNITO_APP_CLIENT_ID")
    cognito_issuer = os.getenv("COGNITO_ISSUER")
    cognito_jwks_url = os.getenv("COGNITO_JWKS_URL")

    if cognito_region and cognito_user_pool_id:
        if not cognito_issuer:
            cognito_issuer = (
                f"https://cognito-idp.{cognito_region}.amazonaws.com/"
                f"{cognito_user_pool_id}"
            )
        if not cognito_jwks_url:
            cognito_jwks_url = f"{cognito_issuer}/.well-known/jwks.json"

    return Settings(
        qdrant_url=os.getenv("QDRANT_URL"),
        qdrant_api_key=os.getenv("QDRANT_API_KEY"),
        qdrant_collection_name=os.getenv(
            "QDRANT_COLLECTION_NAME",
            "course_knowledge",
        ),
        qdrant_guidelines_collection_name=os.getenv(
            "QDRANT_GUIDELINES_COLLECTION_NAME",
            "cpp_guidelines",
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
        cognito_region=cognito_region,
        cognito_user_pool_id=cognito_user_pool_id,
        cognito_app_client_id=cognito_app_client_id,
        cognito_issuer=cognito_issuer,
        cognito_jwks_url=cognito_jwks_url,
        runner_mode=os.getenv("RUNNER_MODE", "docker"),
        runner_image=os.getenv("RUNNER_IMAGE", "codingrabbit-cpp-runner:0.1"),
        cors_origins=tuple(
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS",
                "http://localhost:5173",
            ).split(",")
            if origin.strip()
        ),
    )
