"""
Load and document deploy/deployment.yaml.

Used by upload_model.py, deploy_sagemaker.py, and deploy/scripts/*.sh
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "deployment.yaml"

# Environment variable → dot-path in deployment.yaml
ENV_OVERRIDES: dict[str, str] = {
    "DRIVE_FOLDER_ID": "google_drive.folder_id",
    "AWS_REGION": "aws.region",
    "AWS_PROFILE": "aws.profile",
    "S3_DATA_BUCKET": "aws.s3_bucket",
    "MODEL_DATA_URI": "model_artifact.s3_uri",
    "SAGEMAKER_ENDPOINT": "sagemaker.endpoint_name",
    "SAGEMAKER_INSTANCE_TYPE": "sagemaker.instance_type",
    "SAGEMAKER_EXECUTION_ROLE_ARN": "sagemaker.execution_role_arn",
    "MODEL_FAMILY": "rag_eng.model_family",
    "SAGEMAKER_INFERENCE_BACKEND": "rag_eng.inference_backend",
    "RAG_ENG_ECS_CLUSTER": "rag_eng_ecs.cluster",
    "RAG_ENG_ECS_SERVICE_NAME": "rag_eng_ecs.service_name",
    "RAG_ENG_ECS_TASK_FAMILY": "rag_eng_ecs.task_family",
    "RAG_ENG_ECS_TASK_DEFINITION": "rag_eng_ecs.task_definition",
    "RAG_ENG_ECS_CONTAINER_NAME": "rag_eng_ecs.container_name",
    "RAG_ENG_ECS_LAUNCH_TYPE": "rag_eng_ecs.launch_type",
    "RAG_ENG_ECS_PLATFORM_VERSION": "rag_eng_ecs.platform_version",
    "RAG_ENG_ECS_ASSIGN_PUBLIC_IP": "rag_eng_ecs.assign_public_ip",
    "RAG_ENG_ECS_SUBNETS": "rag_eng_ecs.subnet_ids",
    "RAG_ENG_ECS_SECURITY_GROUPS": "rag_eng_ecs.security_group_ids",
    "RAG_ENG_ECS_ALB_SECURITY_GROUP_ID": "rag_eng_ecs.alb_security_group_id",
    "RAG_ENG_ECS_IMAGE_URI": "rag_eng_ecs.image_uri",
    "RAG_ENG_ECS_EXECUTION_ROLE_ARN": "rag_eng_ecs.execution_role_arn",
    "RAG_ENG_ECS_TASK_ROLE_ARN": "rag_eng_ecs.task_role_arn",
    "RAG_ENG_ECS_CPU": "rag_eng_ecs.cpu",
    "RAG_ENG_ECS_MEMORY": "rag_eng_ecs.memory",
    "RAG_ENG_ECS_CONTAINER_PORT": "rag_eng_ecs.container_port",
    "RAG_ENG_ECS_DESIRED_COUNT": "rag_eng_ecs.desired_count",
    "RAG_ENG_ECS_HEALTH_CHECK_PATH": "rag_eng_ecs.health_check_path",
    "RAG_ENG_ECS_HEALTH_CHECK_GRACE_PERIOD_SECONDS": (
        "rag_eng_ecs.health_check_grace_period_seconds"
    ),
    "RAG_ENG_ECS_LOG_GROUP": "rag_eng_ecs.log_group",
    "RAG_ENG_ECS_LOG_STREAM_PREFIX": "rag_eng_ecs.log_stream_prefix",
    "RAG_ENG_ECS_TARGET_GROUP_ARN": "rag_eng_ecs.target_group_arn",
    "GUARDRAILS_LOG_ONLY": "rag_eng_ecs.environment.GUARDRAILS_LOG_ONLY",
    "RAG_ENG_ECS_ENV_JSON": "rag_eng_ecs.environment",
    "RAG_ENG_ECS_SECRET_ARNS_JSON": "rag_eng_ecs.secret_arn_map",
    "EVALUATION_WORKER_ECS_CLUSTER": "evaluation_worker.cluster",
    "EVALUATION_WORKER_ECS_TASK_FAMILY": "evaluation_worker.task_family",
    "EVALUATION_WORKER_ECS_TASK_DEFINITION": "evaluation_worker.task_definition",
    "EVALUATION_WORKER_ECS_CONTAINER_NAME": "evaluation_worker.container_name",
    "EVALUATION_WORKER_ECS_LAUNCH_TYPE": "evaluation_worker.launch_type",
    "EVALUATION_WORKER_ECS_PLATFORM_VERSION": "evaluation_worker.platform_version",
    "EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP": "evaluation_worker.assign_public_ip",
    "EVALUATION_WORKER_ECS_SUBNETS": "evaluation_worker.subnet_ids",
    "EVALUATION_WORKER_ECS_SECURITY_GROUPS": "evaluation_worker.security_group_ids",
    "EVALUATION_WORKER_ECS_IMAGE_URI": "evaluation_worker.image_uri",
    "EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN": "evaluation_worker.execution_role_arn",
    "EVALUATION_WORKER_ECS_TASK_ROLE_ARN": "evaluation_worker.task_role_arn",
    "EVALUATION_WORKER_ECS_CPU": "evaluation_worker.cpu",
    "EVALUATION_WORKER_ECS_MEMORY": "evaluation_worker.memory",
    "EVALUATION_WORKER_ECS_LOG_GROUP": "evaluation_worker.log_group",
    "EVALUATION_WORKER_ECS_LOG_STREAM_PREFIX": "evaluation_worker.log_stream_prefix",
    "EVALUATION_WORKER_ECS_ENV_JSON": "evaluation_worker.environment",
    "EVALUATION_WORKER_ECS_SECRET_ARNS_JSON": "evaluation_worker.secret_arn_map",
    "FRONTEND_ENABLED": "frontend_web.enabled",
    "FRONTEND_APP_DIR": "frontend_web.app_dir",
    "FRONTEND_DIST_DIR": "frontend_web.dist_dir",
    "FRONTEND_BUCKET_NAME": "frontend_web.bucket_name",
    "FRONTEND_BUCKET_PREFIX": "frontend_web.bucket_prefix",
    "FRONTEND_DEFAULT_ROOT_OBJECT": "frontend_web.default_root_object",
    "FRONTEND_SPA_FALLBACK_PATH": "frontend_web.spa_fallback_path",
    "FRONTEND_PRICE_CLASS": "frontend_web.price_class",
    "FRONTEND_CLOUDFRONT_ALIASES": "frontend_web.cloudfront.aliases",
    "FRONTEND_CLOUDFRONT_DISTRIBUTION_ID": "frontend_web.cloudfront.distribution_id",
    "FRONTEND_CLOUDFRONT_CERTIFICATE_ARN": "frontend_web.cloudfront.certificate_arn",
    "FRONTEND_CLOUDFRONT_COMMENT": "frontend_web.cloudfront.comment",
    "FRONTEND_CLOUDFRONT_CREATE_OAC": "frontend_web.cloudfront.create_oac",
    "FRONTEND_CLOUDFRONT_INVALIDATION_PATHS": "frontend_web.cloudfront.invalidation_paths",
    "FRONTEND_CLOUDFRONT_API_PATH_PATTERNS": "frontend_web.cloudfront.api_path_patterns",
    "FRONTEND_CLOUDFRONT_ORIGIN_PROTOCOL_POLICY": "frontend_web.cloudfront.origin_protocol_policy",
    "FRONTEND_CLOUDFRONT_CACHE_STATIC_ASSETS": "frontend_web.cloudfront.cache_static_assets",
    "FRONTEND_CLOUDFRONT_CACHE_HTML_SECONDS": "frontend_web.cloudfront.cache_html_seconds",
    "VITE_API_BASE_URL": "frontend_web.build.vite_api_base_url",
    "VITE_COGNITO_DOMAIN": "frontend_web.build.vite_cognito_domain",
    "VITE_COGNITO_REDIRECT_URI": "frontend_web.build.vite_cognito_redirect_uri",
    "VITE_COGNITO_LOGOUT_URI": "frontend_web.build.vite_cognito_logout_uri",
    "FRONTEND_EXTRA_ENV_JSON": "frontend_web.build.extra_env",
    "DEPLOY_CONFIG": "_config_path",  # special: path only, not merged into tree
}


@dataclass
class GoogleDriveConfig:
    folder_id: str
    folder_url: str = ""


@dataclass
class LocalPathsConfig:
    download_dir: str
    tarball_path: str
    partial_file_suffixes: tuple[str, ...]


@dataclass
class AwsConfig:
    region: str
    profile: str | None
    s3_bucket: str


@dataclass
class ModelArtifactConfig:
    s3_key: str
    s3_uri: str | None

    def resolved_uri(self, bucket: str) -> str:
        if self.s3_uri:
            return self.s3_uri
        return f"s3://{bucket}/{self.s3_key}"


@dataclass
class ScaleFromZeroAlarmConfig:
    """CloudWatch alarm on HasBacklogWithoutCapacity (queue > 0, instances = 0)."""

    period_seconds: int
    evaluation_periods: int
    datapoints_to_alarm: int


@dataclass
class AutoScalingConfig:
    enabled: bool
    variant_name: str
    min_capacity: int
    max_capacity: int
    target_backlog_per_instance: float
    scale_in_cooldown_seconds: int
    scale_out_cooldown_seconds: int
    scale_from_zero_cooldown_seconds: int
    scale_from_zero_alarm: ScaleFromZeroAlarmConfig


@dataclass
class AsyncInferenceConfig:
    output_s3_prefix: str
    max_concurrent_invocations_per_instance: int
    invoke_poll_interval_seconds: int
    invoke_poll_max_attempts: int
    deploy_wait_delay_seconds: int
    deploy_wait_max_attempts: int


@dataclass
class DlcConfig:
    account_id: str
    repository: str
    tag: str

    def image_uri(self, region: str) -> str:
        return f"{self.account_id}.dkr.ecr.{region}.amazonaws.com/{self.repository}:{self.tag}"


@dataclass
class ContainerConfig:
    inference_backend: str
    hf_task: str
    model_server_workers: str
    extra_env: dict[str, str]

    def as_env_dict(self) -> dict[str, str]:
        env = {str(k): str(v) for k, v in self.extra_env.items()}
        if self.inference_backend == "huggingface":
            env["HF_TASK"] = self.hf_task
            env["SAGEMAKER_MODEL_SERVER_WORKERS"] = self.model_server_workers
        return env


@dataclass
class RuntimeIoConfig:
    input_s3_prefix: str


@dataclass
class SageMakerConfig:
    endpoint_name: str
    instance_type: str
    initial_instance_count: int
    execution_role_arn: str | None
    inference_ami_version: str | None
    autoscaling: AutoScalingConfig
    async_inference: AsyncInferenceConfig
    dlc: DlcConfig
    container: ContainerConfig
    runtime_io: RuntimeIoConfig

    def model_name(self) -> str:
        return f"{self.endpoint_name}-model"

    def config_name(self) -> str:
        return f"{self.endpoint_name}-config"

    def async_output_uri(self, bucket: str) -> str:
        prefix = self.async_inference.output_s3_prefix.rstrip("/")
        return f"s3://{bucket}/{prefix}/"

    def autoscaling_resource_id(self) -> str:
        return f"endpoint/{self.endpoint_name}/variant/{self.autoscaling.variant_name}"


@dataclass
class InferenceSmokeTestConfig:
    default_prompt: str
    system_message: str
    chat_template: str
    max_new_tokens: int
    temperature: float
    top_p: float


@dataclass
class HuggingFacePackagingConfig:
    required_files: tuple[str, ...]


@dataclass
class RagEngConfig:
    model_family: str
    use_sagemaker: bool
    inference_backend: str


@dataclass
class RagEngEcsConfig:
    cluster: str
    service_name: str
    task_family: str
    task_definition: str
    container_name: str
    launch_type: str
    platform_version: str
    assign_public_ip: str
    subnet_ids: tuple[str, ...]
    security_group_ids: tuple[str, ...]
    alb_security_group_id: str | None
    image_uri: str | None
    execution_role_arn: str | None
    task_role_arn: str | None
    cpu: int
    memory: int
    container_port: int
    desired_count: int
    health_check_path: str
    health_check_grace_period_seconds: int
    log_group: str
    log_stream_prefix: str
    target_group_arn: str | None
    environment: dict[str, str]
    secret_arn_map: dict[str, str | None]


@dataclass
class EvaluationWorkerConfig:
    cluster: str
    task_family: str
    task_definition: str
    container_name: str
    launch_type: str
    platform_version: str
    assign_public_ip: str
    subnet_ids: tuple[str, ...]
    security_group_ids: tuple[str, ...]
    image_uri: str | None
    execution_role_arn: str | None
    task_role_arn: str | None
    cpu: int
    memory: int
    log_group: str
    log_stream_prefix: str
    environment: dict[str, str]
    secret_arn_map: dict[str, str | None]


@dataclass
class FrontendCloudFrontConfig:
    distribution_id: str | None
    aliases: tuple[str, ...]
    certificate_arn: str | None
    comment: str
    create_oac: bool
    invalidation_paths: tuple[str, ...]
    api_path_patterns: tuple[str, ...]
    origin_protocol_policy: str
    cache_static_assets: bool
    cache_html_seconds: int


@dataclass
class FrontendBuildConfig:
    vite_api_base_url: str
    vite_cognito_domain: str
    vite_cognito_redirect_uri: str
    vite_cognito_logout_uri: str
    extra_env: dict[str, str]

    def as_env_dict(self) -> dict[str, str]:
        env = {
            "VITE_API_BASE_URL": self.vite_api_base_url,
            "VITE_COGNITO_DOMAIN": self.vite_cognito_domain,
            "VITE_COGNITO_REDIRECT_URI": self.vite_cognito_redirect_uri,
            "VITE_COGNITO_LOGOUT_URI": self.vite_cognito_logout_uri,
        }
        env.update(self.extra_env)
        return env


@dataclass
class FrontendWebConfig:
    enabled: bool
    app_dir: str
    dist_dir: str
    bucket_name: str
    bucket_prefix: str
    default_root_object: str
    spa_fallback_path: str
    price_class: str
    cloudfront: FrontendCloudFrontConfig
    build: FrontendBuildConfig


@dataclass
class DeployConfig:
    config_path: Path
    google_drive: GoogleDriveConfig
    local_paths: LocalPathsConfig
    aws: AwsConfig
    model_artifact: ModelArtifactConfig
    sagemaker: SageMakerConfig
    inference_smoke_test: InferenceSmokeTestConfig
    huggingface_packaging: HuggingFacePackagingConfig
    rag_eng: RagEngConfig
    rag_eng_ecs: RagEngEcsConfig
    evaluation_worker: EvaluationWorkerConfig
    frontend_web: FrontendWebConfig
    _raw: dict[str, Any] = field(repr=False, default_factory=dict)

    @property
    def model_data_uri(self) -> str:
        return self.model_artifact.resolved_uri(self.aws.s3_bucket)


def resolve_config_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    env_path = os.getenv("DEPLOY_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    return DEFAULT_CONFIG_PATH


def _require_yaml() -> None:
    if yaml is None:
        print("ERROR: PyYAML is required.  Run:  uv pip install pyyaml")
        sys.exit(1)


def _load_yaml_dict(path: Path) -> dict[str, Any]:
    _require_yaml()
    if not path.is_file():
        print(f"ERROR: Deployment config not found: {path}")
        sys.exit(1)
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        print(f"ERROR: Invalid YAML root in {path}")
        sys.exit(1)
    return data


def _strip_meta_keys(data: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in data.items() if not str(k).startswith("_")}


def _get_nested(data: dict[str, Any], dot_path: str) -> Any:
    node: Any = data
    for part in dot_path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set_nested(data: dict[str, Any], dot_path: str, value: Any) -> None:
    parts = dot_path.split(".")
    node = data
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def _apply_env_overrides(data: dict[str, Any]) -> None:
    for env_var, dot_path in ENV_OVERRIDES.items():
        if dot_path == "_config_path":
            continue
        raw = os.getenv(env_var)
        if raw is None or raw == "":
            continue
        if dot_path.endswith("profile") and raw.lower() in ("null", "none"):
            _set_nested(data, dot_path, None)
        elif dot_path.endswith("s3_uri") and raw.lower() in ("null", "none"):
            _set_nested(data, dot_path, None)
        elif dot_path.endswith("execution_role_arn") and raw.lower() in (
            "null",
            "none",
        ):
            _set_nested(data, dot_path, None)
        else:
            _set_nested(data, dot_path, raw)


def _as_tuple_str(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return default


def _as_tuple_str_required(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    return ()


def _as_tuple_str_or_csv(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(v).strip() for v in value if str(v).strip())
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return default


def _as_str_mapping(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {
            str(key).strip(): str(val).strip()
            for key, val in value.items()
            if str(key).strip() and val is not None and str(val).strip()
        }
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return {
                str(key).strip(): str(val).strip()
                for key, val in parsed.items()
                if str(key).strip() and val is not None and str(val).strip()
            }
        raise ValueError("Expected a JSON object for mapping overrides.")
    return {}


def _as_optional_str_mapping(value: Any) -> dict[str, str | None]:
    if isinstance(value, dict):
        return {
            str(key).strip(): (
                None if val is None or not str(val).strip() else str(val).strip()
            )
            for key, val in value.items()
            if str(key).strip()
        }
    if isinstance(value, str) and value.strip():
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return {
                str(key).strip(): (
                    None if val is None or not str(val).strip() else str(val).strip()
                )
                for key, val in parsed.items()
                if str(key).strip()
            }
        raise ValueError("Expected a JSON object for mapping overrides.")
    return {}


def _str_or_default(value: Any, default: str) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _load_scale_from_zero_alarm(autoscale: dict) -> ScaleFromZeroAlarmConfig:
    alarm = autoscale.get("scale_from_zero_alarm", {})
    return ScaleFromZeroAlarmConfig(
        period_seconds=int(alarm.get("period_seconds", 30)),
        evaluation_periods=int(alarm.get("evaluation_periods", 1)),
        datapoints_to_alarm=int(alarm.get("datapoints_to_alarm", 1)),
    )


def load_deploy_config(path: str | Path | None = None) -> DeployConfig:
    """Load deployment.yaml, apply environment overrides, return typed config."""
    config_path = resolve_config_path(path)
    raw = _strip_meta_keys(_load_yaml_dict(config_path))
    _apply_env_overrides(raw)

    gd = raw.get("google_drive", {})
    lp = raw.get("local_paths", {})
    aws = raw.get("aws", {})
    ma = raw.get("model_artifact", {})
    sm = raw.get("sagemaker", {})
    ai = sm.get("async_inference", {})
    autoscale = sm.get("autoscaling", {})
    dlc = sm.get("dlc", {})
    container = sm.get("container", {})
    runtime = sm.get("runtime_io", {})
    smoke = raw.get("inference_smoke_test", {})
    hf = raw.get("huggingface_packaging", {})
    rag = raw.get("rag_eng", {})
    rag_ecs = raw.get("rag_eng_ecs", {})
    evaluation_worker = raw.get("evaluation_worker", {})
    frontend = raw.get("frontend_web", {})
    frontend_cloudfront = frontend.get("cloudfront", {})
    frontend_build = frontend.get("build", {})

    profile = aws.get("profile")
    if profile in ("", "null", "none"):
        profile = None

    execution_role = sm.get("execution_role_arn")
    if execution_role in ("", "null", "none"):
        execution_role = None

    inference_ami = sm.get("inference_ami_version")
    if inference_ami in ("", "null", "none"):
        inference_ami = None

    extra_env_raw = container.get("extra_env") or {}
    extra_env = {str(k): str(v) for k, v in extra_env_raw.items()}

    ecs_environment = _as_str_mapping(rag_ecs.get("environment", {}))
    ecs_secret_arn_map = _as_optional_str_mapping(rag_ecs.get("secret_arn_map", {}))

    s3_uri = ma.get("s3_uri")
    if s3_uri in ("", "null", "none"):
        s3_uri = None

    rag_ecs_execution_role = rag_ecs.get("execution_role_arn")
    if rag_ecs_execution_role in ("", "null", "none"):
        rag_ecs_execution_role = None

    rag_ecs_task_role = rag_ecs.get("task_role_arn")
    if rag_ecs_task_role in ("", "null", "none"):
        rag_ecs_task_role = None

    rag_ecs_image_uri = rag_ecs.get("image_uri")
    if rag_ecs_image_uri in ("", "null", "none"):
        rag_ecs_image_uri = None

    rag_ecs_alb_security_group_id = rag_ecs.get("alb_security_group_id")
    if rag_ecs_alb_security_group_id in ("", "null", "none"):
        rag_ecs_alb_security_group_id = None

    rag_ecs_target_group_arn = rag_ecs.get("target_group_arn")
    if rag_ecs_target_group_arn in ("", "null", "none"):
        rag_ecs_target_group_arn = None

    evaluation_worker_execution_role = evaluation_worker.get("execution_role_arn")
    if evaluation_worker_execution_role in ("", "null", "none"):
        evaluation_worker_execution_role = None

    evaluation_worker_task_role = evaluation_worker.get("task_role_arn")
    if evaluation_worker_task_role in ("", "null", "none"):
        evaluation_worker_task_role = None

    evaluation_worker_image_uri = evaluation_worker.get("image_uri")
    if evaluation_worker_image_uri in ("", "null", "none"):
        evaluation_worker_image_uri = None

    evaluation_worker_environment = _as_str_mapping(
        evaluation_worker.get("environment", {})
    )
    evaluation_worker_secret_arn_map = _as_optional_str_mapping(
        evaluation_worker.get("secret_arn_map", {})
    )

    frontend_certificate_arn = frontend_cloudfront.get("certificate_arn")
    if frontend_certificate_arn in ("", "null", "none"):
        frontend_certificate_arn = None

    frontend_distribution_id = frontend_cloudfront.get("distribution_id")
    if frontend_distribution_id in ("", "null", "none"):
        frontend_distribution_id = None

    return DeployConfig(
        config_path=config_path,
        google_drive=GoogleDriveConfig(
            folder_id=str(gd.get("folder_id", "")),
            folder_url=str(gd.get("folder_url", "")),
        ),
        local_paths=LocalPathsConfig(
            download_dir=str(lp.get("download_dir", "./model_download")),
            tarball_path=str(lp.get("tarball_path", "./model.tar.gz")),
            partial_file_suffixes=_as_tuple_str(
                lp.get("partial_file_suffixes"),
                (".part", ".tmp", ".crdownload"),
            ),
        ),
        aws=AwsConfig(
            region=str(aws.get("region", "us-east-1")),
            profile=profile,
            s3_bucket=str(aws.get("s3_bucket", "codingrabbit-data-dev")),
        ),
        model_artifact=ModelArtifactConfig(
            s3_key=str(ma.get("s3_key", "models/qwen-finetuned/model.tar.gz")),
            s3_uri=s3_uri,
        ),
        sagemaker=SageMakerConfig(
            endpoint_name=str(sm.get("endpoint_name", "codingrabbit-qwen-async")),
            instance_type=str(sm.get("instance_type", "ml.g5.2xlarge")),
            initial_instance_count=int(sm.get("initial_instance_count", 1)),
            execution_role_arn=execution_role,
            inference_ami_version=inference_ami,
            autoscaling=AutoScalingConfig(
                enabled=bool(autoscale.get("enabled", True)),
                variant_name=str(autoscale.get("variant_name", "AllTraffic")),
                min_capacity=int(autoscale.get("min_capacity", 0)),
                max_capacity=int(autoscale.get("max_capacity", 1)),
                target_backlog_per_instance=float(
                    autoscale.get("target_backlog_per_instance", 5.0)
                ),
                scale_in_cooldown_seconds=int(
                    autoscale.get("scale_in_cooldown_seconds", 600)
                ),
                scale_out_cooldown_seconds=int(
                    autoscale.get("scale_out_cooldown_seconds", 300)
                ),
                scale_from_zero_cooldown_seconds=int(
                    autoscale.get("scale_from_zero_cooldown_seconds", 300)
                ),
                scale_from_zero_alarm=_load_scale_from_zero_alarm(autoscale),
            ),
            async_inference=AsyncInferenceConfig(
                output_s3_prefix=str(
                    ai.get("output_s3_prefix", "async-inference/output/")
                ),
                max_concurrent_invocations_per_instance=int(
                    ai.get("max_concurrent_invocations_per_instance", 4)
                ),
                invoke_poll_interval_seconds=int(
                    ai.get("invoke_poll_interval_seconds", 3)
                ),
                invoke_poll_max_attempts=int(ai.get("invoke_poll_max_attempts", 60)),
                deploy_wait_delay_seconds=int(ai.get("deploy_wait_delay_seconds", 30)),
                deploy_wait_max_attempts=int(ai.get("deploy_wait_max_attempts", 40)),
            ),
            dlc=DlcConfig(
                account_id=str(dlc.get("account_id", "763104351884")),
                repository=str(dlc.get("repository", "huggingface-vllm")),
                tag=str(
                    dlc.get(
                        "tag",
                        "0.17.0-transformers4.57.5-gpu-py312-cu129-ubuntu22.04",
                    )
                ),
            ),
            container=ContainerConfig(
                inference_backend=str(container.get("inference_backend", "vllm")),
                hf_task=str(container.get("hf_task", "text-generation")),
                model_server_workers=str(container.get("model_server_workers", "1")),
                extra_env=extra_env,
            ),
            runtime_io=RuntimeIoConfig(
                input_s3_prefix=str(
                    runtime.get("input_s3_prefix", "temp/sagemaker_inputs/")
                ),
            ),
        ),
        inference_smoke_test=InferenceSmokeTestConfig(
            default_prompt=str(
                smoke.get(
                    "default_prompt",
                    "Why does my C++ pointer cause a segmentation fault?",
                )
            ),
            system_message=str(
                smoke.get(
                    "system_message",
                    "You are CodingRabbit, a Socratic C++ teaching assistant.",
                )
            ),
            chat_template=str(smoke.get("chat_template", "qwen")),
            max_new_tokens=int(smoke.get("max_new_tokens", 512)),
            temperature=float(smoke.get("temperature", 0.7)),
            top_p=float(smoke.get("top_p", 0.9)),
        ),
        huggingface_packaging=HuggingFacePackagingConfig(
            required_files=_as_tuple_str_required(hf.get("required_files"))
            or ("config.json", "tokenizer_config.json"),
        ),
        rag_eng=RagEngConfig(
            model_family=str(rag.get("model_family", "qwen")),
            use_sagemaker=bool(rag.get("use_sagemaker", False)),
            inference_backend=str(rag.get("inference_backend", "vllm")),
        ),
        rag_eng_ecs=RagEngEcsConfig(
            cluster=_str_or_default(rag_ecs.get("cluster"), ""),
            service_name=_str_or_default(rag_ecs.get("service_name"), ""),
            task_family=_str_or_default(rag_ecs.get("task_family"), ""),
            task_definition=_str_or_default(rag_ecs.get("task_definition"), ""),
            container_name=_str_or_default(rag_ecs.get("container_name"), "rag-eng"),
            launch_type=_str_or_default(rag_ecs.get("launch_type"), "FARGATE"),
            platform_version=_str_or_default(
                rag_ecs.get("platform_version"),
                "LATEST",
            ),
            assign_public_ip=_str_or_default(
                rag_ecs.get("assign_public_ip"),
                "ENABLED",
            ),
            subnet_ids=_as_tuple_str_or_csv(rag_ecs.get("subnet_ids"), ()),
            security_group_ids=_as_tuple_str_or_csv(
                rag_ecs.get("security_group_ids"),
                (),
            ),
            alb_security_group_id=rag_ecs_alb_security_group_id,
            image_uri=rag_ecs_image_uri,
            execution_role_arn=rag_ecs_execution_role,
            task_role_arn=rag_ecs_task_role,
            cpu=int(rag_ecs.get("cpu", 1024)),
            memory=int(rag_ecs.get("memory", 2048)),
            container_port=int(rag_ecs.get("container_port", 8001)),
            desired_count=int(rag_ecs.get("desired_count", 1)),
            health_check_path=_str_or_default(
                rag_ecs.get("health_check_path"), "/health"
            ),
            health_check_grace_period_seconds=int(
                rag_ecs.get("health_check_grace_period_seconds", 120)
            ),
            log_group=_str_or_default(
                rag_ecs.get("log_group"), "/ecs/codingrabbit-rag-eng"
            ),
            log_stream_prefix=_str_or_default(rag_ecs.get("log_stream_prefix"), "ecs"),
            target_group_arn=rag_ecs_target_group_arn,
            environment=ecs_environment,
            secret_arn_map=ecs_secret_arn_map,
        ),
        evaluation_worker=EvaluationWorkerConfig(
            cluster=_str_or_default(
                evaluation_worker.get("cluster"),
                _str_or_default(rag_ecs.get("cluster"), ""),
            ),
            task_family=_str_or_default(
                evaluation_worker.get("task_family"),
                "codingrabbit-evaluation-worker",
            ),
            task_definition=_str_or_default(
                evaluation_worker.get("task_definition"),
                _str_or_default(
                    evaluation_worker.get("task_family"),
                    "codingrabbit-evaluation-worker",
                ),
            ),
            container_name=_str_or_default(
                evaluation_worker.get("container_name"),
                "evaluation-worker",
            ),
            launch_type=_str_or_default(
                evaluation_worker.get("launch_type"),
                _str_or_default(rag_ecs.get("launch_type"), "FARGATE"),
            ),
            platform_version=_str_or_default(
                evaluation_worker.get("platform_version"),
                _str_or_default(rag_ecs.get("platform_version"), "LATEST"),
            ),
            assign_public_ip=_str_or_default(
                evaluation_worker.get("assign_public_ip"),
                _str_or_default(rag_ecs.get("assign_public_ip"), "ENABLED"),
            ),
            subnet_ids=_as_tuple_str_or_csv(
                evaluation_worker.get("subnet_ids"),
                _as_tuple_str_or_csv(rag_ecs.get("subnet_ids"), ()),
            ),
            security_group_ids=_as_tuple_str_or_csv(
                evaluation_worker.get("security_group_ids"),
                _as_tuple_str_or_csv(rag_ecs.get("security_group_ids"), ()),
            ),
            image_uri=evaluation_worker_image_uri or rag_ecs_image_uri,
            execution_role_arn=(
                evaluation_worker_execution_role or rag_ecs_execution_role
            ),
            task_role_arn=evaluation_worker_task_role or rag_ecs_task_role,
            cpu=int(evaluation_worker.get("cpu", rag_ecs.get("cpu", 1024))),
            memory=int(evaluation_worker.get("memory", rag_ecs.get("memory", 2048))),
            log_group=_str_or_default(
                evaluation_worker.get("log_group"),
                "/ecs/codingrabbit-evaluation-worker",
            ),
            log_stream_prefix=_str_or_default(
                evaluation_worker.get("log_stream_prefix"),
                "ecs",
            ),
            environment=evaluation_worker_environment,
            secret_arn_map=evaluation_worker_secret_arn_map,
        ),
        frontend_web=FrontendWebConfig(
            enabled=_as_bool(frontend.get("enabled", False), False),
            app_dir=str(frontend.get("app_dir", "./frontend")),
            dist_dir=str(frontend.get("dist_dir", "./frontend/dist")),
            bucket_name=str(frontend.get("bucket_name", "")),
            bucket_prefix=str(frontend.get("bucket_prefix", "")),
            default_root_object=str(frontend.get("default_root_object", "index.html")),
            spa_fallback_path=str(frontend.get("spa_fallback_path", "/index.html")),
            price_class=str(frontend.get("price_class", "PriceClass_100")),
            cloudfront=FrontendCloudFrontConfig(
                distribution_id=frontend_distribution_id,
                aliases=_as_tuple_str_or_csv(frontend_cloudfront.get("aliases"), ()),
                certificate_arn=frontend_certificate_arn,
                comment=_str_or_default(
                    frontend_cloudfront.get("comment"),
                    "CodingRabbit frontend distribution",
                ),
                create_oac=_as_bool(
                    frontend_cloudfront.get("create_oac", True),
                    True,
                ),
                invalidation_paths=_as_tuple_str_or_csv(
                    frontend_cloudfront.get("invalidation_paths"),
                    ("/*",),
                ),
                api_path_patterns=_as_tuple_str_or_csv(
                    frontend_cloudfront.get("api_path_patterns"),
                    (
                        "/api/*",
                        "/admin/*",
                        "/run/*",
                        "/me",
                        "/query",
                        "/health",
                        "/docs",
                        "/openapi.json",
                        "/gradio*",
                    ),
                ),
                origin_protocol_policy=str(
                    frontend_cloudfront.get("origin_protocol_policy", "http-only")
                ),
                cache_static_assets=_as_bool(
                    frontend_cloudfront.get("cache_static_assets", True),
                    True,
                ),
                cache_html_seconds=int(
                    frontend_cloudfront.get("cache_html_seconds", 60)
                ),
            ),
            build=FrontendBuildConfig(
                vite_api_base_url=str(
                    frontend_build.get("vite_api_base_url", "http://localhost:8001")
                ),
                vite_cognito_domain=str(
                    frontend_build.get(
                        "vite_cognito_domain",
                        "https://us-east-1z5dab8wni.auth.us-east-1.amazoncognito.com",
                    )
                ),
                vite_cognito_redirect_uri=str(
                    frontend_build.get(
                        "vite_cognito_redirect_uri",
                        "http://localhost:5173/auth/callback",
                    )
                ),
                vite_cognito_logout_uri=str(
                    frontend_build.get(
                        "vite_cognito_logout_uri",
                        "http://localhost:5173/logout",
                    )
                ),
                extra_env=_as_str_mapping(frontend_build.get("extra_env", {})),
            ),
        ),
        _raw=raw,
    )


def get_dotpath(cfg: DeployConfig, dot_path: str) -> Any:
    """Resolve a dot-path against the typed config (limited paths for shell)."""
    mapping = {
        "aws.region": cfg.aws.region,
        "aws.profile": cfg.aws.profile or "",
        "aws.s3_bucket": cfg.aws.s3_bucket,
        "google_drive.folder_id": cfg.google_drive.folder_id,
        "local_paths.download_dir": cfg.local_paths.download_dir,
        "local_paths.tarball_path": cfg.local_paths.tarball_path,
        "model_artifact.s3_key": cfg.model_artifact.s3_key,
        "model_artifact.s3_uri": cfg.model_data_uri,
        "sagemaker.endpoint_name": cfg.sagemaker.endpoint_name,
        "sagemaker.instance_type": cfg.sagemaker.instance_type,
        "rag_eng.model_family": cfg.rag_eng.model_family,
        "rag_eng_ecs.cluster": cfg.rag_eng_ecs.cluster,
        "rag_eng_ecs.service_name": cfg.rag_eng_ecs.service_name,
        "rag_eng_ecs.task_family": cfg.rag_eng_ecs.task_family,
        "rag_eng_ecs.task_definition": cfg.rag_eng_ecs.task_definition,
        "rag_eng_ecs.container_name": cfg.rag_eng_ecs.container_name,
        "rag_eng_ecs.alb_security_group_id": cfg.rag_eng_ecs.alb_security_group_id
        or "",
        "rag_eng_ecs.subnet_ids": ",".join(cfg.rag_eng_ecs.subnet_ids),
        "rag_eng_ecs.security_group_ids": ",".join(cfg.rag_eng_ecs.security_group_ids),
        "rag_eng_ecs.image_uri": cfg.rag_eng_ecs.image_uri or "",
        "rag_eng_ecs.execution_role_arn": cfg.rag_eng_ecs.execution_role_arn or "",
        "rag_eng_ecs.task_role_arn": cfg.rag_eng_ecs.task_role_arn or "",
        "rag_eng_ecs.launch_type": cfg.rag_eng_ecs.launch_type,
        "rag_eng_ecs.platform_version": cfg.rag_eng_ecs.platform_version,
        "rag_eng_ecs.assign_public_ip": cfg.rag_eng_ecs.assign_public_ip,
        "rag_eng_ecs.container_port": str(cfg.rag_eng_ecs.container_port),
        "rag_eng_ecs.desired_count": str(cfg.rag_eng_ecs.desired_count),
        "rag_eng_ecs.target_group_arn": cfg.rag_eng_ecs.target_group_arn or "",
        "rag_eng_ecs.health_check_path": cfg.rag_eng_ecs.health_check_path,
        "rag_eng_ecs.health_check_grace_period_seconds": str(
            cfg.rag_eng_ecs.health_check_grace_period_seconds
        ),
        "rag_eng_ecs.log_group": cfg.rag_eng_ecs.log_group,
        "rag_eng_ecs.log_stream_prefix": cfg.rag_eng_ecs.log_stream_prefix,
        "evaluation_worker.cluster": cfg.evaluation_worker.cluster,
        "evaluation_worker.task_family": cfg.evaluation_worker.task_family,
        "evaluation_worker.task_definition": cfg.evaluation_worker.task_definition,
        "evaluation_worker.container_name": cfg.evaluation_worker.container_name,
        "evaluation_worker.image_uri": cfg.evaluation_worker.image_uri or "",
        "evaluation_worker.execution_role_arn": (
            cfg.evaluation_worker.execution_role_arn or ""
        ),
        "evaluation_worker.task_role_arn": cfg.evaluation_worker.task_role_arn or "",
        "evaluation_worker.launch_type": cfg.evaluation_worker.launch_type,
        "evaluation_worker.platform_version": cfg.evaluation_worker.platform_version,
        "evaluation_worker.assign_public_ip": cfg.evaluation_worker.assign_public_ip,
        "evaluation_worker.subnet_ids": ",".join(cfg.evaluation_worker.subnet_ids),
        "evaluation_worker.security_group_ids": ",".join(
            cfg.evaluation_worker.security_group_ids
        ),
        "evaluation_worker.cpu": str(cfg.evaluation_worker.cpu),
        "evaluation_worker.memory": str(cfg.evaluation_worker.memory),
        "evaluation_worker.log_group": cfg.evaluation_worker.log_group,
        "evaluation_worker.log_stream_prefix": cfg.evaluation_worker.log_stream_prefix,
        "frontend_web.enabled": str(cfg.frontend_web.enabled),
        "frontend_web.app_dir": cfg.frontend_web.app_dir,
        "frontend_web.dist_dir": cfg.frontend_web.dist_dir,
        "frontend_web.bucket_name": cfg.frontend_web.bucket_name,
        "frontend_web.bucket_prefix": cfg.frontend_web.bucket_prefix,
        "frontend_web.default_root_object": cfg.frontend_web.default_root_object,
        "frontend_web.spa_fallback_path": cfg.frontend_web.spa_fallback_path,
        "frontend_web.price_class": cfg.frontend_web.price_class,
        "frontend_web.cloudfront.aliases": ",".join(
            cfg.frontend_web.cloudfront.aliases
        ),
        "frontend_web.cloudfront.distribution_id": (
            cfg.frontend_web.cloudfront.distribution_id or ""
        ),
        "frontend_web.cloudfront.certificate_arn": (
            cfg.frontend_web.cloudfront.certificate_arn or ""
        ),
        "frontend_web.cloudfront.comment": cfg.frontend_web.cloudfront.comment,
        "frontend_web.cloudfront.create_oac": str(
            cfg.frontend_web.cloudfront.create_oac
        ),
        "frontend_web.cloudfront.invalidation_paths": ",".join(
            cfg.frontend_web.cloudfront.invalidation_paths
        ),
        "frontend_web.cloudfront.api_path_patterns": ",".join(
            cfg.frontend_web.cloudfront.api_path_patterns
        ),
        "frontend_web.cloudfront.origin_protocol_policy": (
            cfg.frontend_web.cloudfront.origin_protocol_policy
        ),
        "frontend_web.cloudfront.cache_static_assets": str(
            cfg.frontend_web.cloudfront.cache_static_assets
        ),
        "frontend_web.cloudfront.cache_html_seconds": str(
            cfg.frontend_web.cloudfront.cache_html_seconds
        ),
        "frontend_web.build.vite_api_base_url": cfg.frontend_web.build.vite_api_base_url,
        "frontend_web.build.vite_cognito_domain": cfg.frontend_web.build.vite_cognito_domain,
        "frontend_web.build.vite_cognito_redirect_uri": (
            cfg.frontend_web.build.vite_cognito_redirect_uri
        ),
        "frontend_web.build.vite_cognito_logout_uri": (
            cfg.frontend_web.build.vite_cognito_logout_uri
        ),
    }
    return mapping.get(dot_path, _get_nested(cfg._raw, dot_path))


def shell_export(cfg: DeployConfig | None = None) -> str:
    """Emit shell `export` statements for bash scripts."""
    cfg = cfg or load_deploy_config()
    pairs = {
        "DEPLOY_CONFIG_PATH": str(cfg.config_path),
        "DEPLOY_S3_BUCKET": cfg.aws.s3_bucket,
        "DEPLOY_AWS_REGION": cfg.aws.region,
        "DEPLOY_AWS_PROFILE": cfg.aws.profile or "",
        "DEPLOY_MODEL_DATA_URI": cfg.model_data_uri,
        "DEPLOY_MODEL_S3_KEY": cfg.model_artifact.s3_key,
        "DEPLOY_ENDPOINT_NAME": cfg.sagemaker.endpoint_name,
        "DEPLOY_INSTANCE_TYPE": cfg.sagemaker.instance_type,
        "DEPLOY_MODEL_FAMILY": cfg.rag_eng.model_family,
        "DEPLOY_DOWNLOAD_DIR": cfg.local_paths.download_dir,
        "DEPLOY_TARBALL_PATH": cfg.local_paths.tarball_path,
        "DEPLOY_RAG_ENG_ECS_CLUSTER": cfg.rag_eng_ecs.cluster,
        "DEPLOY_RAG_ENG_ECS_SERVICE_NAME": cfg.rag_eng_ecs.service_name,
        "DEPLOY_RAG_ENG_ECS_TASK_FAMILY": cfg.rag_eng_ecs.task_family,
        "DEPLOY_RAG_ENG_ECS_TASK_DEFINITION": cfg.rag_eng_ecs.task_definition,
        "DEPLOY_RAG_ENG_ECS_CONTAINER_NAME": cfg.rag_eng_ecs.container_name,
        "DEPLOY_RAG_ENG_ECS_ALB_SECURITY_GROUP_ID": (
            cfg.rag_eng_ecs.alb_security_group_id or ""
        ),
        "DEPLOY_RAG_ENG_ECS_TARGET_GROUP_ARN": cfg.rag_eng_ecs.target_group_arn or "",
        "DEPLOY_RAG_ENG_ECS_CONTAINER_PORT": str(cfg.rag_eng_ecs.container_port),
        "DEPLOY_RAG_ENG_ECS_LAUNCH_TYPE": cfg.rag_eng_ecs.launch_type,
        "DEPLOY_RAG_ENG_ECS_PLATFORM_VERSION": cfg.rag_eng_ecs.platform_version,
        "DEPLOY_RAG_ENG_ECS_ASSIGN_PUBLIC_IP": cfg.rag_eng_ecs.assign_public_ip,
        "DEPLOY_RAG_ENG_ECS_SUBNETS": ",".join(cfg.rag_eng_ecs.subnet_ids),
        "DEPLOY_RAG_ENG_ECS_SECURITY_GROUPS": ",".join(
            cfg.rag_eng_ecs.security_group_ids
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_CLUSTER": cfg.evaluation_worker.cluster,
        "DEPLOY_EVALUATION_WORKER_ECS_TASK_FAMILY": cfg.evaluation_worker.task_family,
        "DEPLOY_EVALUATION_WORKER_ECS_TASK_DEFINITION": cfg.evaluation_worker.task_definition,
        "DEPLOY_EVALUATION_WORKER_ECS_CONTAINER_NAME": cfg.evaluation_worker.container_name,
        "DEPLOY_EVALUATION_WORKER_ECS_IMAGE_URI": cfg.evaluation_worker.image_uri or "",
        "DEPLOY_EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN": (
            cfg.evaluation_worker.execution_role_arn or ""
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_TASK_ROLE_ARN": (
            cfg.evaluation_worker.task_role_arn or ""
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_LAUNCH_TYPE": cfg.evaluation_worker.launch_type,
        "DEPLOY_EVALUATION_WORKER_ECS_PLATFORM_VERSION": (
            cfg.evaluation_worker.platform_version
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP": (
            cfg.evaluation_worker.assign_public_ip
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_SUBNETS": ",".join(
            cfg.evaluation_worker.subnet_ids
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_SECURITY_GROUPS": ",".join(
            cfg.evaluation_worker.security_group_ids
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_CPU": str(cfg.evaluation_worker.cpu),
        "DEPLOY_EVALUATION_WORKER_ECS_MEMORY": str(cfg.evaluation_worker.memory),
        "DEPLOY_EVALUATION_WORKER_ECS_LOG_GROUP": cfg.evaluation_worker.log_group,
        "DEPLOY_EVALUATION_WORKER_ECS_LOG_STREAM_PREFIX": (
            cfg.evaluation_worker.log_stream_prefix
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_ENV_JSON": json.dumps(
            cfg.evaluation_worker.environment,
            sort_keys=True,
        ),
        "DEPLOY_EVALUATION_WORKER_ECS_SECRET_ARNS_JSON": json.dumps(
            {
                key: value
                for key, value in cfg.evaluation_worker.secret_arn_map.items()
                if value is not None
            },
            sort_keys=True,
        ),
        "DEPLOY_FRONTEND_ENABLED": str(cfg.frontend_web.enabled),
        "DEPLOY_FRONTEND_APP_DIR": cfg.frontend_web.app_dir,
        "DEPLOY_FRONTEND_DIST_DIR": cfg.frontend_web.dist_dir,
        "DEPLOY_FRONTEND_BUCKET_NAME": cfg.frontend_web.bucket_name,
        "DEPLOY_FRONTEND_BUCKET_PREFIX": cfg.frontend_web.bucket_prefix,
        "DEPLOY_FRONTEND_DEFAULT_ROOT_OBJECT": cfg.frontend_web.default_root_object,
        "DEPLOY_FRONTEND_SPA_FALLBACK_PATH": cfg.frontend_web.spa_fallback_path,
        "DEPLOY_FRONTEND_PRICE_CLASS": cfg.frontend_web.price_class,
        "DEPLOY_FRONTEND_CLOUDFRONT_ALIASES": ",".join(
            cfg.frontend_web.cloudfront.aliases
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_DISTRIBUTION_ID": (
            cfg.frontend_web.cloudfront.distribution_id or ""
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_CERTIFICATE_ARN": (
            cfg.frontend_web.cloudfront.certificate_arn or ""
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_COMMENT": cfg.frontend_web.cloudfront.comment,
        "DEPLOY_FRONTEND_CLOUDFRONT_CREATE_OAC": str(
            cfg.frontend_web.cloudfront.create_oac
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_INVALIDATION_PATHS": ",".join(
            cfg.frontend_web.cloudfront.invalidation_paths
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_API_PATH_PATTERNS": ",".join(
            cfg.frontend_web.cloudfront.api_path_patterns
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_ORIGIN_PROTOCOL_POLICY": (
            cfg.frontend_web.cloudfront.origin_protocol_policy
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_CACHE_STATIC_ASSETS": str(
            cfg.frontend_web.cloudfront.cache_static_assets
        ),
        "DEPLOY_FRONTEND_CLOUDFRONT_CACHE_HTML_SECONDS": str(
            cfg.frontend_web.cloudfront.cache_html_seconds
        ),
        "DEPLOY_FRONTEND_VITE_API_BASE_URL": cfg.frontend_web.build.vite_api_base_url,
        "DEPLOY_FRONTEND_VITE_COGNITO_DOMAIN": cfg.frontend_web.build.vite_cognito_domain,
        "DEPLOY_FRONTEND_VITE_COGNITO_REDIRECT_URI": (
            cfg.frontend_web.build.vite_cognito_redirect_uri
        ),
        "DEPLOY_FRONTEND_VITE_COGNITO_LOGOUT_URI": (
            cfg.frontend_web.build.vite_cognito_logout_uri
        ),
        "DEPLOY_FRONTEND_EXTRA_ENV_JSON": json.dumps(
            cfg.frontend_web.build.extra_env,
            sort_keys=True,
        ),
    }
    lines = []
    for key, value in pairs.items():
        escaped = str(value).replace('"', '\\"')
        lines.append(f'export {key}="{escaped}"')
    return "\n".join(lines)


def describe_config(path: str | Path | None = None) -> None:
    """Print human-readable documentation from deployment.yaml."""
    config_path = resolve_config_path(path)
    data = _load_yaml_dict(config_path)
    reference = data.get("_reference", {})
    print(f"Deployment configuration: {config_path}\n")
    if not reference:
        print("No _reference section found. See inline comments in the YAML file.")
        return
    for dot_path, meta in reference.items():
        if not isinstance(meta, dict):
            continue
        print(f"  {dot_path}")
        if meta.get("description"):
            print(f"    Description: {meta['description']}")
        if meta.get("env_override"):
            print(f"    Env override: {meta['env_override']}")
        if meta.get("options"):
            print(f"    Options: {meta['options']}")
        print()
    print("Resolved values (after env overrides):")
    cfg = load_deploy_config(config_path)
    print(
        json.dumps(
            {
                "aws": {
                    "region": cfg.aws.region,
                    "profile": cfg.aws.profile,
                    "s3_bucket": cfg.aws.s3_bucket,
                },
                "model_artifact": {
                    "s3_key": cfg.model_artifact.s3_key,
                    "s3_uri": cfg.model_data_uri,
                },
                "sagemaker": {
                    "endpoint_name": cfg.sagemaker.endpoint_name,
                    "instance_type": cfg.sagemaker.instance_type,
                },
                "rag_eng": {"model_family": cfg.rag_eng.model_family},
                "rag_eng_ecs": {
                    "cluster": cfg.rag_eng_ecs.cluster,
                    "service_name": cfg.rag_eng_ecs.service_name,
                    "task_family": cfg.rag_eng_ecs.task_family,
                    "task_definition": cfg.rag_eng_ecs.task_definition,
                    "container_name": cfg.rag_eng_ecs.container_name,
                    "alb_security_group_id": cfg.rag_eng_ecs.alb_security_group_id,
                    "subnet_ids": cfg.rag_eng_ecs.subnet_ids,
                    "security_group_ids": cfg.rag_eng_ecs.security_group_ids,
                    "execution_role_arn": cfg.rag_eng_ecs.execution_role_arn,
                    "task_role_arn": cfg.rag_eng_ecs.task_role_arn,
                    "launch_type": cfg.rag_eng_ecs.launch_type,
                    "platform_version": cfg.rag_eng_ecs.platform_version,
                    "assign_public_ip": cfg.rag_eng_ecs.assign_public_ip,
                    "container_port": cfg.rag_eng_ecs.container_port,
                    "desired_count": cfg.rag_eng_ecs.desired_count,
                    "target_group_arn": cfg.rag_eng_ecs.target_group_arn,
                    "health_check_path": cfg.rag_eng_ecs.health_check_path,
                    "health_check_grace_period_seconds": cfg.rag_eng_ecs.health_check_grace_period_seconds,
                    "log_group": cfg.rag_eng_ecs.log_group,
                    "log_stream_prefix": cfg.rag_eng_ecs.log_stream_prefix,
                    "environment_keys": sorted(cfg.rag_eng_ecs.environment),
                    "secret_keys": sorted(cfg.rag_eng_ecs.secret_arn_map),
                },
                "frontend_web": {
                    "enabled": cfg.frontend_web.enabled,
                    "bucket_name": cfg.frontend_web.bucket_name,
                    "bucket_prefix": cfg.frontend_web.bucket_prefix,
                    "app_dir": cfg.frontend_web.app_dir,
                    "dist_dir": cfg.frontend_web.dist_dir,
                    "default_root_object": cfg.frontend_web.default_root_object,
                    "spa_fallback_path": cfg.frontend_web.spa_fallback_path,
                    "price_class": cfg.frontend_web.price_class,
                    "aliases": cfg.frontend_web.cloudfront.aliases,
                    "distribution_id": cfg.frontend_web.cloudfront.distribution_id,
                    "certificate_arn": cfg.frontend_web.cloudfront.certificate_arn,
                    "comment": cfg.frontend_web.cloudfront.comment,
                    "create_oac": cfg.frontend_web.cloudfront.create_oac,
                    "invalidation_paths": cfg.frontend_web.cloudfront.invalidation_paths,
                    "api_path_patterns": cfg.frontend_web.cloudfront.api_path_patterns,
                    "origin_protocol_policy": cfg.frontend_web.cloudfront.origin_protocol_policy,
                    "cache_static_assets": cfg.frontend_web.cloudfront.cache_static_assets,
                    "cache_html_seconds": cfg.frontend_web.cloudfront.cache_html_seconds,
                    "vite_api_base_url": cfg.frontend_web.build.vite_api_base_url,
                    "vite_cognito_domain": cfg.frontend_web.build.vite_cognito_domain,
                    "vite_cognito_redirect_uri": cfg.frontend_web.build.vite_cognito_redirect_uri,
                    "vite_cognito_logout_uri": cfg.frontend_web.build.vite_cognito_logout_uri,
                    "extra_env_keys": sorted(cfg.frontend_web.build.extra_env),
                },
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Deployment YAML utilities")
    parser.add_argument(
        "command",
        choices=["get", "shell-export", "describe", "json"],
        help="get DOT.PATH | shell-export | describe | json",
    )
    parser.add_argument("path", nargs="?", help="Dot-path for get command")
    parser.add_argument("--config", default=None, help="Path to deployment.yaml")
    args = parser.parse_args()

    if args.command == "shell-export":
        print(shell_export(load_deploy_config(args.config)))
    elif args.command == "describe":
        describe_config(args.config)
    elif args.command == "json":
        cfg = load_deploy_config(args.config)
        print(
            json.dumps(
                {
                    "config_path": str(cfg.config_path),
                    "model_data_uri": cfg.model_data_uri,
                    "endpoint_name": cfg.sagemaker.endpoint_name,
                    "s3_bucket": cfg.aws.s3_bucket,
                    "region": cfg.aws.region,
                    "rag_eng_ecs": {
                        "cluster": cfg.rag_eng_ecs.cluster,
                        "service_name": cfg.rag_eng_ecs.service_name,
                        "task_family": cfg.rag_eng_ecs.task_family,
                        "task_definition": cfg.rag_eng_ecs.task_definition,
                        "container_name": cfg.rag_eng_ecs.container_name,
                        "alb_security_group_id": cfg.rag_eng_ecs.alb_security_group_id,
                        "subnet_ids": cfg.rag_eng_ecs.subnet_ids,
                        "security_group_ids": cfg.rag_eng_ecs.security_group_ids,
                        "execution_role_arn": cfg.rag_eng_ecs.execution_role_arn,
                        "task_role_arn": cfg.rag_eng_ecs.task_role_arn,
                        "launch_type": cfg.rag_eng_ecs.launch_type,
                        "platform_version": cfg.rag_eng_ecs.platform_version,
                        "assign_public_ip": cfg.rag_eng_ecs.assign_public_ip,
                        "container_port": cfg.rag_eng_ecs.container_port,
                        "desired_count": cfg.rag_eng_ecs.desired_count,
                        "target_group_arn": cfg.rag_eng_ecs.target_group_arn,
                        "health_check_path": cfg.rag_eng_ecs.health_check_path,
                        "health_check_grace_period_seconds": cfg.rag_eng_ecs.health_check_grace_period_seconds,
                        "log_group": cfg.rag_eng_ecs.log_group,
                        "log_stream_prefix": cfg.rag_eng_ecs.log_stream_prefix,
                        "environment_keys": sorted(cfg.rag_eng_ecs.environment),
                        "secret_keys": sorted(cfg.rag_eng_ecs.secret_arn_map),
                    },
                },
                indent=2,
            )
        )
    elif args.command == "get":
        if not args.path:
            print("ERROR: get requires a dot-path argument")
            sys.exit(1)
        value = get_dotpath(load_deploy_config(args.config), args.path)
        print("" if value is None else value)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
