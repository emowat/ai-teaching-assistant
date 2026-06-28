"""Provision the AWS stack for the `rag_eng` online orchestrator.

This helper creates the AWS resources required for the ECS/Fargate service:

- ECR repository for the service image
- ECS cluster
- task execution role and task role
- CloudWatch log group
- app-specific Secrets Manager entries
- ALB security group, application load balancer, target group, and listener

After the infrastructure exists, the script builds/pushes the local Docker image,
registers the ECS task definition, and creates or updates the ECS service.

The output is a JSON summary that can be copied back into
`deploy/deployment.yaml`.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv


load_dotenv()

DEPLOY_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEPLOY_DIR.parent
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

from deploy_rag_eng_ecs import _register_task_definition, _upsert_service  # noqa: E402
from deployment_config import DeployConfig, load_deploy_config  # noqa: E402


SECRET_ENV_KEYS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "COHERE_API_KEY",
    "QDRANT_API_KEY",
    "COURSE_REGISTRY_DATABASE_URL",
)

SECRET_NAMESPACE = "codingrabbit/rag_eng"
ECR_REPOSITORY_NAME = "codingrabbit-rag-eng"
ECS_CLUSTER_NAME = "codingrabbit-rag-eng"
EXECUTION_ROLE_NAME = "codingrabbit-rag-eng-execution-role"
TASK_ROLE_NAME = "codingrabbit-rag-eng-task"
ALB_SECURITY_GROUP_NAME = "codingrabbit-rag-eng-alb-sg"
LOAD_BALANCER_NAME = "codingrabbit-rag-eng"
TARGET_GROUP_NAME = "codingrabbit-rag-eng"
LOG_GROUP_NAME = "/ecs/codingrabbit-rag-eng"
DOCKER_IMAGE_TAG = "latest"
DEFAULT_LISTENER_PORT = 80


def _session(config: DeployConfig) -> boto3.Session:
    return boto3.Session(
        profile_name=config.aws.profile,
        region_name=config.aws.region,
    )


def _client(config: DeployConfig, service_name: str):
    return _session(config).client(service_name)


def _account_id(config: DeployConfig) -> str:
    sts = _client(config, "sts")
    return sts.get_caller_identity()["Account"]


def _secret_name(key: str) -> str:
    return f"{SECRET_NAMESPACE}/{key}"


def _require_env_value(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be set before provisioning rag_eng.")
    return value.strip()


def _ensure_secret(
    client,
    *,
    name: str,
    value: str,
    description: str,
) -> str:
    try:
        secret = client.describe_secret(SecretId=name)
        arn = secret["ARN"]
        client.put_secret_value(SecretId=name, SecretString=value)
        return arn
    except client.exceptions.ResourceNotFoundException:
        response = client.create_secret(
            Name=name,
            SecretString=value,
            Description=description,
        )
        return response["ARN"]


def _ensure_log_group(client, *, log_group_name: str) -> None:
    try:
        client.create_log_group(logGroupName=log_group_name)
    except ClientError as exc:
        if (
            exc.response.get("Error", {}).get("Code")
            != "ResourceAlreadyExistsException"
        ):
            raise


def _ensure_ecr_repository(client, *, repository_name: str) -> str:
    try:
        response = client.describe_repositories(repositoryNames=[repository_name])
        repositories = response.get("repositories", [])
        if repositories:
            return repositories[0]["repositoryUri"]
    except client.exceptions.RepositoryNotFoundException:
        pass

    response = client.create_repository(
        repositoryName=repository_name,
        imageTagMutability="MUTABLE",
        imageScanningConfiguration={"scanOnPush": False},
        encryptionConfiguration={"encryptionType": "AES256"},
    )
    return response["repository"]["repositoryUri"]


def _ensure_cluster(client, *, cluster_name: str) -> str:
    response = client.describe_clusters(clusters=[cluster_name])
    clusters = response.get("clusters", [])
    if clusters:
        return clusters[0]["clusterArn"]

    response = client.create_cluster(
        clusterName=cluster_name,
        capacityProviders=["FARGATE", "FARGATE_SPOT"],
    )
    return response["cluster"]["clusterArn"]


def _ensure_security_group(
    client,
    *,
    vpc_id: str,
    group_name: str,
    description: str,
) -> str:
    response = client.describe_security_groups(
        Filters=[
            {"Name": "group-name", "Values": [group_name]},
            {"Name": "vpc-id", "Values": [vpc_id]},
        ]
    )
    groups = response.get("SecurityGroups", [])
    if groups:
        return groups[0]["GroupId"]

    response = client.create_security_group(
        GroupName=group_name,
        Description=description,
        VpcId=vpc_id,
    )
    return response["GroupId"]


def _ensure_ingress_rule(
    client,
    *,
    security_group_id: str,
    source_security_group_id: str,
    port: int,
) -> None:
    try:
        client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": port,
                    "ToPort": port,
                    "UserIdGroupPairs": [
                        {
                            "GroupId": source_security_group_id,
                            "Description": "Allow ALB to reach rag_eng tasks",
                        }
                    ],
                }
            ],
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "InvalidPermission.Duplicate":
            raise


def _ensure_cidr_ingress_rule(
    client,
    *,
    security_group_id: str,
    cidr_ip: str,
    port: int,
) -> None:
    try:
        client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": port,
                    "ToPort": port,
                    "IpRanges": [
                        {
                            "CidrIp": cidr_ip,
                            "Description": "Allow public HTTP access to the rag_eng ALB",
                        }
                    ],
                }
            ],
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "InvalidPermission.Duplicate":
            raise


def _ensure_load_balancer(
    client,
    *,
    name: str,
    subnet_ids: list[str],
    security_group_id: str,
) -> tuple[str, str]:
    try:
        response = client.describe_load_balancers(Names=[name])
        lbs = response.get("LoadBalancers", [])
        if lbs:
            lb = lbs[0]
            return lb["LoadBalancerArn"], lb["DNSName"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "LoadBalancerNotFound":
            raise

    response = client.create_load_balancer(
        Name=name,
        Subnets=subnet_ids,
        SecurityGroups=[security_group_id],
        Scheme="internet-facing",
        Type="application",
        IpAddressType="ipv4",
    )
    lb = response["LoadBalancers"][0]
    return lb["LoadBalancerArn"], lb["DNSName"]


def _ensure_target_group(
    client,
    *,
    name: str,
    vpc_id: str,
    port: int,
    health_check_path: str,
) -> str:
    try:
        response = client.describe_target_groups(Names=[name])
        target_groups = response.get("TargetGroups", [])
        if target_groups:
            return target_groups[0]["TargetGroupArn"]
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "TargetGroupNotFound":
            raise

    response = client.create_target_group(
        Name=name,
        Protocol="HTTP",
        Port=port,
        VpcId=vpc_id,
        TargetType="ip",
        HealthCheckProtocol="HTTP",
        HealthCheckPath=health_check_path,
        Matcher={"HttpCode": "200-399"},
    )
    return response["TargetGroups"][0]["TargetGroupArn"]


def _ensure_listener(
    client,
    *,
    load_balancer_arn: str,
    target_group_arn: str,
    port: int,
) -> str:
    response = client.describe_listeners(LoadBalancerArn=load_balancer_arn)
    listeners = response.get("Listeners", [])
    for listener in listeners:
        if listener.get("Port") == port:
            current_actions = listener.get("DefaultActions", [])
            current_target_group_arn = None
            if current_actions:
                current_target_group_arn = current_actions[0].get("TargetGroupArn")
            if current_target_group_arn == target_group_arn:
                return listener["ListenerArn"]
            response = client.modify_listener(
                ListenerArn=listener["ListenerArn"],
                DefaultActions=[
                    {
                        "Type": "forward",
                        "TargetGroupArn": target_group_arn,
                    }
                ],
            )
            return response["Listeners"][0]["ListenerArn"]

    response = client.create_listener(
        LoadBalancerArn=load_balancer_arn,
        Protocol="HTTP",
        Port=port,
        DefaultActions=[
            {
                "Type": "forward",
                "TargetGroupArn": target_group_arn,
            }
        ],
    )
    return response["Listeners"][0]["ListenerArn"]


def _role_exists(client, role_name: str) -> bool:
    try:
        client.get_role(RoleName=role_name)
        return True
    except client.exceptions.NoSuchEntityException:
        return False


def _ensure_execution_role(
    client,
    *,
    account_id: str,
    region: str,
    secret_arns: list[str],
) -> str:
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    if not _role_exists(client, EXECUTION_ROLE_NAME):
        response = client.create_role(
            RoleName=EXECUTION_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description="ECS task execution role for rag_eng.",
        )
        role_arn = response["Role"]["Arn"]
    else:
        role_arn = client.get_role(RoleName=EXECUTION_ROLE_NAME)["Role"]["Arn"]

    client.attach_role_policy(
        RoleName=EXECUTION_ROLE_NAME,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy",
    )
    if secret_arns:
        client.put_role_policy(
            RoleName=EXECUTION_ROLE_NAME,
            PolicyName="codingrabbit-rag-eng-secret-read",
            PolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Sid": "ReadRagEngSecrets",
                            "Effect": "Allow",
                            "Action": ["secretsmanager:GetSecretValue"],
                            "Resource": secret_arns,
                        }
                    ],
                }
            ),
        )
    return role_arn


def _ensure_task_role(
    client,
    *,
    account_id: str,
    region: str,
    bucket_name: str,
    sagemaker_endpoint: str,
) -> str:
    assume_role_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    if not _role_exists(client, TASK_ROLE_NAME):
        response = client.create_role(
            RoleName=TASK_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
            Description="ECS task role for rag_eng runtime AWS access.",
        )
        role_arn = response["Role"]["Arn"]
    else:
        role_arn = client.get_role(RoleName=TASK_ROLE_NAME)["Role"]["Arn"]

    bucket_arn = f"arn:aws:s3:::{bucket_name}"
    endpoint_arn = (
        f"arn:aws:sagemaker:{region}:{account_id}:endpoint/{sagemaker_endpoint}"
    )
    client.put_role_policy(
        RoleName=TASK_ROLE_NAME,
        PolicyName="codingrabbit-rag-eng-runtime",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Sid": "S3AsyncIo",
                        "Effect": "Allow",
                        "Action": [
                            "s3:GetObject",
                            "s3:PutObject",
                            "s3:DeleteObject",
                            "s3:ListBucket",
                        ],
                        "Resource": [bucket_arn, f"{bucket_arn}/*"],
                    },
                    {
                        "Sid": "InvokeSageMakerAsync",
                        "Effect": "Allow",
                        "Action": [
                            "sagemaker:InvokeEndpointAsync",
                            "sagemaker:DescribeEndpoint",
                        ],
                        "Resource": [endpoint_arn],
                    },
                    {
                        "Sid": "UseBedrockConverse",
                        "Effect": "Allow",
                        "Action": [
                            "bedrock:Converse",
                            "bedrock:ConverseStream",
                            "bedrock:InvokeModel",
                            "bedrock:InvokeModelWithResponseStream",
                        ],
                        "Resource": ["*"],
                    },
                    {
                        "Sid": "BedrockMarketplaceAccess",
                        "Effect": "Allow",
                        # Anthropic Bedrock models can require Marketplace subscription
                        # authorization during first use.
                        "Action": [
                            "aws-marketplace:Subscribe",
                            "aws-marketplace:Unsubscribe",
                            "aws-marketplace:ViewSubscriptions",
                        ],
                        "Resource": ["*"],
                    },
                ],
            }
        ),
    )
    return role_arn


def _build_image_and_push(
    *,
    config: DeployConfig,
    repository_uri: str,
) -> str:
    image_tag = f"{ECR_REPOSITORY_NAME}:{DOCKER_IMAGE_TAG}"
    remote_tag = f"{repository_uri}:{DOCKER_IMAGE_TAG}"

    login_client = _client(config, "ecr")
    token = login_client.get_authorization_token()["authorizationData"][0]
    username, password = (
        base64.b64decode(token["authorizationToken"]).decode().split(":", 1)
    )
    registry = token["proxyEndpoint"]

    subprocess.run(
        [
            "docker",
            "login",
            "--username",
            username,
            "--password-stdin",
            registry,
        ],
        input=password.encode("utf-8"),
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run(
        [
            "docker",
            "build",
            "-t",
            image_tag,
            "-f",
            str(REPO_ROOT / "Dockerfile"),
            str(REPO_ROOT),
        ],
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run(
        ["docker", "tag", image_tag, remote_tag],
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run(
        ["docker", "push", remote_tag],
        check=True,
        cwd=REPO_ROOT,
    )
    return remote_tag


def _create_secret_arns(config: DeployConfig) -> dict[str, str]:
    sm = _client(config, "secretsmanager")
    secret_arns: dict[str, str] = {}
    descriptions = {
        "OPENAI_API_KEY": "OpenAI API key for rag_eng chat routes.",
        "COHERE_API_KEY": "Cohere API key for rag_eng retrieval/chat routes.",
        "QDRANT_API_KEY": "Qdrant API key for rag_eng vector search.",
        "COURSE_REGISTRY_DATABASE_URL": "Aurora/PostgreSQL URL for course routing and telemetry.",
    }
    for key in SECRET_ENV_KEYS:
        secret_arns[key] = _ensure_secret(
            sm,
            name=_secret_name(key),
            value=_require_env_value(key),
            description=descriptions[key],
        )
    return secret_arns


def _pick_subnet_vpc_id(config: DeployConfig) -> str:
    if not config.rag_eng_ecs.subnet_ids:
        raise RuntimeError(
            "rag_eng_ecs.subnet_ids must be configured before provisioning."
        )
    ec2 = _client(config, "ec2")
    subnet = ec2.describe_subnets(SubnetIds=[config.rag_eng_ecs.subnet_ids[0]])[
        "Subnets"
    ][0]
    return subnet["VpcId"]


def provision_stack(config: DeployConfig) -> dict[str, Any]:
    """Create or update the AWS resources needed by rag_eng."""
    account_id = _account_id(config)
    region = config.aws.region
    bucket_name = config.aws.s3_bucket
    subnet_ids = list(config.rag_eng_ecs.subnet_ids)
    task_security_group_ids = list(config.rag_eng_ecs.security_group_ids)
    if not subnet_ids:
        raise RuntimeError("rag_eng_ecs.subnet_ids must be set in deployment.yaml")
    if not task_security_group_ids:
        raise RuntimeError(
            "rag_eng_ecs.security_group_ids must be set in deployment.yaml"
        )

    ecr = _client(config, "ecr")
    ecs = _client(config, "ecs")
    ec2 = _client(config, "ec2")
    elbv2 = _client(config, "elbv2")
    logs = _client(config, "logs")
    iam = _client(config, "iam")

    vpc_id = _pick_subnet_vpc_id(config)
    secret_arns = _create_secret_arns(config)
    secret_arn_values = list(secret_arns.values())

    repository_uri = _ensure_ecr_repository(
        ecr,
        repository_name=ECR_REPOSITORY_NAME,
    )
    cluster_arn = _ensure_cluster(ecs, cluster_name=ECS_CLUSTER_NAME)
    _ensure_log_group(logs, log_group_name=LOG_GROUP_NAME)

    task_sg_id = task_security_group_ids[0]
    alb_sg_id = config.rag_eng_ecs.alb_security_group_id
    if not alb_sg_id:
        alb_sg_id = _ensure_security_group(
            ec2,
            vpc_id=vpc_id,
            group_name=ALB_SECURITY_GROUP_NAME,
            description="Security group for the rag_eng application load balancer",
        )
    _ensure_cidr_ingress_rule(
        ec2,
        security_group_id=alb_sg_id,
        cidr_ip="0.0.0.0/0",
        port=DEFAULT_LISTENER_PORT,
    )
    _ensure_ingress_rule(
        ec2,
        security_group_id=task_sg_id,
        source_security_group_id=alb_sg_id,
        port=config.rag_eng_ecs.container_port,
    )

    load_balancer_arn, load_balancer_dns_name = _ensure_load_balancer(
        elbv2,
        name=LOAD_BALANCER_NAME,
        subnet_ids=subnet_ids,
        security_group_id=alb_sg_id,
    )
    target_group_arn = _ensure_target_group(
        elbv2,
        name=TARGET_GROUP_NAME,
        vpc_id=vpc_id,
        port=config.rag_eng_ecs.container_port,
        health_check_path=config.rag_eng_ecs.health_check_path,
    )
    _ensure_listener(
        elbv2,
        load_balancer_arn=load_balancer_arn,
        target_group_arn=target_group_arn,
        port=DEFAULT_LISTENER_PORT,
    )

    execution_role_arn = _ensure_execution_role(
        iam,
        account_id=account_id,
        region=region,
        secret_arns=secret_arn_values,
    )
    task_role_arn = _ensure_task_role(
        iam,
        account_id=account_id,
        region=region,
        bucket_name=bucket_name,
        sagemaker_endpoint=config.sagemaker.endpoint_name,
    )

    image_uri = _build_image_and_push(
        config=config,
        repository_uri=repository_uri,
    )

    provisioned_config = replace(
        config,
        rag_eng_ecs=replace(
            config.rag_eng_ecs,
            image_uri=image_uri,
            execution_role_arn=execution_role_arn,
            task_role_arn=task_role_arn,
            target_group_arn=target_group_arn,
            alb_security_group_id=alb_sg_id,
            secret_arn_map=secret_arns,
        ),
    )

    registered = _register_task_definition(provisioned_config, client=ecs)
    deployed = _upsert_service(
        provisioned_config,
        task_definition=registered["taskDefinitionArn"] or registered["family"],
        client=ecs,
    )

    return {
        "account_id": account_id,
        "region": region,
        "repository_uri": repository_uri,
        "image_uri": image_uri,
        "cluster_arn": cluster_arn,
        "execution_role_arn": execution_role_arn,
        "task_role_arn": task_role_arn,
        "task_security_group_id": task_sg_id,
        "alb_security_group_id": alb_sg_id,
        "load_balancer_arn": load_balancer_arn,
        "load_balancer_dns_name": load_balancer_dns_name,
        "target_group_arn": target_group_arn,
        "secret_arns": secret_arns,
        "task_definition": registered,
        "service": deployed,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Provision the AWS stack for the rag_eng ECS orchestrator.",
    )
    parser.add_argument(
        "action",
        choices=("describe", "apply"),
        help="Describe the current config or provision the AWS stack.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to deployment.yaml (default: deploy/deployment.yaml or DEPLOY_CONFIG)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    config = load_deploy_config(args.config)

    if args.action == "describe":
        from deploy_rag_eng_ecs import describe_config

        print("\n".join(describe_config(config)))
        return 0

    result = provision_stack(config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
