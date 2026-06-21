from __future__ import annotations

import json
from pathlib import Path

from deploy.deploy_ingestion_worker import (
    build_backend_env_fragment,
    build_task_definition,
    describe_config,
    load_ingestion_worker_config,
    missing_backend_launch_values,
    missing_registration_values,
    register_task_definition,
)


def _env() -> dict[str, str]:
    return {
        "AWS_REGION": "us-east-1",
        "AWS_PROFILE": "codingrabbit-dev",
        "INGESTION_ECS_CLUSTER": "codingrabbit-ingestion",
        "INGESTION_ECS_TASK_FAMILY": "codingrabbit-ingestion-worker",
        "INGESTION_ECS_TASK_DEFINITION": "codingrabbit-ingestion-worker",
        "INGESTION_ECS_CONTAINER_NAME": "ingestion-worker",
        "INGESTION_ECS_LAUNCH_TYPE": "FARGATE",
        "INGESTION_ECS_PLATFORM_VERSION": "LATEST",
        "INGESTION_ECS_ASSIGN_PUBLIC_IP": "ENABLED",
        "INGESTION_ECS_SUBNETS": "subnet-a, subnet-b",
        "INGESTION_ECS_SECURITY_GROUPS": "sg-a",
        "INGESTION_ECS_IMAGE_URI": "123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-ingestion:latest",
        "INGESTION_ECS_EXECUTION_ROLE_ARN": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
        "INGESTION_ECS_TASK_ROLE_ARN": "arn:aws:iam::123456789012:role/codingrabbit-ingestion-task",
        "INGESTION_ECS_SECRET_ARNS_JSON": json.dumps(
            {
                "INGESTION_JOBS_DATABASE_URL": "arn:aws:secretsmanager:us-east-1:123456789012:secret:db",
                "QDRANT_API_KEY": "arn:aws:secretsmanager:us-east-1:123456789012:secret:qdrant",
            }
        ),
        "QDRANT_URL": "https://qdrant.example",
        "EMBEDDING_MODEL": "sentence-transformers/multi-qa-mpnet-base-dot-v1",
        "QDRANT_COLLECTION_MIT13": "course_knowledge",
        "QDRANT_COLLECTION_MIT14": "course_knowledge",
        "QDRANT_COLLECTION_CS50": "harvard_cs50",
        "QDRANT_COLLECTION_GUIDELINES": "cpp_guidelines",
        "INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS": "7",
    }


def test_load_ingestion_worker_config_reads_env_and_secret_mappings() -> None:
    config = load_ingestion_worker_config(_env())

    assert config.aws_region == "us-east-1"
    assert config.aws_profile == "codingrabbit-dev"
    assert config.ecs_cluster == "codingrabbit-ingestion"
    assert config.ecs_task_definition == "codingrabbit-ingestion-worker"
    assert config.ecs_image_uri.endswith("/codingrabbit-ingestion:latest")
    assert config.ecs_execution_role_arn.endswith("ecsTaskExecutionRole")
    assert config.ecs_task_role_arn.endswith("codingrabbit-ingestion-task")
    assert config.ecs_subnet_ids == ("subnet-a", "subnet-b")
    assert config.ecs_security_group_ids == ("sg-a",)
    assert config.secret_arn_map["INGESTION_JOBS_DATABASE_URL"].endswith(":secret:db")
    assert config.secret_arn_map["QDRANT_API_KEY"].endswith(":secret:qdrant")


def test_build_task_definition_includes_worker_env_and_secrets() -> None:
    config = load_ingestion_worker_config(_env())
    payload = build_task_definition(config)

    assert payload["family"] == "codingrabbit-ingestion-worker"
    assert payload["networkMode"] == "awsvpc"
    assert payload["requiresCompatibilities"] == ["FARGATE"]
    assert payload["cpu"] == "1024"
    assert payload["memory"] == "2048"
    assert payload["executionRoleArn"].endswith("ecsTaskExecutionRole")
    assert payload["taskRoleArn"].endswith("codingrabbit-ingestion-task")

    container = payload["containerDefinitions"][0]
    assert container["name"] == "ingestion-worker"
    assert container["image"].endswith("/codingrabbit-ingestion:latest")
    assert container["logConfiguration"]["options"]["awslogs-group"] == (
        "/ecs/codingrabbit-ingestion-worker"
    )
    env_map = {item["name"]: item["value"] for item in container["environment"]}
    assert env_map["AWS_REGION"] == "us-east-1"
    assert env_map["AWS_DEFAULT_REGION"] == "us-east-1"
    assert env_map["QDRANT_URL"] == "https://qdrant.example"
    assert env_map["EMBEDDING_MODEL"] == "sentence-transformers/multi-qa-mpnet-base-dot-v1"
    assert env_map["QDRANT_COLLECTION_MIT14"] == "course_knowledge"
    assert env_map["INGESTION_JOBS_CONNECT_TIMEOUT_SECONDS"] == "7"

    secrets = {item["name"]: item["valueFrom"] for item in container["secrets"]}
    assert secrets["INGESTION_JOBS_DATABASE_URL"].endswith(":secret:db")
    assert secrets["QDRANT_API_KEY"].endswith(":secret:qdrant")


def test_backend_env_fragment_matches_launch_settings() -> None:
    config = load_ingestion_worker_config(_env())
    fragment = build_backend_env_fragment(config)

    assert "INGESTION_ECS_CLUSTER=codingrabbit-ingestion" in fragment
    assert "INGESTION_ECS_TASK_DEFINITION=codingrabbit-ingestion-worker" in fragment
    assert "INGESTION_ECS_CONTAINER_NAME=ingestion-worker" in fragment
    assert "INGESTION_ECS_SUBNETS=subnet-a,subnet-b" in fragment
    assert "INGESTION_ECS_SECURITY_GROUPS=sg-a" in fragment


def test_describe_config_reports_no_missing_values() -> None:
    config = load_ingestion_worker_config(_env())
    lines = describe_config(config)

    assert missing_registration_values(config) == []
    assert missing_backend_launch_values(config) == []
    assert any("Task definition values missing: (none)" in line for line in lines)
    assert any("Backend launch values missing: (none)" in line for line in lines)
    assert any("Secret ARN mappings: INGESTION_JOBS_DATABASE_URL, QDRANT_API_KEY" in line for line in lines)


class _FakeEcsClient:
    def __init__(self) -> None:
        self.kwargs = None

    def register_task_definition(self, **kwargs):
        self.kwargs = kwargs
        return {
            "taskDefinition": {
                "taskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/codingrabbit-ingestion-worker:3",
                "family": kwargs["family"],
                "revision": 3,
            }
        }


def test_register_task_definition_uses_rendered_payload() -> None:
    config = load_ingestion_worker_config(_env())
    client = _FakeEcsClient()

    response = register_task_definition(config, client=client)

    assert client.kwargs is not None
    assert client.kwargs["family"] == "codingrabbit-ingestion-worker"
    assert client.kwargs["executionRoleArn"].endswith("ecsTaskExecutionRole")
    assert response["taskDefinitionArn"].endswith(":3")
    assert response["family"] == "codingrabbit-ingestion-worker"
    assert response["revision"] == 3


def test_worker_requirements_include_parser_dependencies() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")

    assert "pymupdf" in requirements
    assert "python-docx" in requirements
    assert "python-pptx" in requirements
    assert "beautifulsoup4" in requirements


def test_deploy_script_loads_the_rendered_deploy_config() -> None:
    script = Path("deploy/scripts/deploy-ingestion-worker.sh").read_text(encoding="utf-8")

    assert "load_deploy_config \"${REPO_ROOT}\" \"${PYTHON}\"" in script
    assert 'echo "    Config:   ${DEPLOY_CONFIG_PATH}"' in script
