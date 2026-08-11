"""Build and push the dedicated ECR image for the on-demand ingestion worker.

Unlike the evaluation worker image, this one does not need a curated source
whitelist - ingestion_worker/Dockerfile already COPYs the data_ingestion/,
rag/, and rag_eng/ directories wholesale (see that Dockerfile), so the build
context is just the repo root and there is no staging step.
"""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE_PATH = Path("ingestion_worker/Dockerfile")
DEFAULT_REPOSITORY_NAME = "codingrabbit-ingestion"
DEFAULT_IMAGE_TAG = "latest"
DEFAULT_PLATFORM = "linux/amd64"


@dataclass(frozen=True)
class IngestionWorkerImageConfig:
    """Resolved image build and push settings."""

    aws_region: str
    aws_profile: str | None
    repository_name: str
    image_tag: str
    repo_root: Path


def _boto3_session(*, region: str, profile_name: str | None):
    import boto3

    return boto3.Session(profile_name=profile_name, region_name=region)


def _ensure_ecr_repository(client, *, repository_name: str) -> str:
    try:
        response = client.describe_repositories(repositoryNames=[repository_name])
        repositories = response.get("repositories") or []
        if repositories:
            repository_uri = repositories[0].get("repositoryUri")
            if isinstance(repository_uri, str) and repository_uri.strip():
                return repository_uri
    except Exception as exc:  # pragma: no cover - AWS errors covered by integration
        error_code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if error_code not in {"RepositoryNotFoundException", "RepositoryNotFound"}:
            raise

    response = client.create_repository(repositoryName=repository_name)
    repository = response.get("repository") or {}
    repository_uri = repository.get("repositoryUri")
    if not isinstance(repository_uri, str) or not repository_uri.strip():
        raise RuntimeError(
            f"Failed to resolve repository URI for ECR repository {repository_name!r}."
        )
    return repository_uri


def _docker_login(*, client, docker_binary: str) -> None:
    token = client.get_authorization_token()["authorizationData"][0]
    username, password = (
        base64.b64decode(token["authorizationToken"]).decode().split(":", 1)
    )
    registry = token["proxyEndpoint"]
    subprocess.run(
        [
            docker_binary,
            "login",
            "--username",
            username,
            "--password-stdin",
            registry,
        ],
        input=password.encode("utf-8"),
        check=True,
    )


def build_and_push_image(
    *,
    config: IngestionWorkerImageConfig,
    docker_binary: str = "docker",
) -> str:
    """Build the worker image from the repo root and push it to ECR."""
    session = _boto3_session(region=config.aws_region, profile_name=config.aws_profile)
    ecr_client = session.client("ecr")
    repository_uri = _ensure_ecr_repository(
        ecr_client,
        repository_name=config.repository_name,
    )
    local_tag = f"{config.repository_name}:{config.image_tag}"
    remote_tag = f"{repository_uri}:{config.image_tag}"
    dockerfile_path = config.repo_root / DOCKERFILE_PATH
    if not dockerfile_path.is_file():
        raise FileNotFoundError(f"Missing ingestion worker Dockerfile: {dockerfile_path}")

    _docker_login(client=ecr_client, docker_binary=docker_binary)
    subprocess.run(
        [
            docker_binary,
            "build",
            "--platform",
            DEFAULT_PLATFORM,
            "-t",
            local_tag,
            "-f",
            str(dockerfile_path),
            str(config.repo_root),
        ],
        check=True,
    )
    subprocess.run(
        [docker_binary, "tag", local_tag, remote_tag],
        check=True,
    )
    subprocess.run(
        [docker_binary, "push", remote_tag],
        check=True,
    )
    return remote_tag


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and push the dedicated ECS ingestion worker image.",
    )
    parser.add_argument(
        "--region",
        default=os.getenv(
            "AWS_REGION",
            os.getenv("AWS_DEFAULT_REGION", os.getenv("DEPLOY_AWS_REGION", "us-east-1")),
        ),
        help="AWS region used for the ECR repository and docker login",
    )
    parser.add_argument(
        "--profile",
        default=os.getenv("AWS_PROFILE", os.getenv("DEPLOY_AWS_PROFILE")),
        help="Optional AWS profile for boto3",
    )
    parser.add_argument(
        "--repository-name",
        default=os.getenv("INGESTION_ECR_REPOSITORY", DEFAULT_REPOSITORY_NAME),
        help="ECR repository name to create or reuse",
    )
    parser.add_argument(
        "--tag",
        default=os.getenv("INGESTION_ECR_IMAGE_TAG", DEFAULT_IMAGE_TAG),
        help="Docker image tag to build and push",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root used as the Docker build context",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = IngestionWorkerImageConfig(
        aws_region=args.region,
        aws_profile=args.profile or None,
        repository_name=args.repository_name,
        image_tag=args.tag,
        repo_root=Path(args.repo_root).expanduser().resolve(),
    )
    image_uri = build_and_push_image(config=config)
    print(image_uri)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
