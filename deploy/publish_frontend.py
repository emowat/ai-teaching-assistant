"""Build and publish the React/Vite frontend to S3 and CloudFront.

This helper keeps the frontend delivery slice intentionally narrow:

- build the frontend with deployment-configured Vite env values
- sync the generated static assets to the configured S3 bucket/prefix
- invalidate the configured CloudFront distribution paths

It does not create the S3 bucket, CloudFront distribution, or DNS records.
Those infra resources are expected to exist before this publish flow runs.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
import time
import uuid
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator

import boto3
from dotenv import load_dotenv


load_dotenv()

DEPLOY_DIR = Path(__file__).resolve().parent
REPO_ROOT = DEPLOY_DIR.parent
if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

from deployment_config import DeployConfig, load_deploy_config  # noqa: E402


MIN_FRONTEND_NODE_VERSION = (20, 19, 0)
FRONTEND_BUILD_DOCKER_IMAGE = "node:22-bookworm"
FRONTEND_BUILD_ENV_KEYS = (
    "VITE_API_BASE_URL",
    "VITE_COGNITO_DOMAIN",
    "VITE_COGNITO_REDIRECT_URI",
    "VITE_COGNITO_LOGOUT_URI",
    "FRONTEND_EXTRA_ENV_JSON",
)


def _session(config: DeployConfig) -> boto3.Session:
    return boto3.Session(
        profile_name=config.aws.profile,
        region_name=config.aws.region,
    )


def _repo_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def _frontend_env(config: DeployConfig, *, production: bool) -> dict[str, str]:
    env = os.environ.copy()
    env.update(config.frontend_web.build.as_env_dict())
    if production:
        env["NODE_ENV"] = "production"
    else:
        env.pop("NODE_ENV", None)
        env.pop("npm_config_production", None)
    return env


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    cleaned = version.strip().lstrip("v")
    parts = cleaned.split(".")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def _local_frontend_build_supported() -> bool:
    try:
        completed = subprocess.run(
            ["node", "-v"],
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False

    parsed = _parse_semver(completed.stdout)
    if parsed is None:
        return False
    return parsed >= MIN_FRONTEND_NODE_VERSION


def _run_command(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


def _tests_disabled(skip_tests: bool) -> bool:
    if skip_tests:
        return True
    return os.getenv("FRONTEND_SKIP_TESTS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _load_publish_config() -> DeployConfig:
    """Load deployment config while ignoring local frontend build env overrides.

    The repo-root `.env` is still useful for local dev and AWS auth, but the
    production frontend build settings must come from `deploy/deployment.yaml`.
    """

    saved_env = {key: os.environ.get(key) for key in FRONTEND_BUILD_ENV_KEYS}
    try:
        for key in FRONTEND_BUILD_ENV_KEYS:
            os.environ.pop(key, None)
        return load_deploy_config()
    finally:
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _docker_build_command(
    *,
    app_dir: Path,
    env: dict[str, str],
    skip_tests: bool,
) -> list[str]:
    docker_env_flags: list[str] = []
    for key in sorted(env):
        if not key.startswith("VITE_"):
            continue
        docker_env_flags.extend(["-e", f"{key}={env[key]}"])

    workspace_root = app_dir.parent
    relative_app_dir = app_dir.relative_to(workspace_root).as_posix()
    test_step = "" if skip_tests else "npm run test:components && "
    return [
        "docker",
        "run",
        "--rm",
        "-u",
        f"{os.getuid()}:{os.getgid()}",
        "-v",
        f"{workspace_root}:/workspace",
        "-w",
        f"/workspace/{relative_app_dir}",
        "-e",
        "HOME=/tmp",
        "-e",
        "npm_config_cache=/tmp/.npm",
        *docker_env_flags,
        FRONTEND_BUILD_DOCKER_IMAGE,
        "bash",
        "-lc",
        f"npm ci --include=dev && {test_step}NODE_ENV=production npm run build",
    ]


def _build_frontend(config: DeployConfig, *, skip_tests: bool = False) -> None:
    app_dir = _repo_path(config.frontend_web.app_dir)
    workspace_root = app_dir.parent
    package_json = app_dir / "package.json"
    if not package_json.is_file():
        raise RuntimeError(f"Missing frontend package.json: {package_json}")

    print(f"[1/3] Building frontend in {app_dir}")
    if _local_frontend_build_supported():
        install_env = _frontend_env(config, production=False)
        build_env = _frontend_env(config, production=True)
        install_cmd = (
            ["npm", "ci", "--include=dev"]
            if (app_dir / "package-lock.json").is_file()
            else ["npm", "install", "--include=dev"]
        )
        _run_command(install_cmd, cwd=app_dir, env=install_env)
        if _tests_disabled(skip_tests):
            print("    Frontend tests skipped")
        else:
            print("    Running frontend test suite (npm run test:components)")
            _run_command(
                ["npm", "run", "test:components"], cwd=app_dir, env=install_env
            )
        _run_command(["npm", "run", "build"], cwd=app_dir, env=build_env)
        return

    print(
        "    Local Node.js is too old for the current frontend toolchain; "
        f"using Docker build image {FRONTEND_BUILD_DOCKER_IMAGE}"
    )
    docker_env = _frontend_env(config, production=True)
    _run_command(
        _docker_build_command(
            app_dir=app_dir,
            env=docker_env,
            skip_tests=_tests_disabled(skip_tests),
        ),
        cwd=workspace_root,
        env=os.environ.copy(),
    )


def _normalized_prefix(prefix: str) -> str:
    return prefix.strip("/").strip()


def _prefix_root(prefix: str) -> str:
    normalized = _normalized_prefix(prefix)
    if not normalized:
        return ""
    return f"{normalized}/"


def _s3_key(prefix: str, relative_path: Path) -> str:
    normalized = _normalized_prefix(prefix)
    relative = relative_path.as_posix()
    if not normalized:
        return relative
    return f"{normalized}/{relative}"


def _content_type_for_path(path: Path) -> str:
    content_type, _ = mimetypes.guess_type(path.name)
    return content_type or "application/octet-stream"


def _cache_control_for_path(
    path: Path,
    *,
    cache_html_seconds: int,
    cache_static_assets: bool,
) -> str:
    if path.suffix.lower() == ".html":
        return f"public, max-age={cache_html_seconds}, must-revalidate"
    if cache_static_assets:
        return "public, max-age=31536000, immutable"
    return f"public, max-age={cache_html_seconds}, must-revalidate"


def _iter_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _chunked(items: list[str], size: int) -> Iterator[list[str]]:
    iterator = iter(items)
    while chunk := list(islice(iterator, size)):
        yield chunk


def _list_existing_keys(
    s3_client,
    *,
    bucket_name: str,
    prefix: str,
) -> set[str]:
    paginator = s3_client.get_paginator("list_objects_v2")
    existing: set[str] = set()
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item.get("Key")
            if key:
                existing.add(str(key))
    return existing


def _sync_dist_to_s3(
    s3_client,
    *,
    bucket_name: str,
    bucket_prefix: str,
    dist_dir: Path,
    cache_html_seconds: int,
    cache_static_assets: bool,
) -> dict[str, Any]:
    if not dist_dir.is_dir():
        raise RuntimeError(f"Frontend dist directory does not exist: {dist_dir}")

    prefix_root = _prefix_root(bucket_prefix)
    uploaded_keys: list[str] = []
    local_keys: set[str] = set()

    files = list(_iter_files(dist_dir))
    if not files:
        raise RuntimeError(f"Frontend dist directory is empty: {dist_dir}")

    print(
        f"[2/3] Syncing {len(files)} frontend files to s3://{bucket_name}/{prefix_root}"
    )
    for file_path in files:
        relative_path = file_path.relative_to(dist_dir)
        key = _s3_key(bucket_prefix, relative_path)
        local_keys.add(key)
        s3_client.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=file_path.read_bytes(),
            ContentType=_content_type_for_path(file_path),
            CacheControl=_cache_control_for_path(
                file_path,
                cache_html_seconds=cache_html_seconds,
                cache_static_assets=cache_static_assets,
            ),
        )
        uploaded_keys.append(key)

    existing_keys = _list_existing_keys(
        s3_client,
        bucket_name=bucket_name,
        prefix=prefix_root,
    )
    stale_keys = sorted(existing_keys - local_keys)
    deleted_keys: list[str] = []
    for chunk in _chunked(stale_keys, 1000):
        s3_client.delete_objects(
            Bucket=bucket_name,
            Delete={
                "Objects": [{"Key": key} for key in chunk],
                "Quiet": True,
            },
        )
        deleted_keys.extend(chunk)

    return {
        "uploaded_count": len(uploaded_keys),
        "deleted_count": len(deleted_keys),
        "uploaded_keys": uploaded_keys,
        "deleted_keys": deleted_keys,
    }


def _invalidate_cloudfront(
    cloudfront_client,
    *,
    distribution_id: str,
    paths: Iterable[str],
) -> dict[str, Any]:
    items = [path if path.startswith("/") else f"/{path}" for path in paths]
    if not items:
        items = ["/*"]

    print(f"[3/3] Invalidating CloudFront distribution {distribution_id}")
    response = cloudfront_client.create_invalidation(
        DistributionId=distribution_id,
        InvalidationBatch={
            "CallerReference": f"frontend-publish-{int(time.time())}-{uuid.uuid4().hex}",
            "Paths": {"Quantity": len(items), "Items": items},
        },
    )
    invalidation = response.get("Invalidation", {})
    return {
        "id": invalidation.get("Id"),
        "status": invalidation.get("Status"),
        "paths": items,
    }


def missing_publish_values(config: DeployConfig) -> list[str]:
    missing: list[str] = []
    if not config.frontend_web.enabled:
        missing.append("FRONTEND_ENABLED")
    if not config.frontend_web.bucket_name.strip():
        missing.append("FRONTEND_BUCKET_NAME")
    if not config.frontend_web.cloudfront.distribution_id:
        missing.append("FRONTEND_CLOUDFRONT_DISTRIBUTION_ID")
    if not _repo_path(config.frontend_web.app_dir).is_dir():
        missing.append("FRONTEND_APP_DIR")
    return missing


def describe_config(config: DeployConfig) -> list[str]:
    frontend = config.frontend_web
    lines = [
        "==> frontend publish",
        f"    Region:             {config.aws.region}",
        f"    Profile:            {config.aws.profile or '(default credential chain)'}",
        f"    Enabled:            {frontend.enabled}",
        f"    App dir:            {_repo_path(frontend.app_dir)}",
        f"    Dist dir:           {_repo_path(frontend.dist_dir)}",
        f"    Bucket:             {frontend.bucket_name or '(missing)'}",
        f"    Prefix:             {frontend.bucket_prefix or '(root)'}",
        f"    Distribution ID:    {frontend.cloudfront.distribution_id or '(missing)'}",
        f"    Invalidations:      {frontend.cloudfront.invalidation_paths}",
        f"    API path patterns:  {frontend.cloudfront.api_path_patterns}",
        f"    Vite API base URL:  {frontend.build.vite_api_base_url or '(same-origin)'}",
        f"    Cognito domain:     {frontend.build.vite_cognito_domain or '(missing)'}",
        f"    Cognito redirect:   {frontend.build.vite_cognito_redirect_uri or '(missing)'}",
        f"    Cognito logout:     {frontend.build.vite_cognito_logout_uri or '(missing)'}",
    ]
    missing = missing_publish_values(config)
    lines.append(
        "    Missing values:      " + (", ".join(missing) if missing else "(none)")
    )
    return lines


def publish_frontend(
    config: DeployConfig,
    *,
    session: boto3.Session | None = None,
    s3_client: Any | None = None,
    cloudfront_client: Any | None = None,
    skip_tests: bool = False,
) -> dict[str, Any]:
    if missing_publish_values(config):
        missing = ", ".join(missing_publish_values(config))
        raise RuntimeError(f"Frontend publish configuration is incomplete: {missing}")

    _build_frontend(config, skip_tests=skip_tests)

    session = session or _session(config)
    s3_client = s3_client or session.client("s3")
    cloudfront_client = cloudfront_client or session.client("cloudfront")

    dist_dir = _repo_path(config.frontend_web.dist_dir)
    sync_summary = _sync_dist_to_s3(
        s3_client,
        bucket_name=config.frontend_web.bucket_name,
        bucket_prefix=config.frontend_web.bucket_prefix,
        dist_dir=dist_dir,
        cache_html_seconds=config.frontend_web.cloudfront.cache_html_seconds,
        cache_static_assets=config.frontend_web.cloudfront.cache_static_assets,
    )
    invalidation_summary = _invalidate_cloudfront(
        cloudfront_client,
        distribution_id=config.frontend_web.cloudfront.distribution_id or "",
        paths=config.frontend_web.cloudfront.invalidation_paths,
    )

    return {
        "bucket_name": config.frontend_web.bucket_name,
        "bucket_prefix": config.frontend_web.bucket_prefix,
        "distribution_id": config.frontend_web.cloudfront.distribution_id,
        "sync": sync_summary,
        "invalidation": invalidation_summary,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print("\nPublish summary")
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build and publish the frontend")
    parser.add_argument(
        "command",
        choices=["describe", "publish"],
        help="describe | publish",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help=(
            "Skip the frontend test suite gate (npm run test:components) before "
            "building. Can also be set via FRONTEND_SKIP_TESTS=1."
        ),
    )
    args = parser.parse_args()

    config = _load_publish_config()

    if args.command == "describe":
        for line in describe_config(config):
            print(line)
        return

    summary = publish_frontend(config, skip_tests=args.skip_tests)
    _print_summary(summary)


if __name__ == "__main__":
    main()
