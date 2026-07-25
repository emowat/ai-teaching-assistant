"""Render and register the ECS evaluation worker task definition."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dotenv import load_dotenv


load_dotenv()


SECRET_ENV_KEYS: tuple[str, ...] = (
    "COURSE_REGISTRY_DATABASE_URL",
    "OPENAI_API_KEY",
)

WORKER_ENV_KEYS: tuple[str, ...] = (
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "S3_DATA_BUCKET",
    "OPENAI_BASE_URL",
    "EVALUATION_DEFAULT_JUDGE_PROVIDER",
    "EVALUATION_DEFAULT_JUDGE_MODEL",
    "EVALUATION_RESULTS_PREFIX",
    "EVALUATION_OUTPUT_DIR",
    "EVALUATION_EXPORT_TZ",
    "EVALUATION_WRITE_AURORA",
    "EVALUATION_HOMEWORK_N",
    "EVALUATION_STUDY_N",
    "EVALUATION_JUDGE_TEMPERATURE",
    "EVALUATION_JUDGE_TOP_P",
    "EVALUATION_JUDGE_TIMEOUT_SECONDS",
    "EVALUATION_JUDGE_MAX_CONCURRENCY",
    "EVALUATION_JUDGE_MAX_TOKENS",
    "LOG_LEVEL",
    # Plain (non-secret) env vars needed to self-heal from an Aurora master
    # password rotation mid-run: the AWS-managed secret's ARN itself (not our
    # app secret's - that one is never touched by Aurora's rotation) plus the
    # stable connection details needed to rebuild a full URL from just a
    # refreshed username/password. See rag_eng/aurora_secret_refresh.py.
    "COURSE_REGISTRY_DATABASE_URL_SECRET_ID",
    "COURSE_REGISTRY_DB_HOST",
    "COURSE_REGISTRY_DB_PORT",
    "COURSE_REGISTRY_DB_NAME",
    "COURSE_REGISTRY_DB_SSLMODE",
)

BACKEND_ENV_KEYS: tuple[str, ...] = (
    "AWS_REGION",
    "AWS_PROFILE",
    "EVALUATION_WORKER_ECS_CLUSTER",
    "EVALUATION_WORKER_ECS_TASK_DEFINITION",
    "EVALUATION_WORKER_ECS_CONTAINER_NAME",
    "EVALUATION_WORKER_ECS_LAUNCH_TYPE",
    "EVALUATION_WORKER_ECS_PLATFORM_VERSION",
    "EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP",
    "EVALUATION_WORKER_ECS_SUBNETS",
    "EVALUATION_WORKER_ECS_SECURITY_GROUPS",
)

DEFAULT_TASK_FAMILY = "codingrabbit-evaluation-worker"
DEFAULT_CONTAINER_NAME = "evaluation-worker"
DEFAULT_LOG_GROUP = "/ecs/codingrabbit-evaluation-worker"
DEFAULT_LOG_STREAM_PREFIX = "ecs"


def _csv_values(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _json_mapping(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object for secret ARN mappings.")
    return {
        str(key).strip(): str(value).strip()
        for key, value in data.items()
        if str(key).strip() and str(value).strip()
    }


def _env_value(source: Mapping[str, str], *names: str, default: str | None = None) -> str | None:
    for name in names:
        value = source.get(name)
        if value is not None and value != "":
            return value
    return default


def _env_int(source: Mapping[str, str], *names: str, default: int) -> int:
    raw = _env_value(source, *names)
    if raw is None:
        return default
    return int(raw)


@dataclass(frozen=True)
class EvaluationWorkerDeployConfig:
    """Resolved ECS settings for the offline evaluation worker."""

    aws_region: str
    aws_profile: str | None
    ecs_cluster: str
    ecs_task_definition: str
    ecs_task_family: str
    ecs_container_name: str
    ecs_launch_type: str
    ecs_platform_version: str
    ecs_assign_public_ip: str
    ecs_subnet_ids: tuple[str, ...]
    ecs_security_group_ids: tuple[str, ...]
    ecs_image_uri: str
    ecs_execution_role_arn: str
    ecs_task_role_arn: str
    ecs_cpu: int
    ecs_memory: int
    ecs_log_group: str
    ecs_log_stream_prefix: str
    worker_env: dict[str, str]
    secret_arn_map: dict[str, str]


def load_evaluation_worker_config(
    env: Mapping[str, str] | None = None,
) -> EvaluationWorkerDeployConfig:
    """Load worker deployment settings from environment variables."""
    source = env or os.environ
    secret_arn_map = {}
    for key in ("DEPLOY_EVALUATION_WORKER_ECS_SECRET_ARNS_JSON", "EVALUATION_WORKER_ECS_SECRET_ARNS_JSON"):
        secret_arn_map.update(_json_mapping(source.get(key)))

    worker_env = {
        key: value
        for key in WORKER_ENV_KEYS
        if (value := _env_value(source, key)) is not None
    }

    aws_region = _env_value(
        source,
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "DEPLOY_AWS_REGION",
        default="us-east-1",
    )
    return EvaluationWorkerDeployConfig(
        aws_region=aws_region or "us-east-1",
        aws_profile=_env_value(source, "AWS_PROFILE", "DEPLOY_AWS_PROFILE"),
        ecs_cluster=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_CLUSTER",
            "EVALUATION_WORKER_ECS_CLUSTER",
            default="",
        )
        or "",
        ecs_task_definition=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_TASK_DEFINITION",
            "EVALUATION_WORKER_ECS_TASK_DEFINITION",
            default="",
        )
        or _env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_TASK_FAMILY",
            "EVALUATION_WORKER_ECS_TASK_FAMILY",
            default=DEFAULT_TASK_FAMILY,
        )
        or DEFAULT_TASK_FAMILY,
        ecs_task_family=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_TASK_FAMILY",
            "EVALUATION_WORKER_ECS_TASK_FAMILY",
            default=DEFAULT_TASK_FAMILY,
        )
        or DEFAULT_TASK_FAMILY,
        ecs_container_name=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_CONTAINER_NAME",
            "EVALUATION_WORKER_ECS_CONTAINER_NAME",
            default=DEFAULT_CONTAINER_NAME,
        )
        or DEFAULT_CONTAINER_NAME,
        ecs_launch_type=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_LAUNCH_TYPE",
            "EVALUATION_WORKER_ECS_LAUNCH_TYPE",
            default="FARGATE",
        )
        or "FARGATE",
        ecs_platform_version=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_PLATFORM_VERSION",
            "EVALUATION_WORKER_ECS_PLATFORM_VERSION",
            default="LATEST",
        )
        or "LATEST",
        ecs_assign_public_ip=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP",
            "EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP",
            default="ENABLED",
        )
        or "ENABLED",
        ecs_subnet_ids=_csv_values(
            _env_value(
                source,
                "DEPLOY_EVALUATION_WORKER_ECS_SUBNETS",
                "EVALUATION_WORKER_ECS_SUBNETS",
            )
        ),
        ecs_security_group_ids=_csv_values(
            _env_value(
                source,
                "DEPLOY_EVALUATION_WORKER_ECS_SECURITY_GROUPS",
                "EVALUATION_WORKER_ECS_SECURITY_GROUPS",
            )
        ),
        ecs_image_uri=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_IMAGE_URI",
            "EVALUATION_WORKER_ECS_IMAGE_URI",
            default="",
        )
        or "",
        ecs_execution_role_arn=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN",
            "EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN",
            default="",
        )
        or "",
        ecs_task_role_arn=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_TASK_ROLE_ARN",
            "EVALUATION_WORKER_ECS_TASK_ROLE_ARN",
            default="",
        )
        or "",
        ecs_cpu=_env_int(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_CPU",
            "EVALUATION_WORKER_ECS_CPU",
            default=1024,
        ),
        ecs_memory=_env_int(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_MEMORY",
            "EVALUATION_WORKER_ECS_MEMORY",
            default=2048,
        ),
        ecs_log_group=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_LOG_GROUP",
            "EVALUATION_WORKER_ECS_LOG_GROUP",
            default=DEFAULT_LOG_GROUP,
        )
        or DEFAULT_LOG_GROUP,
        ecs_log_stream_prefix=_env_value(
            source,
            "DEPLOY_EVALUATION_WORKER_ECS_LOG_STREAM_PREFIX",
            "EVALUATION_WORKER_ECS_LOG_STREAM_PREFIX",
            default=DEFAULT_LOG_STREAM_PREFIX,
        )
        or DEFAULT_LOG_STREAM_PREFIX,
        worker_env=worker_env,
        secret_arn_map=secret_arn_map,
    )


def _worker_environment(config: EvaluationWorkerDeployConfig) -> list[dict[str, str]]:
    environment = [
        {"name": "AWS_REGION", "value": config.aws_region},
        {"name": "AWS_DEFAULT_REGION", "value": config.aws_region},
    ]
    for key in WORKER_ENV_KEYS:
        if key in {"AWS_REGION", "AWS_DEFAULT_REGION"}:
            continue
        value = config.worker_env.get(key)
        if value is not None and value != "":
            environment.append({"name": key, "value": value})
    return environment


def _worker_secrets(config: EvaluationWorkerDeployConfig) -> list[dict[str, str]]:
    secrets: list[dict[str, str]] = []
    for key in SECRET_ENV_KEYS:
        value_from = config.secret_arn_map.get(key)
        if value_from:
            secrets.append({"name": key, "valueFrom": value_from})
    return secrets


def build_task_definition(config: EvaluationWorkerDeployConfig) -> dict[str, Any]:
    """Build the ECS task definition payload for the evaluation worker."""
    container_def: dict[str, Any] = {
        "name": config.ecs_container_name,
        "image": config.ecs_image_uri,
        "essential": True,
        "command": ["python", "-m", "model_eval.evaluation_worker"],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": config.ecs_log_group,
                "awslogs-region": config.aws_region,
                "awslogs-stream-prefix": config.ecs_log_stream_prefix,
            },
        },
        "environment": _worker_environment(config),
    }
    secrets = _worker_secrets(config)
    if secrets:
        container_def["secrets"] = secrets

    return {
        "family": config.ecs_task_family,
        "networkMode": "awsvpc",
        "requiresCompatibilities": [config.ecs_launch_type],
        "cpu": str(config.ecs_cpu),
        "memory": str(config.ecs_memory),
        "executionRoleArn": config.ecs_execution_role_arn,
        "taskRoleArn": config.ecs_task_role_arn,
        "runtimePlatform": {
            "operatingSystemFamily": "LINUX",
            "cpuArchitecture": "X86_64",
        },
        "containerDefinitions": [container_def],
    }


def build_backend_env_fragment(config: EvaluationWorkerDeployConfig) -> list[str]:
    """Build the env lines that backend launcher code should copy into `.env`."""
    lines: list[str] = []
    mapping = {
        "AWS_REGION": config.aws_region,
        "AWS_PROFILE": config.aws_profile,
        "EVALUATION_WORKER_ECS_CLUSTER": config.ecs_cluster,
        "EVALUATION_WORKER_ECS_TASK_DEFINITION": config.ecs_task_definition,
        "EVALUATION_WORKER_ECS_CONTAINER_NAME": config.ecs_container_name,
        "EVALUATION_WORKER_ECS_LAUNCH_TYPE": config.ecs_launch_type,
        "EVALUATION_WORKER_ECS_PLATFORM_VERSION": config.ecs_platform_version,
        "EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP": config.ecs_assign_public_ip,
        "EVALUATION_WORKER_ECS_SUBNETS": ",".join(config.ecs_subnet_ids),
        "EVALUATION_WORKER_ECS_SECURITY_GROUPS": ",".join(
            config.ecs_security_group_ids
        ),
    }
    for key in BACKEND_ENV_KEYS:
        value = mapping.get(key)
        if value:
            lines.append(f"{key}={value}")
    return lines


def missing_registration_values(config: EvaluationWorkerDeployConfig) -> list[str]:
    """Return the ECS values required to register the task definition."""
    missing: list[str] = []
    if not config.ecs_image_uri:
        missing.append("EVALUATION_WORKER_ECS_IMAGE_URI")
    if not config.ecs_execution_role_arn:
        missing.append("EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN")
    if not config.ecs_task_role_arn:
        missing.append("EVALUATION_WORKER_ECS_TASK_ROLE_ARN")
    return missing


def missing_backend_launch_values(config: EvaluationWorkerDeployConfig) -> list[str]:
    """Return the ECS values required for the backend `run-task` launcher."""
    missing: list[str] = []
    if not config.ecs_cluster:
        missing.append("EVALUATION_WORKER_ECS_CLUSTER")
    if not config.ecs_task_definition:
        missing.append("EVALUATION_WORKER_ECS_TASK_DEFINITION")
    if not config.ecs_subnet_ids:
        missing.append("EVALUATION_WORKER_ECS_SUBNETS")
    if not config.ecs_security_group_ids:
        missing.append("EVALUATION_WORKER_ECS_SECURITY_GROUPS")
    return missing


def describe_config(config: EvaluationWorkerDeployConfig) -> list[str]:
    """Return a human-readable summary of the worker deployment settings."""
    lines = [
        "==> ECS evaluation worker",
        f"    Region:           {config.aws_region}",
        f"    Profile:          {config.aws_profile or '(default credential chain)'}",
        f"    Task family:      {config.ecs_task_family}",
        f"    Task definition:  {config.ecs_task_definition}",
        f"    Container:        {config.ecs_container_name}",
        f"    Launch type:      {config.ecs_launch_type}",
        f"    Platform version: {config.ecs_platform_version}",
        f"    Assign public IP: {config.ecs_assign_public_ip}",
        f"    Subnets:          {', '.join(config.ecs_subnet_ids) or '(missing)'}",
        f"    Security groups:  {', '.join(config.ecs_security_group_ids) or '(missing)'}",
        f"    Image URI:        {config.ecs_image_uri or '(missing)'}",
        f"    Exec role ARN:    {config.ecs_execution_role_arn or '(missing)'}",
        f"    Task role ARN:    {config.ecs_task_role_arn or '(missing)'}",
        f"    CPU / Memory:     {config.ecs_cpu} / {config.ecs_memory}",
        f"    Log group:        {config.ecs_log_group}",
        f"    Log prefix:       {config.ecs_log_stream_prefix}",
    ]
    registration_missing = missing_registration_values(config)
    backend_missing = missing_backend_launch_values(config)
    lines.append(
        "    Task definition values missing: "
        + (", ".join(registration_missing) if registration_missing else "(none)"),
    )
    lines.append(
        "    Backend launch values missing: "
        + (", ".join(backend_missing) if backend_missing else "(none)"),
    )
    secret_keys = sorted(config.secret_arn_map)
    if secret_keys:
        lines.append("    Secret ARN mappings: " + ", ".join(secret_keys))
    else:
        lines.append("    Secret ARN mappings: (none)")
    return lines


def _ecs_client(config: EvaluationWorkerDeployConfig):
    import boto3

    session = boto3.Session(
        profile_name=config.aws_profile,
        region_name=config.aws_region,
    )
    return session.client("ecs")


def register_task_definition(
    config: EvaluationWorkerDeployConfig,
    *,
    client=None,
) -> dict[str, Any]:
    """Register the evaluation worker task definition with ECS."""
    missing = missing_registration_values(config)
    if missing:
        raise ValueError(
            "Missing required values: " + ", ".join(missing),
        )
    payload = build_task_definition(config)
    ecs_client = client or _ecs_client(config)
    response = ecs_client.register_task_definition(**payload)
    task_definition = response.get("taskDefinition", {}) if isinstance(response, dict) else {}
    return {
        "taskDefinitionArn": task_definition.get("taskDefinitionArn"),
        "family": task_definition.get("family", config.ecs_task_family),
        "revision": task_definition.get("revision"),
    }


def _write_output(output: str, output_path: Path | None) -> None:
    if output_path is None:
        print(output)
        return
    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote {output_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Describe or register the ECS evaluation worker task definition.",
    )
    parser.add_argument(
        "action",
        choices=(
            "describe",
            "render-task-definition",
            "render-backend-env",
            "register-task-definition",
        ),
        help="Inspect the worker config, render JSON, or register the task definition",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write the rendered JSON or env fragment",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        help="AWS region for ECS registration (default: AWS_REGION or us-east-1)",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE"),
        help="Optional AWS profile for boto3",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    env = dict(os.environ)
    env["AWS_REGION"] = args.region
    if args.profile:
        env["AWS_PROFILE"] = args.profile
    else:
        env.pop("AWS_PROFILE", None)

    config = load_evaluation_worker_config(env)

    if args.action == "describe":
        _write_output("\n".join(describe_config(config)), args.output)
        return 0

    if args.action == "render-task-definition":
        payload = build_task_definition(config)
        _write_output(json.dumps(payload, indent=2, sort_keys=True), args.output)
        return 0

    if args.action == "render-backend-env":
        _write_output("\n".join(build_backend_env_fragment(config)), args.output)
        return 0

    if args.action == "register-task-definition":
        missing = missing_registration_values(config)
        if missing:
            parser.error(
                "Missing required values. Run describe and fill in the missing fields.",
            )
        response = register_task_definition(config)
        _write_output(json.dumps(response, indent=2, sort_keys=True), args.output)
        return 0

    parser.error(f"Unknown action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
