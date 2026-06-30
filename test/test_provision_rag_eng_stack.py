from __future__ import annotations

import json

from deploy import provision_rag_eng_stack as provision


class _FakeIamExceptions:
    class NoSuchEntityException(Exception):
        pass


class _FakeIamClient:
    def __init__(self, *, role_exists: bool = False) -> None:
        self.exceptions = _FakeIamExceptions()
        self._role_exists = role_exists
        self.created_roles: list[dict[str, object]] = []
        self.attached_policies: list[dict[str, str]] = []
        self.put_policies: list[dict[str, str]] = []

    def get_role(self, *, RoleName: str):
        if not self._role_exists:
            raise self.exceptions.NoSuchEntityException(RoleName)
        return {"Role": {"Arn": f"arn:aws:iam::123456789012:role/{RoleName}"}}

    def create_role(self, **kwargs):
        self._role_exists = True
        self.created_roles.append(kwargs)
        return {"Role": {"Arn": f"arn:aws:iam::123456789012:role/{kwargs['RoleName']}"}}

    def attach_role_policy(self, **kwargs):
        self.attached_policies.append(kwargs)

    def put_role_policy(self, **kwargs):
        self.put_policies.append(kwargs)


class _FakeElbv2Client:
    def __init__(self, *, existing_target_group_arn: str) -> None:
        self.existing_target_group_arn = existing_target_group_arn
        self.modified_listeners: list[dict[str, object]] = []
        self.created_listeners: list[dict[str, object]] = []

    def describe_listeners(self, **kwargs):
        return {
            "Listeners": [
                {
                    "ListenerArn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/rag-eng/1",
                    "Port": 80,
                    "DefaultActions": [
                        {
                            "Type": "forward",
                            "TargetGroupArn": self.existing_target_group_arn,
                        }
                    ],
                }
            ]
        }

    def modify_listener(self, **kwargs):
        self.modified_listeners.append(kwargs)
        return {
            "Listeners": [
                {
                    "ListenerArn": kwargs["ListenerArn"],
                }
            ]
        }

    def create_listener(self, **kwargs):
        self.created_listeners.append(kwargs)
        return {
            "Listeners": [
                {
                    "ListenerArn": "arn:aws:elasticloadbalancing:us-east-1:123456789012:listener/app/rag-eng/2",
                }
            ]
        }


def test_ensure_task_role_writes_runtime_permissions() -> None:
    client = _FakeIamClient()

    role_arn = provision._ensure_task_role(
        client,
        account_id="123456789012",
        region="us-east-1",
        bucket_name="codingrabbit-data-dev",
        sagemaker_endpoint="codingrabbit-qwen-async",
    )

    assert role_arn.endswith(":role/codingrabbit-rag-eng-task")
    assert client.created_roles, "expected the task role to be created"
    assert client.put_policies

    policy = json.loads(client.put_policies[0]["PolicyDocument"])
    statements = {statement["Sid"]: statement for statement in policy["Statement"]}
    assert statements["S3AsyncIo"]["Resource"] == [
        "arn:aws:s3:::codingrabbit-data-dev",
        "arn:aws:s3:::codingrabbit-data-dev/*",
    ]
    assert set(statements["InvokeSageMakerAsync"]["Action"]) == {
        "sagemaker:InvokeEndpointAsync",
        "sagemaker:DescribeEndpoint",
    }
    assert statements["UseBedrockConverse"]["Action"] == [
        "bedrock:Converse",
        "bedrock:ConverseStream",
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
    ]
    assert statements["BedrockMarketplaceAccess"]["Action"] == [
        "aws-marketplace:Subscribe",
        "aws-marketplace:Unsubscribe",
        "aws-marketplace:ViewSubscriptions",
    ]


def test_ensure_execution_role_grants_secret_access() -> None:
    client = _FakeIamClient()

    role_arn = provision._ensure_execution_role(
        client,
        account_id="123456789012",
        region="us-east-1",
        secret_arns=[
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:openai",
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:qdrant",
        ],
    )

    assert role_arn.endswith(":role/codingrabbit-rag-eng-execution-role")
    assert client.created_roles, "expected the execution role to be created"
    assert client.attached_policies
    assert client.put_policies

    policy = json.loads(client.put_policies[0]["PolicyDocument"])
    statement = policy["Statement"][0]
    assert statement["Sid"] == "ReadRagEngSecrets"
    assert statement["Action"] == ["secretsmanager:GetSecretValue"]
    assert statement["Resource"] == [
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:openai",
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:qdrant",
    ]


def test_ensure_listener_updates_when_target_group_changes() -> None:
    client = _FakeElbv2Client(
        existing_target_group_arn="arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/old/1111",
    )

    listener_arn = provision._ensure_listener(
        client,
        load_balancer_arn="arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/rag-eng/1",
        target_group_arn="arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/new/2222",
        port=80,
    )

    assert listener_arn.endswith(":listener/app/rag-eng/1")
    assert len(client.modified_listeners) == 1
    assert not client.created_listeners
    assert client.modified_listeners[0]["DefaultActions"][0]["TargetGroupArn"] == (
        "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/new/2222"
    )


def test_run_preflight_checks_runs_local_gate(monkeypatch) -> None:
    commands: list[list[str]] = []

    monkeypatch.setattr(
        provision.shutil, "which", lambda name: "/usr/bin/uv" if name == "uv" else None
    )

    def fake_run(command, *, cwd, check, **kwargs):
        commands.append(list(command))
        assert cwd == provision.REPO_ROOT
        assert check is True
        return None

    monkeypatch.setattr(provision.subprocess, "run", fake_run)

    provision.run_preflight_checks()

    assert commands[0] == ["git", "diff", "--check"]
    assert commands[1][:3] == ["uv", "run", "ruff"]
    assert commands[1][3:] == [
        "check",
        "deploy/provision_rag_eng_stack.py",
        "deploy/deploy_rag_eng_ecs.py",
        "deploy/deployment_config.py",
        "rag_eng",
    ]
    assert commands[2][:3] == ["uv", "run", "pytest"]
    assert "test/test_rag_eng_api.py" in commands[2]
    assert "test/test_pipeline.py" not in commands[2]
    assert "test/test_offline_eval_live_smoke.py" not in commands[2]
    assert "test/test_aurora_wakeup_benchmark.py" not in commands[2]


def test_run_preflight_checks_can_be_skipped(monkeypatch) -> None:
    called = []

    monkeypatch.setenv("RAG_ENG_SKIP_PREFLIGHT", "1")
    monkeypatch.setattr(
        provision.subprocess,
        "run",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    provision.run_preflight_checks()

    assert called == []


def test_build_arg_parser_accepts_skip_preflight_flag() -> None:
    args = provision.build_arg_parser().parse_args(["apply", "--skip-preflight"])

    assert args.action == "apply"
    assert args.skip_preflight is True
