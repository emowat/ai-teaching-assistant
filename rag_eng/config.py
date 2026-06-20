"""Environment-driven configuration for the `rag_eng` service."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


load_dotenv()

_INFERENCE_CONFIG_PATH = Path(__file__).parent / "inference_config.yaml"
_RUNTIME_CONFIG_PATH = Path(__file__).parent / "runtime_config.yaml"


# ---------------------------------------------------------------------------
# Inference config (loaded from inference_config.yaml)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OllamaOptions:
    temperature: float
    top_p: float
    num_ctx: int
    num_predict: int


@dataclass(frozen=True)
class OllamaInferenceConfig:
    model: str
    url: str
    timeout_seconds: float
    think: bool
    options: OllamaOptions


@dataclass(frozen=True)
class SageMakerGenerationConfig:
    max_tokens: int
    temperature: float
    top_p: float


@dataclass(frozen=True)
class SageMakerContextConfig:
    """Must stay in sync with deploy/deployment.yaml SM_VLLM_MAX_MODEL_LEN after redeploy."""
    max_model_len: int
    reserved_output_tokens: int
    safety_tokens: int
    chars_per_token: float


@dataclass(frozen=True)
class SageMakerInferenceConfig:
    poll_interval_seconds: float
    streaming_chunk_size: int
    generation: SageMakerGenerationConfig
    context: SageMakerContextConfig


@dataclass(frozen=True)
class InferenceConfig:
    ollama: OllamaInferenceConfig
    sagemaker: SageMakerInferenceConfig
    rag: "ModelRouteConfig"
    chat: "ModelRouteConfig"
    openai_base_url: str


@dataclass(frozen=True)
class ModelRouteConfig:
    provider: str
    model: str


_BEDROCK_RAG_DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"
_BEDROCK_CHAT_DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"


def load_inference_config(path: Path | None = None) -> InferenceConfig:
    """Load runtime provider selections and legacy inference defaults."""
    if path is None:
        if _RUNTIME_CONFIG_PATH.exists():
            path = _RUNTIME_CONFIG_PATH
        else:
            path = _INFERENCE_CONFIG_PATH

    raw: dict = yaml.safe_load(path.read_text()) if path.exists() else {}
    raw = raw or {}

    ollama_raw = raw.get("ollama", {})
    options_raw = ollama_raw.get("options", {})

    model = os.getenv("OLLAMA_MODEL") or ollama_raw.get("model", "qwen3.5:9b")
    url = os.getenv("OLLAMA_URL") or ollama_raw.get("url", "http://localhost:11434/api/chat")

    ollama = OllamaInferenceConfig(
        model=model,
        url=url,
        timeout_seconds=float(ollama_raw.get("timeout_seconds", 900)),
        think=bool(ollama_raw.get("think", False)),
        options=OllamaOptions(
            temperature=float(options_raw.get("temperature", 0.7)),
            top_p=float(options_raw.get("top_p", 0.9)),
            num_ctx=int(options_raw.get("num_ctx", 8192)),
            num_predict=int(options_raw.get("num_predict", 2048)),
        ),
    )

    sm_raw = raw.get("sagemaker", {})
    gen_raw = sm_raw.get("generation", {})
    ctx_raw = sm_raw.get("context", {})
    sagemaker = SageMakerInferenceConfig(
        poll_interval_seconds=float(sm_raw.get("poll_interval_seconds", 2.0)),
        streaming_chunk_size=int(sm_raw.get("streaming_chunk_size", 20)),
        generation=SageMakerGenerationConfig(
            max_tokens=int(gen_raw.get("max_tokens", 2048)),
            temperature=float(gen_raw.get("temperature", 0.7)),
            top_p=float(gen_raw.get("top_p", 0.9)),
        ),
        context=SageMakerContextConfig(
            max_model_len=int(ctx_raw.get("max_model_len", 10240)),
            reserved_output_tokens=int(ctx_raw.get("reserved_output_tokens", 2048)),
            safety_tokens=int(ctx_raw.get("safety_tokens", 128)),
            chars_per_token=float(ctx_raw.get("chars_per_token", 4.0)),
        ),
    )

    runtime_raw = raw.get("runtime", raw)
    rag_raw = runtime_raw.get("rag", {})
    chat_raw = runtime_raw.get("chat", {})
    openai_raw = runtime_raw.get("openai", {})
    default_chat_provider = "sagemaker" if os.getenv("USE_SAGEMAKER", "false").lower() == "true" else "ollama"
    rag_provider = str(rag_raw.get("provider", "cohere"))
    chat_provider = str(chat_raw.get("provider", default_chat_provider))
    rag_default_model = (
        ""
        if rag_provider == "sagemaker"
        else "gpt-5.4-mini"
        if rag_provider == "openai"
        else _BEDROCK_RAG_DEFAULT_MODEL
        if rag_provider == "bedrock"
        else "command-xlarge-nightly"
    )
    chat_default_model = (
        ""
        if chat_provider == "sagemaker"
        else "gpt-5.4-mini"
        if chat_provider == "openai"
        else _BEDROCK_CHAT_DEFAULT_MODEL
        if chat_provider == "bedrock"
        else model
    )

    def _route_model(raw_value: object, default: str) -> str:
        value = "" if raw_value is None else str(raw_value).strip()
        return value if value else default

    return InferenceConfig(
        ollama=ollama,
        sagemaker=sagemaker,
        rag=ModelRouteConfig(
            provider=rag_provider,
            model=_route_model(rag_raw.get("model"), rag_default_model),
        ),
        chat=ModelRouteConfig(
            provider=chat_provider,
            model=_route_model(chat_raw.get("model"), chat_default_model),
        ),
        openai_base_url=str(openai_raw.get("base_url", "https://api.openai.com/v1")),
    )


_inference_config: InferenceConfig | None = None


def get_inference_config() -> InferenceConfig:
    """Return cached InferenceConfig (loaded once at first call)."""
    global _inference_config
    if _inference_config is None:
        _inference_config = load_inference_config()
    return _inference_config


def reload_inference_config() -> InferenceConfig:
    """Force a reload of the cached inference configuration."""
    global _inference_config
    _inference_config = load_inference_config()
    return _inference_config


def get_runtime_config_path() -> Path:
    return _RUNTIME_CONFIG_PATH


def load_runtime_config(path: Path | None = None) -> dict:
    """Load the editable runtime config file as plain YAML data."""
    p = path or _RUNTIME_CONFIG_PATH
    loaded = yaml.safe_load(p.read_text()) if p.exists() else {}
    return loaded or {}


def save_runtime_config(data: Mapping[str, object], path: Path | None = None) -> None:
    """Persist the editable runtime config file."""
    p = path or _RUNTIME_CONFIG_PATH
    p.write_text(yaml.safe_dump(dict(data), sort_keys=False))


def _read_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data

    for line in path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _format_env_line(key: str, value: str) -> str:
    if value == "":
        return f"{key}="
    if any(ch in value for ch in (" ", "#", '"', "'")):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'{key}="{escaped}"'
    return f"{key}={value}"


def update_env_file(path: Path, updates: Mapping[str, str | None]) -> None:
    """Update a .env file in place while preserving unrelated comments/keys."""
    existing_lines = path.read_text().splitlines() if path.exists() else []
    index_by_key: dict[str, int] = {}
    for idx, line in enumerate(existing_lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        index_by_key[key] = idx

    new_lines = list(existing_lines)
    for key, value in updates.items():
        if value is None:
            continue
        formatted = _format_env_line(key, value)
        if key in index_by_key:
            new_lines[index_by_key[key]] = formatted
        else:
            new_lines.append(formatted)

    path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    qdrant_url: str | None
    qdrant_api_key: str | None
    qdrant_collection_name: str
    qdrant_guidelines_collection_name: str
    qdrant_harvard_collection_name: str
    cohere_api_key: str | None
    openai_api_key: str | None
    openai_base_url: str
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
    restart_command: str | None

    # --- Inference routing ---
    use_sagemaker: bool
    sagemaker_endpoint: str
    sagemaker_inference_backend: str  # vllm | huggingface
    sagemaker_poll_timeout_seconds: int
    s3_data_bucket: str
    model_family: str          # llama3 | qwen | generic
    ollama_url: str
    aws_region: str
    aws_profile: str | None

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
        qdrant_harvard_collection_name=os.getenv(
            "QDRANT_HARVARD_COLLECTION_NAME",
            "harvard_cs50",
        ),
        cohere_api_key=os.getenv("COHERE_API_KEY"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
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
        restart_command=os.getenv("RESTART_COMMAND") or None,
        use_sagemaker=os.getenv("USE_SAGEMAKER", "false").lower() == "true",
        sagemaker_endpoint=os.getenv(
            "SAGEMAKER_ENDPOINT", "codingrabbit-sagemaker-async-endpoint"
        ),
        sagemaker_inference_backend=os.getenv("SAGEMAKER_INFERENCE_BACKEND", "vllm"),
        sagemaker_poll_timeout_seconds=int(
            os.getenv("SAGEMAKER_POLL_TIMEOUT_SECONDS", "600")
        ),
        s3_data_bucket=os.getenv("S3_DATA_BUCKET", "codingrabbit-data-dev"),
        model_family=os.getenv("MODEL_FAMILY", "llama3"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat"),
        aws_region=os.getenv("AWS_REGION", "us-east-1"),
        aws_profile=os.getenv("AWS_PROFILE") or None,
    )
