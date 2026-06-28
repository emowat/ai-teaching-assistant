from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from deploy.deploy_rag_eng_ecs import (
    build_service_spec,
    build_task_definition,
    describe_config,
    missing_registration_values,
    missing_service_values,
    _render_json,
    _service_status,
)
from deploy.deploy_rag_eng_ecs import _register_task_definition
from deploy.deploy_rag_eng_ecs import _upsert_service
from deploy.deployment_config import load_deploy_config, shell_export


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "deployment.yaml"
    path.write_text(
        """
aws:
  region: us-east-1
  profile: codingrabbit-dev
  s3_bucket: codingrabbit-data-dev
rag_eng:
  model_family: qwen
  use_sagemaker: true
  inference_backend: vllm
rag_eng_ecs:
  cluster: codingrabbit-rag-eng
  service_name: codingrabbit-rag-eng
  task_family: codingrabbit-rag-eng
  task_definition: codingrabbit-rag-eng
  container_name: rag-eng
  launch_type: FARGATE
  platform_version: LATEST
  assign_public_ip: ENABLED
  subnet_ids:
    - subnet-a
    - subnet-b
  security_group_ids:
    - sg-a
  alb_security_group_id: sg-alb
  target_group_arn: arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/rag-eng/1234567890123456
  image_uri: 123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-rag-eng:latest
  execution_role_arn: arn:aws:iam::123456789012:role/ecsTaskExecutionRole
  task_role_arn: arn:aws:iam::123456789012:role/codingrabbit-rag-eng-task
  cpu: 1024
  memory: 2048
  container_port: 8001
  desired_count: 1
  health_check_path: /health
  health_check_grace_period_seconds: 600
  log_group: /ecs/codingrabbit-rag-eng
  log_stream_prefix: ecs
  environment:
    APP_PORT: "8001"
    AWS_REGION: us-east-1
    CORS_ORIGINS: http://localhost:5173
    COGNITO_REGION: us-east-1
    COGNITO_USER_POOL_ID: us-east-1_Z5DAb8wni
    COGNITO_APP_CLIENT_ID: 5k11ek5do9l3p6vhpev3aifh0f
    COGNITO_ISSUER: https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Z5DAb8wni
    COGNITO_JWKS_URL: https://cognito-idp.us-east-1.amazonaws.com/us-east-1_Z5DAb8wni/.well-known/jwks.json
    LOG_LEVEL: INFO
    GRADIO_ROOT_PATH: /gradio
    GRADIO_PUBLIC_ORIGIN: "https://d26myplnp1msqn.cloudfront.net"
    OPENAI_BASE_URL: https://api.openai.com/v1
    QDRANT_URL: https://qdrant.example
    QDRANT_COLLECTION_NAME: codingrabbit_rag_vectordb
    QDRANT_GUIDELINES_COLLECTION_NAME: cpp_guidelines
    QDRANT_HARVARD_COLLECTION_NAME: harvard_cs50
    QDRANT_COLLECTION_MIT13: mit13_course
    QDRANT_COLLECTION_MIT14: mit14_course
    QDRANT_COLLECTION_CS50: harvard_cs50
    QDRANT_COLLECTION_GUIDELINES: cpp_guidelines
    EMBEDDING_MODEL: sentence-transformers/multi-qa-mpnet-base-dot-v1
    INPUT_GUARDRAILS_ENABLED: "true"
    INPUT_GUARDRAILS_CODEBERT_S3_URI: s3://codingrabbit-data-dev/models/guardrails/input_codebert_v1/model.tar.gz
    INPUT_GUARDRAILS_CODEBERT_CHECKPOINT_DIR: input_guardrails/models/checkpoints/input_codebert_v1
    INPUT_GUARDRAILS_CODEBERT_PASS_BELOW: "0.30"
    INPUT_GUARDRAILS_CODEBERT_BLOCK_ABOVE: "0.70"
    GUARDRAILS_CODEBERT_S3_URI: s3://codingrabbit-data-dev/models/guardrails/codebert_v2_1/model.tar.gz
    GUARDRAILS_CODEBERT_CHECKPOINT_DIR: output_guardrails/models/checkpoints/codebert_v2_1
    USE_SAGEMAKER: "true"
    SAGEMAKER_ENDPOINT: codingrabbit-qwen-async
    SAGEMAKER_INFERENCE_BACKEND: vllm
    SAGEMAKER_POLL_TIMEOUT_SECONDS: "900"
    S3_DATA_BUCKET: codingrabbit-data-dev
    MODEL_FAMILY: qwen
  secret_arn_map:
    COHERE_API_KEY: arn:aws:secretsmanager:us-east-1:123456789012:secret:cohere
    OPENAI_API_KEY: arn:aws:secretsmanager:us-east-1:123456789012:secret:openai
    QDRANT_API_KEY: arn:aws:secretsmanager:us-east-1:123456789012:secret:qdrant
    COURSE_REGISTRY_DATABASE_URL: arn:aws:secretsmanager:us-east-1:123456789012:secret:course-registry
frontend_web:
  enabled: true
  app_dir: ./frontend
  dist_dir: ./frontend/dist
  bucket_name: codingrabbit-frontend-dev
  bucket_prefix: web
  default_root_object: index.html
  spa_fallback_path: /index.html
  price_class: PriceClass_100
  cloudfront:
      distribution_id: E1234567890
      aliases:
        - app.example.com
      certificate_arn: arn:aws:acm:us-east-1:123456789012:certificate/example
      comment: CodingRabbit frontend
      create_oac: true
      invalidation_paths:
        - /*
      api_path_patterns:
        - /api/*
        - /health
      origin_protocol_policy: http-only
      cache_static_assets: true
      cache_html_seconds: 60
  build:
    vite_api_base_url: https://api.example.com
    vite_cognito_domain: https://example.auth.us-east-1.amazoncognito.com
    vite_cognito_redirect_uri: https://app.example.com/auth/callback
    vite_cognito_logout_uri: https://app.example.com/logout
    extra_env:
      VITE_APP_VARIANT: production
""",
        encoding="utf-8",
    )
    return path


def test_load_rag_eng_ecs_config_reads_env_overrides(tmp_path, monkeypatch) -> None:
    path = _write_config(tmp_path)
    monkeypatch.setenv("RAG_ENG_ECS_CLUSTER", "override-cluster")

    config = load_deploy_config(path)

    assert config.rag_eng_ecs.cluster == "override-cluster"
    assert config.rag_eng_ecs.service_name == "codingrabbit-rag-eng"
    assert config.rag_eng_ecs.container_port == 8001
    assert config.rag_eng_ecs.alb_security_group_id == "sg-alb"
    assert config.rag_eng_ecs.secret_arn_map["OPENAI_API_KEY"].endswith(
        ":secret:openai"
    )


def test_load_frontend_web_config_reads_values_and_shell_exports(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("VITE_API_BASE_URL", raising=False)
    monkeypatch.delenv("VITE_COGNITO_DOMAIN", raising=False)
    monkeypatch.delenv("VITE_COGNITO_REDIRECT_URI", raising=False)
    monkeypatch.delenv("VITE_COGNITO_LOGOUT_URI", raising=False)

    config = load_deploy_config(_write_config(tmp_path))

    assert config.frontend_web.enabled is True
    assert config.frontend_web.bucket_name == "codingrabbit-frontend-dev"
    assert config.frontend_web.bucket_prefix == "web"
    assert config.frontend_web.cloudfront.distribution_id == "E1234567890"
    assert config.frontend_web.cloudfront.aliases == ("app.example.com",)
    assert config.frontend_web.cloudfront.create_oac is True
    assert config.frontend_web.cloudfront.cache_static_assets is True
    assert config.frontend_web.cloudfront.cache_html_seconds == 60
    assert config.frontend_web.cloudfront.origin_protocol_policy == "http-only"
    assert config.frontend_web.build.vite_api_base_url == "https://api.example.com"
    assert config.frontend_web.build.extra_env["VITE_APP_VARIANT"] == "production"

    exports = shell_export(config)
    assert 'export DEPLOY_FRONTEND_BUCKET_NAME="codingrabbit-frontend-dev"' in exports
    assert 'export DEPLOY_FRONTEND_CLOUDFRONT_DISTRIBUTION_ID="E1234567890"' in exports
    assert 'export DEPLOY_FRONTEND_CLOUDFRONT_ALIASES="app.example.com"' in exports
    assert (
        'export DEPLOY_FRONTEND_CLOUDFRONT_ORIGIN_PROTOCOL_POLICY="http-only"'
        in exports
    )
    assert (
        'export DEPLOY_FRONTEND_VITE_API_BASE_URL="https://api.example.com"' in exports
    )
    assert "DEPLOY_FRONTEND_EXTRA_ENV_JSON=" in exports
    assert "VITE_APP_VARIANT" in exports


def test_build_task_definition_includes_runtime_env_and_secrets(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    payload = build_task_definition(config)

    assert payload["family"] == "codingrabbit-rag-eng"
    assert payload["requiresCompatibilities"] == ["FARGATE"]
    assert payload["cpu"] == "1024"
    assert payload["memory"] == "2048"

    container = payload["containerDefinitions"][0]
    assert container["name"] == "rag-eng"
    assert container["image"].endswith("/codingrabbit-rag-eng:latest")
    assert container["command"] == [
        "/bin/sh",
        "/app/deploy/scripts/rag-eng-startup.sh",
    ]
    assert container["portMappings"] == [{"containerPort": 8001, "protocol": "tcp"}]

    env_map = {item["name"]: item["value"] for item in container["environment"]}
    assert env_map["APP_PORT"] == "8001"
    assert env_map["AWS_REGION"] == "us-east-1"
    assert env_map["QDRANT_URL"] == "https://qdrant.example"
    assert env_map["SAGEMAKER_ENDPOINT"] == "codingrabbit-qwen-async"
    assert env_map["MODEL_FAMILY"] == "qwen"
    assert env_map["GRADIO_ROOT_PATH"] == "/gradio"
    assert env_map["GRADIO_PUBLIC_ORIGIN"] == "https://d26myplnp1msqn.cloudfront.net"
    assert (
        env_map["GUARDRAILS_CODEBERT_S3_URI"]
        == "s3://codingrabbit-data-dev/models/guardrails/codebert_v2_1/model.tar.gz"
    )

    secrets = {item["name"]: item["valueFrom"] for item in container["secrets"]}
    assert secrets["OPENAI_API_KEY"].endswith(":secret:openai")
    assert secrets["QDRANT_API_KEY"].endswith(":secret:qdrant")


def test_build_service_spec_includes_target_group_and_network_config(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    payload = build_service_spec(
        config, task_definition="arn:aws:ecs:task-definition/rag-eng:1"
    )

    assert payload["cluster"] == "codingrabbit-rag-eng"
    assert payload["serviceName"] == "codingrabbit-rag-eng"
    assert payload["taskDefinition"].endswith(":1")
    assert payload["desiredCount"] == 1
    assert payload["healthCheckGracePeriodSeconds"] == 600
    assert payload["networkConfiguration"]["awsvpcConfiguration"]["subnets"] == [
        "subnet-a",
        "subnet-b",
    ]
    assert payload["loadBalancers"][0]["containerPort"] == 8001
    assert payload["loadBalancers"][0]["targetGroupArn"].endswith("/1234567890123456")


def test_describe_config_reports_no_missing_values(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    lines = describe_config(config)

    assert missing_registration_values(config) == []
    assert missing_service_values(config) == []
    assert any("Task definition values missing: (none)" in line for line in lines)
    assert any("Service launch values missing: (none)" in line for line in lines)
    assert any("Runtime env values missing: (none)" in line for line in lines)
    assert any("Secret keys:" in line for line in lines)


class _FakeEcsClient:
    def __init__(self, *, has_service: bool = False, include_temporal_metadata: bool = False) -> None:
        self.has_service = has_service
        self.include_temporal_metadata = include_temporal_metadata
        self.register_kwargs = None
        self.create_kwargs = None
        self.update_kwargs = None

    def register_task_definition(self, **kwargs):
        self.register_kwargs = kwargs
        return {
            "taskDefinition": {
                "taskDefinitionArn": "arn:aws:ecs:us-east-1:123456789012:task-definition/rag-eng:3",
                "family": kwargs["family"],
                "revision": 3,
            }
        }

    def describe_services(self, **kwargs):
        if not self.has_service:
            return {"services": []}
        service = {
            "services": [
                {
                    "status": "ACTIVE",
                    "serviceArn": "arn:aws:ecs:us-east-1:123456789012:service/codingrabbit-rag-eng",
                    "runningCount": 1,
                    "desiredCount": 1,
                    "taskDefinition": kwargs["services"][0],
                }
            ]
        }
        if self.include_temporal_metadata:
            service["services"][0]["events"] = [
                {
                    "createdAt": datetime(2026, 6, 26, 12, 34, 56, tzinfo=timezone.utc),
                    "message": "service started",
                }
            ]
            service["services"][0]["deployments"] = [
                {
                    "createdAt": datetime(2026, 6, 26, 12, 35, 0, tzinfo=timezone.utc),
                    "updatedAt": datetime(2026, 6, 26, 12, 36, 0, tzinfo=timezone.utc),
                    "status": "PRIMARY",
                }
            ]
        return service

    def create_service(self, **kwargs):
        self.create_kwargs = kwargs
        return {
            "service": {
                "status": "ACTIVE",
                "serviceArn": "arn:aws:ecs:us-east-1:123456789012:service/codingrabbit-rag-eng",
                "runningCount": kwargs["desiredCount"],
                "desiredCount": kwargs["desiredCount"],
                "taskDefinition": kwargs["taskDefinition"],
            }
        }

    def update_service(self, **kwargs):
        self.update_kwargs = kwargs
        return {
            "service": {
                "status": "ACTIVE",
                "serviceArn": "arn:aws:ecs:us-east-1:123456789012:service/codingrabbit-rag-eng",
                "runningCount": kwargs["desiredCount"],
                "desiredCount": kwargs["desiredCount"],
                "taskDefinition": kwargs["taskDefinition"],
            }
        }


def test_register_task_definition_uses_rendered_payload(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    client = _FakeEcsClient()

    response = _register_task_definition(config, client=client)

    assert client.register_kwargs is not None
    assert client.register_kwargs["family"] == "codingrabbit-rag-eng"
    assert response["taskDefinitionArn"].endswith(":3")
    assert response["family"] == "codingrabbit-rag-eng"
    assert response["revision"] == 3


def test_upsert_service_creates_service_when_missing(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    client = _FakeEcsClient()

    response = _upsert_service(
        config,
        task_definition="arn:aws:ecs:us-east-1:123456789012:task-definition/rag-eng:3",
        client=client,
    )

    assert client.create_kwargs is not None
    assert client.update_kwargs is None
    assert response["action"] == "created"
    assert response["taskDefinition"].endswith(":3")


def test_upsert_service_updates_existing_service(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    client = _FakeEcsClient(has_service=True)

    response = _upsert_service(
        config,
        task_definition="arn:aws:ecs:us-east-1:123456789012:task-definition/rag-eng:4",
        client=client,
    )

    assert client.create_kwargs is None
    assert client.update_kwargs is not None
    assert "launchType" not in client.update_kwargs
    assert response["action"] == "updated"
    assert response["taskDefinition"].endswith(":4")


def test_service_status_rendering_handles_datetime_fields(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    client = _FakeEcsClient(has_service=True, include_temporal_metadata=True)

    status = _service_status(config, client=client)
    rendered = _render_json(status)

    assert "2026-06-26T12:34:56+00:00" in rendered
    assert "2026-06-26T12:35:00+00:00" in rendered
    assert "2026-06-26T12:36:00+00:00" in rendered


def test_deploy_script_loads_the_rendered_deploy_config() -> None:
    script = Path("deploy/scripts/deploy-rag-eng-ecs.sh").read_text(encoding="utf-8")

    assert 'load_deploy_config "${REPO_ROOT}" "${PYTHON}"' in script
    assert 'echo "    Cluster:  ${DEPLOY_RAG_ENG_ECS_CLUSTER}"' in script
    assert 'echo "    Service:  ${DEPLOY_RAG_ENG_ECS_SERVICE_NAME}"' in script
