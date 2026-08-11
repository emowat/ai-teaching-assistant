from __future__ import annotations

from pathlib import Path

import pytest

import deploy.deploy_evaluation_worker as deploy_evaluation_worker
from deploy.deploy_evaluation_worker import (
    AURORA_SELF_HEAL_ENV_KEYS,
    build_backend_env_fragment,
    build_task_definition,
    describe_config,
    main,
    missing_backend_launch_values,
    missing_registration_values,
    register_task_definition,
)
from deploy.deployment_config import load_deploy_config


# deployment_config.load_deploy_config() intentionally prioritizes real env
# vars over deployment.yaml (see ENV_OVERRIDES) - the repo's real .env sets
# AWS_PROFILE=default, AWS_REGION=us-east-1, which would otherwise silently
# leak into "pure YAML" assertions below. Clear them for every test; tests
# that want to exercise override behavior set what they need explicitly.
_ENV_OVERRIDE_KEYS_TO_ISOLATE = (
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "EVALUATION_WORKER_ECS_CLUSTER",
    "EVALUATION_WORKER_ECS_TASK_FAMILY",
    "EVALUATION_WORKER_ECS_TASK_DEFINITION",
    "EVALUATION_WORKER_ECS_CONTAINER_NAME",
    "EVALUATION_WORKER_ECS_LAUNCH_TYPE",
    "EVALUATION_WORKER_ECS_PLATFORM_VERSION",
    "EVALUATION_WORKER_ECS_ASSIGN_PUBLIC_IP",
    "EVALUATION_WORKER_ECS_SUBNETS",
    "EVALUATION_WORKER_ECS_SECURITY_GROUPS",
    "EVALUATION_WORKER_ECS_IMAGE_URI",
    "EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN",
    "EVALUATION_WORKER_ECS_TASK_ROLE_ARN",
    "EVALUATION_WORKER_ECS_CPU",
    "EVALUATION_WORKER_ECS_MEMORY",
    "EVALUATION_WORKER_ECS_LOG_GROUP",
    "EVALUATION_WORKER_ECS_LOG_STREAM_PREFIX",
    "EVALUATION_WORKER_ECS_ENV_JSON",
    "EVALUATION_WORKER_ECS_SECRET_ARNS_JSON",
)


@pytest.fixture(autouse=True)
def _isolate_from_real_env(monkeypatch):
    for key in _ENV_OVERRIDE_KEYS_TO_ISOLATE:
        monkeypatch.delenv(key, raising=False)


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "deployment.yaml"
    path.write_text(
        """
aws:
  region: us-east-1
  profile: codingrabbit-dev
  s3_bucket: codingrabbit-data-dev
evaluation_worker:
  cluster: codingrabbit-rag-eng
  task_family: codingrabbit-evaluation-worker
  task_definition: codingrabbit-evaluation-worker
  container_name: evaluation-worker
  launch_type: FARGATE
  platform_version: LATEST
  assign_public_ip: ENABLED
  subnet_ids:
    - subnet-a
    - subnet-b
  security_group_ids:
    - sg-a
  image_uri: 123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-evaluation-worker:latest
  execution_role_arn: arn:aws:iam::123456789012:role/ecsTaskExecutionRole
  task_role_arn: arn:aws:iam::123456789012:role/codingrabbit-rag-eng-task
  cpu: 1024
  memory: 2048
  log_group: /ecs/codingrabbit-evaluation-worker
  log_stream_prefix: ecs
  environment:
    S3_DATA_BUCKET: codingrabbit-data-dev
    OPENAI_BASE_URL: https://api.openai.com/v1
    EVALUATION_DEFAULT_JUDGE_PROVIDER: bedrock
    EVALUATION_DEFAULT_JUDGE_MODEL: anthropic.claude-haiku-4-5
    EVALUATION_HOMEWORK_N: "7"
    EVALUATION_STUDY_N: "9"
    EVALUATION_JUDGE_TEMPERATURE: "0.1"
    EVALUATION_JUDGE_TOP_P: "0.2"
    EVALUATION_JUDGE_TIMEOUT_SECONDS: "11"
    EVALUATION_JUDGE_MAX_CONCURRENCY: "5"
    EVALUATION_JUDGE_MAX_TOKENS: "256"
    EVALUATION_EXPORT_TZ: America/Los_Angeles
    EVALUATION_WRITE_AURORA: "true"
    LOG_LEVEL: INFO
  secret_arn_map:
    COURSE_REGISTRY_DATABASE_URL: arn:aws:secretsmanager:us-east-1:123456789012:secret:db
    OPENAI_API_KEY: arn:aws:secretsmanager:us-east-1:123456789012:secret:openai
""",
        encoding="utf-8",
    )
    return path


def test_load_evaluation_worker_config_reads_values(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    ew = config.evaluation_worker

    assert config.aws.region == "us-east-1"
    assert config.aws.profile == "codingrabbit-dev"
    assert ew.cluster == "codingrabbit-rag-eng"
    assert ew.task_definition == "codingrabbit-evaluation-worker"
    assert ew.image_uri.endswith("/codingrabbit-evaluation-worker:latest")
    assert ew.execution_role_arn.endswith("ecsTaskExecutionRole")
    assert ew.task_role_arn.endswith("codingrabbit-rag-eng-task")
    assert ew.subnet_ids == ("subnet-a", "subnet-b")
    assert ew.security_group_ids == ("sg-a",)
    assert ew.secret_arn_map["COURSE_REGISTRY_DATABASE_URL"].endswith(":secret:db")
    assert ew.secret_arn_map["OPENAI_API_KEY"].endswith(":secret:openai")


def test_load_evaluation_worker_config_reads_env_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("EVALUATION_WORKER_ECS_CLUSTER", "override-cluster")

    config = load_deploy_config(_write_config(tmp_path))

    assert config.evaluation_worker.cluster == "override-cluster"


def test_build_task_definition_includes_worker_env_and_secrets(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
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
    assert container["image"].endswith("/codingrabbit-evaluation-worker:latest")
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


def test_build_task_definition_preserves_aurora_self_heal_env_vars(
    tmp_path, monkeypatch
) -> None:
    """deployment.yaml's evaluation_worker.environment does NOT (and should
    not) carry these - they're read directly from the process environment
    (.env), same as before this script depended on deployment.yaml at all.
    Regression guard: silently dropping these would break Aurora
    password-rotation self-heal in the deployed worker."""
    assert "COURSE_REGISTRY_DATABASE_URL_SECRET_ID" not in Path(
        _write_config(tmp_path)
    ).read_text()

    for key in AURORA_SELF_HEAL_ENV_KEYS:
        monkeypatch.setenv(key, f"test-value-{key}")

    config = load_deploy_config(_write_config(tmp_path))
    payload = build_task_definition(config)
    env_map = {
        item["name"]: item["value"]
        for item in payload["containerDefinitions"][0]["environment"]
    }

    for key in AURORA_SELF_HEAL_ENV_KEYS:
        assert env_map[key] == f"test-value-{key}"


def test_backend_env_fragment_matches_launch_settings(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    fragment = build_backend_env_fragment(config)

    assert "EVALUATION_WORKER_ECS_CLUSTER=codingrabbit-rag-eng" in fragment
    assert "EVALUATION_WORKER_ECS_TASK_DEFINITION=codingrabbit-evaluation-worker" in fragment
    assert "EVALUATION_WORKER_ECS_CONTAINER_NAME=evaluation-worker" in fragment
    assert "EVALUATION_WORKER_ECS_SUBNETS=subnet-a,subnet-b" in fragment
    assert "EVALUATION_WORKER_ECS_SECURITY_GROUPS=sg-a" in fragment


def test_describe_config_reports_no_missing_values(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
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


def test_register_task_definition_uses_rendered_payload(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    client = _FakeEcsClient()

    response = register_task_definition(config, client=client)

    assert client.kwargs is not None
    assert client.kwargs["family"] == "codingrabbit-evaluation-worker"
    assert client.kwargs["executionRoleArn"].endswith("ecsTaskExecutionRole")
    assert response["taskDefinitionArn"].endswith(":3")
    assert response["family"] == "codingrabbit-evaluation-worker"
    assert response["revision"] == 3


# --- deploy_worker: build+push+register composition ---
# Never touches real docker/boto3 - both build_and_push_image and
# register_task_definition are stubbed at the module level.


def test_deploy_worker_builds_pushes_and_registers_with_fresh_image_uri(
    tmp_path, monkeypatch
) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    build_calls: list[dict[str, object]] = []
    register_calls: list = []

    def fake_build_and_push_image(*, config, docker_binary="docker"):
        build_calls.append(
            {
                "repository_name": config.repository_name,
                "image_tag": config.image_tag,
                "docker_binary": docker_binary,
            }
        )
        return "123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-evaluation-worker:latest-fresh"

    def fake_register_task_definition(registration_config):
        register_calls.append(registration_config)
        return {
            "taskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/codingrabbit-evaluation-worker:4",
            "family": registration_config.evaluation_worker.task_family,
            "revision": 4,
        }

    monkeypatch.setattr(
        deploy_evaluation_worker, "build_and_push_image", fake_build_and_push_image
    )
    monkeypatch.setattr(
        deploy_evaluation_worker,
        "register_task_definition",
        fake_register_task_definition,
    )

    result = deploy_evaluation_worker.deploy_worker(config)

    assert build_calls == [
        {
            "repository_name": "codingrabbit-evaluation-worker",
            "image_tag": "latest",
            "docker_binary": "docker",
        }
    ]
    # register_task_definition must be called with the FRESHLY pushed image
    # URI, not whatever was in the deployment.yaml-configured config.
    assert register_calls[0].evaluation_worker.image_uri.endswith(":latest-fresh")
    assert result["imageUri"].endswith(":latest-fresh")
    assert result["revision"] == 4


def test_deploy_action_does_not_require_image_uri_up_front(tmp_path, monkeypatch) -> None:
    """The image URI is produced by the build step, so `deploy` must not
    fail the pre-flight missing-value check just because it isn't set yet -
    unlike register-task-definition, which does require it."""
    config_path = tmp_path / "deployment.yaml"
    config_path.write_text(
        """
aws:
  region: us-east-1
evaluation_worker:
  cluster: codingrabbit-rag-eng
  subnet_ids:
    - subnet-a
  security_group_ids:
    - sg-a
  execution_role_arn: arn:aws:iam::123456789012:role/ecsTaskExecutionRole
  task_role_arn: arn:aws:iam::123456789012:role/codingrabbit-rag-eng-task
""",
        encoding="utf-8",
    )

    calls: list = []

    def fake_deploy_worker(config):
        calls.append(config)
        return {"taskDefinitionArn": "arn:...:5", "family": "x", "revision": 5, "imageUri": "fresh"}

    monkeypatch.setattr(deploy_evaluation_worker, "deploy_worker", fake_deploy_worker)

    exit_code = main(["deploy", "--config", str(config_path)])

    assert exit_code == 0
    assert len(calls) == 1
