"""Build and push the dedicated ECR image for the offline evaluation worker."""

from __future__ import annotations

import argparse
import base64
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPOSITORY_NAME = "codingrabbit-evaluation-worker"
DEFAULT_IMAGE_TAG = "latest"
DEFAULT_PLATFORM = "linux/amd64"
BUILD_CONTEXT_DIRNAME = "codingrabbit-evaluation-worker-build"
WORKER_REQUIREMENTS_PATH = Path("deploy/evaluation_worker_requirements.txt")

_WORKER_SOURCE_FILES: tuple[Path, ...] = (
    Path("model_eval/__init__.py"),
    Path("model_eval/evaluation_worker.py"),
    Path("model_eval/eval_functions.py"),
    Path("model_eval/prompts.py"),
    Path("model_eval/requirements.txt"),
    Path("model_eval/backfill_ta_effectiveness.py"),
    Path("rag/__init__.py"),
    Path("rag/schemas.py"),
    Path("rag_eng/__init__.py"),
    Path("rag_eng/aurora_retry.py"),
    Path("rag_eng/aurora_secret_refresh.py"),
    Path("rag_eng/config.py"),
    Path("rag_eng/llm_clients.py"),
    Path("rag_eng/schemas.py"),
    Path("rag_eng/ta_effectiveness_ingest.py"),
    Path("rag_eng/inference_config.yaml"),
    Path("rag_eng/runtime_config.yaml"),
)


@dataclass(frozen=True)
class EvaluationWorkerImageConfig:
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


def _dockerfile_text() -> str:
    return """FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY model_eval /app/model_eval
COPY rag /app/rag
COPY rag_eng /app/rag_eng

CMD ["python", "-m", "model_eval.evaluation_worker"]
"""


def _copy_selected_sources(*, repo_root: Path, build_root: Path) -> None:
    for relative_path in _WORKER_SOURCE_FILES:
        source_path = repo_root / relative_path
        if not source_path.is_file():
            raise FileNotFoundError(f"Missing worker source file: {relative_path}")
        destination_path = build_root / relative_path
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)

    requirements_source = repo_root / WORKER_REQUIREMENTS_PATH
    if not requirements_source.is_file():
        raise FileNotFoundError(f"Missing worker requirements file: {requirements_source}")
    shutil.copy2(requirements_source, build_root / "requirements.txt")

    # The worker only needs the RAG schema module; keep the package init empty so
    # importing `rag.schemas` does not drag the full online retrieval stack into
    # the evaluation image.
    (build_root / "rag" / "__init__.py").write_text(
        '"""Minimal RAG package for the evaluation worker image."""\n',
        encoding="utf-8",
    )

    (build_root / "Dockerfile").write_text(_dockerfile_text(), encoding="utf-8")


def stage_build_context(*, repo_root: Path, build_root: Path) -> Path:
    """Create a temporary Docker build context with only the worker sources."""
    build_root.mkdir(parents=True, exist_ok=True)
    _copy_selected_sources(repo_root=repo_root, build_root=build_root)
    return build_root


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
    config: EvaluationWorkerImageConfig,
    docker_binary: str = "docker",
) -> str:
    """Build the worker image from a staged context and push it to ECR."""
    session = _boto3_session(region=config.aws_region, profile_name=config.aws_profile)
    ecr_client = session.client("ecr")
    repository_uri = _ensure_ecr_repository(
        ecr_client,
        repository_name=config.repository_name,
    )
    local_tag = f"{config.repository_name}:{config.image_tag}"
    remote_tag = f"{repository_uri}:{config.image_tag}"

    with tempfile.TemporaryDirectory(prefix=f"{BUILD_CONTEXT_DIRNAME}-") as tmpdir:
        build_root = stage_build_context(
            repo_root=config.repo_root,
            build_root=Path(tmpdir),
        )
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
                str(build_root / "Dockerfile"),
                str(build_root),
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
        description="Build and push the dedicated ECS evaluation worker image.",
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
        default=os.getenv(
            "EVALUATION_WORKER_ECR_REPOSITORY",
            os.getenv("DEPLOY_EVALUATION_WORKER_ECR_REPOSITORY", DEFAULT_REPOSITORY_NAME),
        ),
        help="ECR repository name to create or reuse",
    )
    parser.add_argument(
        "--tag",
        default=os.getenv(
            "EVALUATION_WORKER_ECR_IMAGE_TAG",
            os.getenv("DEPLOY_EVALUATION_WORKER_ECR_IMAGE_TAG", DEFAULT_IMAGE_TAG),
        ),
        help="Docker image tag to build and push",
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root used to stage the worker build context",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    config = EvaluationWorkerImageConfig(
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
