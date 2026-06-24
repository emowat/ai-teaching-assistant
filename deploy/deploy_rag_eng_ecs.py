"""Render and deploy the `rag_eng` ECS/Fargate orchestrator service.

This helper keeps the AWS service wiring in one place:

- describe the orchestrator deployment settings
- render the ECS task definition payload
- render the ECS service spec for review
- register the task definition with ECS
- create or update the ECS service behind the ALB target group

The runtime application still lives in `rag_eng`; this module only manages the
AWS deployment surface.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import boto3
from dotenv import load_dotenv


load_dotenv()

_DEPLOY_DIR = Path(__file__).resolve().parent
if str(_DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOY_DIR))

from deployment_config import DeployConfig, RagEngEcsConfig, load_deploy_config  # noqa: E402


REQUIRED_ENV_KEYS: tuple[str, ...] = (
    "APP_PORT",
    "AWS_REGION",
    "CORS_ORIGINS",
    "COGNITO_REGION",
    "COGNITO_USER_POOL_ID",
    "COGNITO_APP_CLIENT_ID",
    "COGNITO_ISSUER",
    "COGNITO_JWKS_URL",
    "LOG_LEVEL",
    "OPENAI_BASE_URL",
    "QDRANT_URL",
    "QDRANT_COLLECTION_NAME",
    "QDRANT_GUIDELINES_COLLECTION_NAME",
    "QDRANT_HARVARD_COLLECTION_NAME",
    "QDRANT_COLLECTION_MIT13",
    "QDRANT_COLLECTION_MIT14",
    "QDRANT_COLLECTION_CS50",
    "QDRANT_COLLECTION_GUIDELINES",
    "EMBEDDING_MODEL",
    "INPUT_GUARDRAILS_ENABLED",
    "INPUT_GUARDRAILS_CODEBERT_S3_URI",
    "INPUT_GUARDRAILS_CODEBERT_CHECKPOINT_DIR",
    "INPUT_GUARDRAILS_CODEBERT_PASS_BELOW",
    "INPUT_GUARDRAILS_CODEBERT_BLOCK_ABOVE",
    "USE_SAGEMAKER",
    "SAGEMAKER_ENDPOINT",
    "SAGEMAKER_INFERENCE_BACKEND",
    "SAGEMAKER_POLL_TIMEOUT_SECONDS",
    "S3_DATA_BUCKET",
    "MODEL_FAMILY",
)


def _ecs_client(config: DeployConfig):
    session = boto3.Session(
        profile_name=config.aws.profile,
        region_name=config.aws.region,
    )
    return session.client("ecs")


def _task_environment(config: RagEngEcsConfig, region: str) -> list[dict[str, str]]:
    env = dict(config.environment)
    env["APP_PORT"] = str(config.container_port)
    env["AWS_REGION"] = region
    env["AWS_DEFAULT_REGION"] = region

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


def _task_secrets(config: RagEngEcsConfig) -> list[dict[str, str]]:
    secrets: list[dict[str, str]] = []
    for key in sorted(config.secret_arn_map):
        value_from = config.secret_arn_map[key]
        if value_from:
            secrets.append({"name": key, "valueFrom": value_from})
    return secrets


def _missing_required_env_values(config: RagEngEcsConfig) -> list[str]:
    missing: list[str] = []
    env = config.environment
    for key in REQUIRED_ENV_KEYS:
        value = env.get(key)
        if value is None or str(value).strip() == "":
            missing.append(key)
    if config.container_port and str(env.get("APP_PORT", "")).strip() not in {
        "",
        str(config.container_port),
    }:
        missing.append("APP_PORT")
    return missing


def build_task_definition(config: DeployConfig) -> dict[str, Any]:
    """Build the ECS task definition payload for the orchestrator container."""
    ecs = config.rag_eng_ecs
    container_def: dict[str, Any] = {
        "name": ecs.container_name,
        "image": ecs.image_uri,
        "essential": True,
        "portMappings": [
            {"containerPort": ecs.container_port, "protocol": "tcp"},
        ],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": ecs.log_group,
                "awslogs-region": config.aws.region,
                "awslogs-stream-prefix": ecs.log_stream_prefix,
            },
        },
        "environment": _task_environment(ecs, config.aws.region),
    }
    secrets = _task_secrets(ecs)
    if secrets:
        container_def["secrets"] = secrets

    return {
        "family": ecs.task_family,
        "networkMode": "awsvpc",
        "requiresCompatibilities": [ecs.launch_type],
        "cpu": str(ecs.cpu),
        "memory": str(ecs.memory),
        "executionRoleArn": ecs.execution_role_arn,
        "taskRoleArn": ecs.task_role_arn,
        "runtimePlatform": {
            "operatingSystemFamily": "LINUX",
            "cpuArchitecture": "X86_64",
        },
        "containerDefinitions": [container_def],
    }


def build_service_spec(
    config: DeployConfig,
    *,
    task_definition: str | None = None,
) -> dict[str, Any]:
    """Build the ECS service spec for the orchestrator ALB deployment."""
    ecs = config.rag_eng_ecs
    spec: dict[str, Any] = {
        "cluster": ecs.cluster,
        "serviceName": ecs.service_name,
        "taskDefinition": task_definition or ecs.task_definition or ecs.task_family,
        "desiredCount": ecs.desired_count,
        "launchType": ecs.launch_type,
        "platformVersion": ecs.platform_version,
        "healthCheckGracePeriodSeconds": ecs.health_check_grace_period_seconds,
        "deploymentConfiguration": {
            "maximumPercent": 200,
            "minimumHealthyPercent": 100,
            "deploymentCircuitBreaker": {"enable": True, "rollback": True},
        },
        "networkConfiguration": {
            "awsvpcConfiguration": {
                "subnets": list(ecs.subnet_ids),
                "securityGroups": list(ecs.security_group_ids),
                "assignPublicIp": ecs.assign_public_ip,
            }
        },
    }
    if ecs.target_group_arn:
        spec["loadBalancers"] = [
            {
                "targetGroupArn": ecs.target_group_arn,
                "containerName": ecs.container_name,
                "containerPort": ecs.container_port,
            }
        ]
    return spec


def missing_registration_values(config: DeployConfig) -> list[str]:
    """Return the ECS task-definition values that are still missing."""
    ecs = config.rag_eng_ecs
    missing: list[str] = []
    if not ecs.image_uri:
        missing.append("RAG_ENG_ECS_IMAGE_URI")
    if not ecs.execution_role_arn:
        missing.append("RAG_ENG_ECS_EXECUTION_ROLE_ARN")
    if not ecs.task_role_arn:
        missing.append("RAG_ENG_ECS_TASK_ROLE_ARN")
    missing.extend(
        f"RAG_ENG_ECS_SECRET_ARNS_JSON[{key}]"
        for key, value in sorted(ecs.secret_arn_map.items())
        if value is None or str(value).strip() == ""
    )
    missing.extend(
        f"RAG_ENG_ECS_ENV[{key}]"
        for key in _missing_required_env_values(ecs)
    )
    return missing


def missing_service_values(config: DeployConfig) -> list[str]:
    """Return the ECS service values that are still missing."""
    ecs = config.rag_eng_ecs
    missing: list[str] = []
    if not ecs.cluster:
        missing.append("RAG_ENG_ECS_CLUSTER")
    if not ecs.service_name:
        missing.append("RAG_ENG_ECS_SERVICE_NAME")
    if not ecs.subnet_ids:
        missing.append("RAG_ENG_ECS_SUBNETS")
    if not ecs.security_group_ids:
        missing.append("RAG_ENG_ECS_SECURITY_GROUPS")
    if not ecs.target_group_arn:
        missing.append("RAG_ENG_ECS_TARGET_GROUP_ARN")
    return missing


def describe_config(config: DeployConfig) -> list[str]:
    """Return a human-readable summary of the orchestrator deployment settings."""
    ecs = config.rag_eng_ecs
    lines = [
        "==> rag_eng ECS service",
        f"    Region:           {config.aws.region}",
        f"    Profile:          {config.aws.profile or '(default credential chain)'}",
        f"    Cluster:          {ecs.cluster or '(missing)'}",
        f"    Service:          {ecs.service_name or '(missing)'}",
        f"    Task family:      {ecs.task_family or '(missing)'}",
        f"    Task definition:  {ecs.task_definition or '(missing)'}",
        f"    Container:        {ecs.container_name or '(missing)'}",
        f"    Image URI:        {ecs.image_uri or '(missing)'}",
        f"    Exec role ARN:    {ecs.execution_role_arn or '(missing)'}",
        f"    Task role ARN:    {ecs.task_role_arn or '(missing)'}",
        f"    CPU / Memory:     {ecs.cpu} / {ecs.memory}",
        f"    Container port:   {ecs.container_port}",
        f"    Desired count:    {ecs.desired_count}",
        f"    Health path:      {ecs.health_check_path}",
        f"    Target group ARN: {ecs.target_group_arn or '(missing)'}",
        f"    Launch type:      {ecs.launch_type}",
        f"    Platform version: {ecs.platform_version}",
        f"    Assign public IP: {ecs.assign_public_ip}",
        f"    Subnets:          {', '.join(ecs.subnet_ids) or '(missing)'}",
        f"    Security groups:  {', '.join(ecs.security_group_ids) or '(missing)'}",
        f"    Log group:        {ecs.log_group}",
        f"    Log prefix:       {ecs.log_stream_prefix}",
    ]
    registration_missing = missing_registration_values(config)
    service_missing = missing_service_values(config)
    runtime_missing = _missing_required_env_values(ecs)
    lines.append(
        "    Task definition values missing: "
        + (", ".join(registration_missing) if registration_missing else "(none)"),
    )
    lines.append(
        "    Service launch values missing: "
        + (", ".join(service_missing) if service_missing else "(none)"),
    )
    lines.append(
        "    Runtime env values missing: "
        + (", ".join(runtime_missing) if runtime_missing else "(none)"),
    )
    secret_keys = sorted(ecs.secret_arn_map)
    lines.append("    Secret keys: " + (", ".join(secret_keys) if secret_keys else "(none)"))
    return lines


def _register_task_definition(
    config: DeployConfig,
    *,
    client=None,
) -> dict[str, Any]:
    missing = missing_registration_values(config)
    if missing:
        raise ValueError("Missing required values: " + ", ".join(missing))
    payload = build_task_definition(config)
    ecs_client = client or _ecs_client(config)
    response = ecs_client.register_task_definition(**payload)
    task_definition = response.get("taskDefinition", {}) if isinstance(response, dict) else {}
    return {
        "taskDefinitionArn": task_definition.get("taskDefinitionArn"),
        "family": task_definition.get("family", config.rag_eng_ecs.task_family),
        "revision": task_definition.get("revision"),
    }


def _upsert_service(
    config: DeployConfig,
    *,
    task_definition: str,
    client=None,
) -> dict[str, Any]:
    ecs = config.rag_eng_ecs
    missing = missing_service_values(config)
    if missing:
        raise ValueError("Missing required values: " + ", ".join(missing))

    ecs_client = client or _ecs_client(config)
    payload = build_service_spec(config, task_definition=task_definition)
    service_name = ecs.service_name
    cluster = ecs.cluster

    existing = ecs_client.describe_services(cluster=cluster, services=[service_name])
    services = existing.get("services", []) if isinstance(existing, dict) else []
    service = services[0] if services else None

    if not service or service.get("status") == "INACTIVE":
        response = ecs_client.create_service(**payload)
        service = response.get("service", {}) if isinstance(response, dict) else {}
        action = "created"
    else:
        response = ecs_client.update_service(
            cluster=cluster,
            service=service_name,
            taskDefinition=task_definition,
            desiredCount=ecs.desired_count,
            platformVersion=ecs.platform_version,
            launchType=ecs.launch_type,
            loadBalancers=payload.get("loadBalancers", []),
            networkConfiguration=payload["networkConfiguration"],
            healthCheckGracePeriodSeconds=ecs.health_check_grace_period_seconds,
            deploymentConfiguration=payload["deploymentConfiguration"],
            forceNewDeployment=True,
        )
        service = response.get("service", {}) if isinstance(response, dict) else {}
        action = "updated"

    return {
        "action": action,
        "serviceArn": service.get("serviceArn"),
        "status": service.get("status"),
        "runningCount": service.get("runningCount"),
        "desiredCount": service.get("desiredCount"),
        "taskDefinition": service.get("taskDefinition", task_definition),
    }


def _service_status(config: DeployConfig, *, client=None) -> dict[str, Any]:
    ecs = config.rag_eng_ecs
    ecs_client = client or _ecs_client(config)
    response = ecs_client.describe_services(
        cluster=ecs.cluster,
        services=[ecs.service_name],
    )
    services = response.get("services", []) if isinstance(response, dict) else []
    service = services[0] if services else {}
    return {
        "status": service.get("status"),
        "runningCount": service.get("runningCount"),
        "desiredCount": service.get("desiredCount"),
        "taskDefinition": service.get("taskDefinition"),
        "serviceArn": service.get("serviceArn"),
        "events": service.get("events", []),
        "deployments": service.get("deployments", []),
    }


def _write_output(output: str, output_path: Path | None) -> None:
    if output_path is None:
        print(output)
        return
    output_path.write_text(output, encoding="utf-8")
    print(f"Wrote {output_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Describe, render, or deploy the rag_eng ECS service.",
    )
    parser.add_argument(
        "action",
        choices=(
            "describe",
            "render-task-definition",
            "render-service-spec",
            "register-task-definition",
            "deploy",
            "status",
        ),
        help="Inspect the service config, render JSON, register the task definition, or deploy the ECS service",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional file path to write rendered JSON output",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to deployment.yaml (default: deploy/deployment.yaml or DEPLOY_CONFIG)",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
        help="AWS region for ECS calls (default: AWS_REGION or us-east-1)",
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

    if args.action == "render-service-spec":
        payload = build_service_spec(config)
        _write_output(json.dumps(payload, indent=2, sort_keys=True), args.output)
        return 0

    if args.action == "register-task-definition":
        response = _register_task_definition(config)
        _write_output(json.dumps(response, indent=2, sort_keys=True), args.output)
        return 0

    if args.action == "deploy":
        registered = _register_task_definition(config)
        deployed = _upsert_service(
            config,
            task_definition=registered["taskDefinitionArn"] or registered["family"],
        )
        output = {
            "task_definition": registered,
            "service": deployed,
        }
        _write_output(json.dumps(output, indent=2, sort_keys=True), args.output)
        return 0

    if args.action == "status":
        status = _service_status(config)
        _write_output(json.dumps(status, indent=2, sort_keys=True), args.output)
        return 0

    parser.error(f"Unknown action: {args.action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
