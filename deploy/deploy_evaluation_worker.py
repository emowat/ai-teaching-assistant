"""Render, register, and deploy the ECS evaluation worker task definition.

Loads settings from deploy/deployment.yaml (with env var overrides) via
deployment_config.load_deploy_config(), the same way deploy_rag_eng_ecs.py
does - so this script is fully self-sufficient via `uv run` and does not
need deploy/scripts/deploy-evaluation-worker.sh to bridge YAML values into
flat env vars first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


load_dotenv()

DEPLOY_DIR = Path(__file__).resolve().parent
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

from deployment_config import DeployConfig, load_deploy_config  # noqa: E402
from evaluation_worker_image import (  # noqa: E402
    EvaluationWorkerImageConfig,
    build_and_push_image,
)
from evaluation_worker_image import (  # noqa: E402
    DEFAULT_IMAGE_TAG as DEFAULT_IMAGE_BUILD_TAG,
)
from evaluation_worker_image import (  # noqa: E402
    DEFAULT_REPOSITORY_NAME as DEFAULT_IMAGE_REPOSITORY_NAME,
)
from evaluation_worker_image import REPO_ROOT as IMAGE_REPO_ROOT  # noqa: E402


# Aurora password-rotation self-heal wiring for rag_eng/aurora_secret_refresh.py:
# the AWS-managed secret's ARN itself (not our app secret's - that one is never
# touched by Aurora's rotation) plus the stable connection details needed to
# rebuild a full URL from just a refreshed username/password. These are plain
# process env vars (typically from .env), not deployment.yaml settings - they
# don't belong alongside EVALUATION_* judge/output tuning there.
AURORA_SELF_HEAL_ENV_KEYS: tuple[str, ...] = (
    "COURSE_REGISTRY_DATABASE_URL_SECRET_ID",
    "COURSE_REGISTRY_DB_HOST",
    "COURSE_REGISTRY_DB_PORT",
    "COURSE_REGISTRY_DB_NAME",
    "COURSE_REGISTRY_DB_SSLMODE",
)


def _worker_environment(config: DeployConfig) -> list[dict[str, str]]:
    ew = config.evaluation_worker
    env = dict(ew.environment)
    env["AWS_REGION"] = config.aws.region
    env["AWS_DEFAULT_REGION"] = config.aws.region
    for key in AURORA_SELF_HEAL_ENV_KEYS:
        value = os.getenv(key)
        if value:
            env[key] = value

    environment: list[dict[str, str]] = []
    for key in sorted(env):
        value = env[key]
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        environment.append({"name": key, "value": text})
    return environment


def _worker_secrets(config: DeployConfig) -> list[dict[str, str]]:
    secrets: list[dict[str, str]] = []
    for key, value_from in sorted(config.evaluation_worker.secret_arn_map.items()):
        if value_from:
            secrets.append({"name": key, "valueFrom": value_from})
    return secrets


def build_task_definition(config: DeployConfig) -> dict[str, Any]:
    """Build the ECS task definition payload for the evaluation worker."""
    ew = config.evaluation_worker
    container_def: dict[str, Any] = {
        "name": ew.container_name,
        "image": ew.image_uri,
        "essential": True,
        "command": ["python", "-m", "model_eval.evaluation_worker"],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": ew.log_group,
                "awslogs-region": config.aws.region,
                "awslogs-stream-prefix": ew.log_stream_prefix,
            },
        },
        "environment": _worker_environment(config),
    }
    secrets = _worker_secrets(config)
    if secrets:
        container_def["secrets"] = secrets

    return {
        "family": ew.task_family,
        "networkMode": "awsvpc",
        "requiresCompatibilities": [ew.launch_type],
        "cpu": str(ew.cpu),
        "memory": str(ew.memory),
        "executionRoleArn": ew.execution_role_arn,
        "taskRoleArn": ew.task_role_arn,
        "runtimePlatform": {
            "operatingSystemFamily": "LINUX",
            "cpuArchitecture": "X86_64",
        },
        "containerDefinitions": [container_def],
    }


def build_backend_env_fragment(config: DeployConfig) -> list[str]:
    """Build the env lines that backend launcher code should copy into `.env`."""
    ew = config.evaluation_worker
    mapping = {
        "AWS_REGION": config.aws.region,
        "AWS_PROFILE": config.aws.profile,
        "EVALUATION_WORKER_ECS_CLUSTER": ew.cluster,
        "EVALUATION_WORKER_ECS_TASK_DEFINITION": ew.task_definition,
        "EVALUATION_WORKER_ECS_CONTAINER_NAME": ew.container_name,
        "EVALUATION_WORKER_ECS_LAUNCH_TYPE": ew.launch_type,
        "EVALUATION_WORKER_ECS_PLATFORM_VERSION": ew.platform_version,
        "EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP": ew.assign_public_ip,
        "EVALUATION_WORKER_ECS_SUBNETS": ",".join(ew.subnet_ids),
        "EVALUATION_WORKER_ECS_SECURITY_GROUPS": ",".join(ew.security_group_ids),
    }
    return [f"{key}={value}" for key, value in mapping.items() if value]


def missing_registration_values(config: DeployConfig) -> list[str]:
    """Return the ECS values required to register the task definition."""
    ew = config.evaluation_worker
    missing: list[str] = []
    if not ew.image_uri:
        missing.append("EVALUATION_WORKER_ECS_IMAGE_URI")
    if not ew.execution_role_arn:
        missing.append("EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN")
    if not ew.task_role_arn:
        missing.append("EVALUATION_WORKER_ECS_TASK_ROLE_ARN")
    return missing


def missing_backend_launch_values(config: DeployConfig) -> list[str]:
    """Return the ECS values required for the backend `run-task` launcher."""
    ew = config.evaluation_worker
    missing: list[str] = []
    if not ew.cluster:
        missing.append("EVALUATION_WORKER_ECS_CLUSTER")
    if not ew.task_definition:
        missing.append("EVALUATION_WORKER_ECS_TASK_DEFINITION")
    if not ew.subnet_ids:
        missing.append("EVALUATION_WORKER_ECS_SUBNETS")
    if not ew.security_group_ids:
        missing.append("EVALUATION_WORKER_ECS_SECURITY_GROUPS")
    return missing


def describe_config(config: DeployConfig) -> list[str]:
    """Return a human-readable summary of the worker deployment settings."""
    ew = config.evaluation_worker
    lines = [
        "==> ECS evaluation worker",
        f"    Region:           {config.aws.region}",
        f"    Profile:          {config.aws.profile or '(default credential chain)'}",
        f"    Task family:      {ew.task_family}",
        f"    Task definition:  {ew.task_definition}",
        f"    Container:        {ew.container_name}",
        f"    Launch type:      {ew.launch_type}",
        f"    Platform version: {ew.platform_version}",
        f"    Assign public IP: {ew.assign_public_ip}",
        f"    Subnets:          {', '.join(ew.subnet_ids) or '(missing)'}",
        f"    Security groups:  {', '.join(ew.security_group_ids) or '(missing)'}",
        f"    Image URI:        {ew.image_uri or '(missing)'}",
        f"    Exec role ARN:    {ew.execution_role_arn or '(missing)'}",
        f"    Task role ARN:    {ew.task_role_arn or '(missing)'}",
        f"    CPU / Memory:     {ew.cpu} / {ew.memory}",
        f"    Log group:        {ew.log_group}",
        f"    Log prefix:       {ew.log_stream_prefix}",
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
    secret_keys = sorted(ew.secret_arn_map)
    lines.append(
        "    Secret ARN mappings: " + (", ".join(secret_keys) if secret_keys else "(none)")
    )
    return lines


def _ecs_client(config: DeployConfig):
    import boto3

    session = boto3.Session(
        profile_name=config.aws.profile,
        region_name=config.aws.region,
    )
    return session.client("ecs")


def register_task_definition(
    config: DeployConfig,
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
        "family": task_definition.get("family", config.evaluation_worker.task_family),
        "revision": task_definition.get("revision"),
    }


def deploy_worker(
    config: DeployConfig,
    *,
    docker_binary: str = "docker",
) -> dict[str, Any]:
    """Build and push the worker image, then register a task definition
    pointing at the freshly-pushed image (overriding whatever image_uri is
    configured, since that value would otherwise still point at the
    previous build).
    """
    image_config = EvaluationWorkerImageConfig(
        aws_region=config.aws.region,
        aws_profile=config.aws.profile,
        repository_name=os.getenv("EVALUATION_WORKER_ECR_REPOSITORY", DEFAULT_IMAGE_REPOSITORY_NAME),
        image_tag=os.getenv("EVALUATION_WORKER_ECR_IMAGE_TAG", DEFAULT_IMAGE_BUILD_TAG),
        repo_root=IMAGE_REPO_ROOT,
    )
    image_uri = build_and_push_image(config=image_config, docker_binary=docker_binary)
    registration_config = replace(
        config,
        evaluation_worker=replace(config.evaluation_worker, image_uri=image_uri),
    )
    result = register_task_definition(registration_config)
    result["imageUri"] = image_uri
    return result


def _write_output(output: str, output_path: Path | None) -> None:
    if output_path is None:
        print(output)
        return
    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote {output_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Describe, render, register, or deploy the ECS evaluation worker task definition.",
    )
    parser.add_argument(
        "action",
        choices=(
            "describe",
            "render-task-definition",
            "render-backend-env",
            "register-task-definition",
            "deploy",
        ),
        help=(
            "Inspect the worker config, render JSON, register the task "
            "definition, or build+push the image and register in one step"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write the rendered JSON or env fragment",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to deployment.yaml (default: deploy/deployment.yaml or DEPLOY_CONFIG)",
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

    os.environ["AWS_REGION"] = args.region
    if args.profile:
        os.environ["AWS_PROFILE"] = args.profile
    else:
        os.environ.pop("AWS_PROFILE", None)

    config = load_deploy_config(args.config)

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

    if args.action == "deploy":
        # Image URI is produced by the build+push step below, not required
        # up front - every other registration value still is.
        missing = [
            value
            for value in missing_registration_values(config)
            if value != "EVALUATION_WORKER_ECS_IMAGE_URI"
        ]
        if missing:
            parser.error(
                "Missing required values: "
                + ", ".join(missing)
                + ". Run describe and fill in the missing fields.",
            )
        response = deploy_worker(config)
        _write_output(json.dumps(response, indent=2, sort_keys=True), args.output)
        return 0

    parser.error(f"Unknown action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
