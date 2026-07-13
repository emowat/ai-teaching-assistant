from __future__ import annotations

import json
from pathlib import Path

from deploy.deploy_evaluation_worker import (
    build_backend_env_fragment,
    build_task_definition,
    describe_config,
    load_evaluation_worker_config,
    missing_backend_launch_values,
    missing_registration_values,
    register_task_definition,
)


def _env() -> dict[str, str]:
    return {
        "AWS_REGION": "us-east-1",
        "AWS_PROFILE": "codingrabbit-dev",
        "DEPLOY_EVALUATION_WORKER_ECS_CLUSTER": "codingrabbit-rag-eng",
        "DEPLOY_EVALUATION_WORKER_ECS_TASK_FAMILY": "codingrabbit-evaluation-worker",
        "DEPLOY_EVALUATION_WORKER_ECS_TASK_DEFINITION": "codingrabbit-evaluation-worker",
        "DEPLOY_EVALUATION_WORKER_ECS_CONTAINER_NAME": "evaluation-worker",
        "DEPLOY_EVALUATION_WORKER_ECS_LAUNCH_TYPE": "FARGATE",
        "DEPLOY_EVALUATION_WORKER_ECS_PLATFORM_VERSION": "LATEST",
        "DEPLOY_EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP": "ENABLED",
        "DEPLOY_EVALUATION_WORKER_ECS_SUBNETS": "subnet-a, subnet-b",
        "DEPLOY_EVALUATION_WORKER_ECS_SECURITY_GROUPS": "sg-a",
        "DEPLOY_EVALUATION_WORKER_ECS_IMAGE_URI": "123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-rag-eng:latest",
        "DEPLOY_EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
        "DEPLOY_EVALUATION_WORKER_ECS_TASK_ROLE_ARN": "arn:aws:iam::123456789012:role/codingrabbit-rag-eng-task",
        "DEPLOY_EVALUATION_WORKER_ECS_SECRET_ARNS_JSON": json.dumps(
            {
                "COURSE_REGISTRY_DATABASE_URL": "arn:aws:secretsmanager:us-east-1:123456789012:secret:db",
                "OPENAI_API_KEY": "arn:aws:secretsmanager:us-east-1:123456789012:secret:openai",
            }
        ),
        "S3_DATA_BUCKET": "codingrabbit-data-dev",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "EVALUATION_DEFAULT_JUDGE_PROVIDER": "bedrock",
        "EVALUATION_DEFAULT_JUDGE_MODEL": "anthropic.claude-haiku-4-5",
        "EVALUATION_HOMEWORK_N": "7",
        "EVALUATION_STUDY_N": "9",
        "EVALUATION_JUDGE_TEMPERATURE": "0.1",
        "EVALUATION_JUDGE_TOP_P": "0.2",
        "EVALUATION_JUDGE_TIMEOUT_SECONDS": "11",
        "EVALUATION_JUDGE_MAX_CONCURRENCY": "5",
        "EVALUATION_JUDGE_MAX_TOKENS": "256",
        "EVALUATION_EXPORT_TZ": "America/Los_Angeles",
        "EVALUATION_WRITE_AURORA": "true",
        "LOG_LEVEL": "INFO",
    }


def test_load_evaluation_worker_config_reads_env_and_secret_mappings() -> None:
    config = load_evaluation_worker_config(_env())

    assert config.aws_region == "us-east-1"
    assert config.aws_profile == "codingrabbit-dev"
    assert config.ecs_cluster == "codingrabbit-rag-eng"
    assert config.ecs_task_definition == "codingrabbit-evaluation-worker"
    assert config.ecs_image_uri.endswith("/codingrabbit-rag-eng:latest")
    assert config.ecs_execution_role_arn.endswith("ecsTaskExecutionRole")
    assert config.ecs_task_role_arn.endswith("codingrabbit-rag-eng-task")
    assert config.ecs_subnet_ids == ("subnet-a", "subnet-b")
    assert config.ecs_security_group_ids == ("sg-a",)
    assert config.secret_arn_map["COURSE_REGISTRY_DATABASE_URL"].endswith(":secret:db")
    assert config.secret_arn_map["OPENAI_API_KEY"].endswith(":secret:openai")


def test_build_task_definition_includes_worker_env_and_secrets() -> None:
    config = load_evaluation_worker_config(_env())
    payload = build_task_definition(config)

    assert payload["family"] == "codingrabbit-evaluation-worker"
    assert payload["networkMode"] == "awsvpc"
    assert payload["requiresCompatibilities"] == ["FARGATE"]
    assert payload["cpu"] == "1024"
    assert payload["memory"] == "2048"
    assert payload["executionRoleArn"].endswith("ecsTaskExecutionRole")
    assert payload["taskRoleArn"].endswith("codingrabbit-rag-eng-task")

    container = payload["containerDefinitions"][0]
    assert container["name"] == "evaluation-worker"
    assert container["image"].endswith("/codingrabbit-rag-eng:latest")
    assert container["command"] == ["python", "-m", "model_eval.evaluation_worker"]
    assert container["logConfiguration"]["options"]["awslogs-group"] == (
        "/ecs/codingrabbit-evaluation-worker"
    )

    env_map = {item["name"]: item["value"] for item in container["environment"]}
    assert env_map["AWS_REGION"] == "us-east-1"
    assert env_map["AWS_DEFAULT_REGION"] == "us-east-1"
    assert env_map["S3_DATA_BUCKET"] == "codingrabbit-data-dev"
    assert env_map["EVALUATION_DEFAULT_JUDGE_PROVIDER"] == "bedrock"
    assert env_map["EVALUATION_DEFAULT_JUDGE_MODEL"] == "anthropic.claude-haiku-4-5"
    assert env_map["EVALUATION_HOMEWORK_N"] == "7"
    assert env_map["EVALUATION_STUDY_N"] == "9"

    secrets = {item["name"]: item["valueFrom"] for item in container["secrets"]}
    assert secrets["COURSE_REGISTRY_DATABASE_URL"].endswith(":secret:db")
    assert secrets["OPENAI_API_KEY"].endswith(":secret:openai")


def test_backend_env_fragment_matches_launch_settings() -> None:
    config = load_evaluation_worker_config(_env())
    fragment = build_backend_env_fragment(config)

    assert "EVALUATION_WORKER_ECS_CLUSTER=codingrabbit-rag-eng" in fragment
    assert "EVALUATION_WORKER_ECS_TASK_DEFINITION=codingrabbit-evaluation-worker" in fragment
    assert "EVALUATION_WORKER_ECS_CONTAINER_NAME=evaluation-worker" in fragment
    assert "EVALUATION_WORKER_ECS_SUBNETS=subnet-a,subnet-b" in fragment
    assert "EVALUATION_WORKER_ECS_SECURITY_GROUPS=sg-a" in fragment


def test_describe_config_reports_no_missing_values() -> None:
    config = load_evaluation_worker_config(_env())
    lines = describe_config(config)

    assert missing_registration_values(config) == []
    assert missing_backend_launch_values(config) == []
    assert any("Task definition values missing: (none)" in line for line in lines)
    assert any("Backend launch values missing: (none)" in line for line in lines)
    assert any(
        "Secret ARN mappings: COURSE_REGISTRY_DATABASE_URL, OPENAI_API_KEY" in line
        for line in lines
    )


class _FakeEcsClient:
    def __init__(self) -> None:
        self.kwargs = None

    def register_task_definition(self, **kwargs):
        self.kwargs = kwargs
        return {
            "taskDefinition": {
                "taskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/codingrabbit-evaluation-worker:3",
                "family": kwargs["family"],
                "revision": 3,
            }
        }


def test_register_task_definition_uses_rendered_payload() -> None:
    config = load_evaluation_worker_config(_env())
    client = _FakeEcsClient()

    response = register_task_definition(config, client=client)

    assert client.kwargs is not None
    assert client.kwargs["family"] == "codingrabbit-evaluation-worker"
    assert client.kwargs["executionRoleArn"].endswith("ecsTaskExecutionRole")
    assert response["taskDefinitionArn"].endswith(":3")
    assert response["family"] == "codingrabbit-evaluation-worker"
    assert response["revision"] == 3


def test_deploy_script_loads_the_rendered_deploy_config() -> None:
    script = Path("deploy/scripts/deploy-evaluation-worker.sh").read_text(
        encoding="utf-8"
    )

    assert "load_deploy_config \"${REPO_ROOT}\" \"${PYTHON}\"" in script
    assert 'echo "    Config:   ${DEPLOY_CONFIG_PATH}"' in script
