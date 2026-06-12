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
    hf_task: str
    model_server_workers: str

    def as_env_dict(self) -> dict[str, str]:
        return {
            "HF_TASK": self.hf_task,
            "SAGEMAKER_MODEL_SERVER_WORKERS": self.model_server_workers,
        }


@dataclass
class RuntimeIoConfig:
    input_s3_prefix: str


@dataclass
class SageMakerConfig:
    endpoint_name: str
    instance_type: str
    initial_instance_count: int
    execution_role_arn: str | None
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
        elif dot_path.endswith("execution_role_arn") and raw.lower() in ("null", "none"):
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
    dlc = sm.get("dlc", {})
    container = sm.get("container", {})
    runtime = sm.get("runtime_io", {})
    smoke = raw.get("inference_smoke_test", {})
    hf = raw.get("huggingface_packaging", {})
    rag = raw.get("rag_eng", {})

    profile = aws.get("profile")
    if profile in ("", "null", "none"):
        profile = None

    execution_role = sm.get("execution_role_arn")
    if execution_role in ("", "null", "none"):
        execution_role = None

    s3_uri = ma.get("s3_uri")
    if s3_uri in ("", "null", "none"):
        s3_uri = None

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
                repository=str(dlc.get("repository", "huggingface-pytorch-inference")),
                tag=str(
                    dlc.get("tag", "2.3.0-transformers4.40.1-gpu-py311-cu121-ubuntu20.04")
                ),
            ),
            container=ContainerConfig(
                hf_task=str(container.get("hf_task", "text-generation")),
                model_server_workers=str(container.get("model_server_workers", "1")),
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
    print(json.dumps(
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
        },
        indent=2,
    ))


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
        print(json.dumps(
            {
                "config_path": str(cfg.config_path),
                "model_data_uri": cfg.model_data_uri,
                "endpoint_name": cfg.sagemaker.endpoint_name,
                "s3_bucket": cfg.aws.s3_bucket,
                "region": cfg.aws.region,
            },
            indent=2,
        ))
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
