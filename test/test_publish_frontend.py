from __future__ import annotations

import os
from pathlib import Path

from deploy.deployment_config import load_deploy_config
from deploy.publish_frontend import publish_frontend


def _write_config(tmp_path: Path) -> Path:
    app_dir = tmp_path / "frontend"
    dist_dir = app_dir / "dist"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    app_dir.mkdir(exist_ok=True)
    (app_dir / "package.json").write_text("{}", encoding="utf-8")
    (app_dir / "package-lock.json").write_text("{}", encoding="utf-8")
    (dist_dir / "index.html").write_text("<html></html>", encoding="utf-8")
    (assets_dir / "main.js").write_text("console.log('ok');", encoding="utf-8")
    (dist_dir / "assets" / "stale.js").write_text(
        "console.log('stale');", encoding="utf-8"
    )

    path = tmp_path / "deployment.yaml"
    path.write_text(
        f"""
aws:
  region: us-east-1
  profile: default
  s3_bucket: codingrabbit-data-dev
frontend_web:
  enabled: true
  app_dir: {app_dir}
  dist_dir: {dist_dir}
  bucket_name: codingrabbit-frontend-dev
  bucket_prefix: web
  default_root_object: index.html
  spa_fallback_path: /index.html
  price_class: PriceClass_100
  cloudfront:
    distribution_id: E1234567890
    aliases:
      - app.example.com
    certificate_arn: null
    comment: CodingRabbit frontend
    create_oac: true
    invalidation_paths:
      - /*
    api_path_patterns:
      - /api/*
    cache_static_assets: true
    cache_html_seconds: 60
  build:
    vite_api_base_url: ""
    vite_cognito_domain: https://example.auth.us-east-1.amazoncognito.com
    vite_cognito_redirect_uri: https://app.example.com/auth/callback
    vite_cognito_logout_uri: https://app.example.com/logout
    extra_env:
      VITE_APP_VARIANT: production
""",
        encoding="utf-8",
    )
    return path


class _FakePaginator:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self._pages = pages
        self.calls: list[tuple[str, str]] = []

    def paginate(self, *, Bucket: str, Prefix: str):  # noqa: N803
        self.calls.append((Bucket, Prefix))
        return self._pages


class _FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []
        self.paginator = _FakePaginator(
            [{"Contents": [{"Key": "web/old.js"}]}],
        )

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        return {}

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return self.paginator

    def delete_objects(self, **kwargs):
        self.delete_calls.append(kwargs)
        return {}


class _FakeCloudFrontClient:
    def __init__(self) -> None:
        self.invalidation_calls: list[dict[str, object]] = []

    def create_invalidation(self, **kwargs):
        self.invalidation_calls.append(kwargs)
        return {"Invalidation": {"Id": "INV123", "Status": "InProgress"}}


def test_publish_frontend_syncs_dist_and_invalidates_cloudfront(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.delenv("VITE_API_BASE_URL", raising=False)
    monkeypatch.delenv("VITE_COGNITO_DOMAIN", raising=False)
    monkeypatch.delenv("VITE_COGNITO_REDIRECT_URI", raising=False)
    monkeypatch.delenv("VITE_COGNITO_LOGOUT_URI", raising=False)
    monkeypatch.setattr(
        "deploy.publish_frontend._local_frontend_build_supported",
        lambda: True,
    )

    config = load_deploy_config(_write_config(tmp_path))
    fake_s3 = _FakeS3Client()
    fake_cloudfront = _FakeCloudFrontClient()
    run_calls: list[tuple[list[str], dict[str, str]]] = []

    def _fake_run_command(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        run_calls.append((cmd, env))
        assert cwd == Path(config.frontend_web.app_dir)

    monkeypatch.setattr("deploy.publish_frontend._run_command", _fake_run_command)

    summary = publish_frontend(
        config,
        s3_client=fake_s3,
        cloudfront_client=fake_cloudfront,
        skip_tests=True,
    )

    assert run_calls[0][0] == ["npm", "ci", "--include=dev"]
    assert run_calls[1][0] == ["npm", "run", "build"]
    assert run_calls[0][1]["VITE_API_BASE_URL"] == ""
    assert run_calls[0][1]["VITE_APP_VARIANT"] == "production"
    assert "npm_config_production" not in run_calls[0][1]
    assert "NODE_ENV" not in run_calls[0][1]
    assert run_calls[1][1]["NODE_ENV"] == "production"

    uploaded_keys = [call["Key"] for call in fake_s3.put_calls]
    assert uploaded_keys == [
        "web/assets/main.js",
        "web/assets/stale.js",
        "web/index.html",
    ]
    assert fake_s3.delete_calls[0]["Delete"]["Objects"] == [{"Key": "web/old.js"}]

    html_upload = next(
        call for call in fake_s3.put_calls if call["Key"] == "web/index.html"
    )
    assert html_upload["CacheControl"] == "public, max-age=60, must-revalidate"
    assert html_upload["ContentType"] == "text/html"

    asset_upload = next(
        call for call in fake_s3.put_calls if call["Key"] == "web/assets/main.js"
    )
    assert asset_upload["CacheControl"] == "public, max-age=31536000, immutable"

    assert fake_cloudfront.invalidation_calls[0]["DistributionId"] == "E1234567890"
    assert fake_cloudfront.invalidation_calls[0]["InvalidationBatch"]["Paths"][
        "Items"
    ] == ["/*"]
    assert summary["distribution_id"] == "E1234567890"
    assert summary["sync"]["deleted_count"] == 1


def test_load_publish_config_ignores_frontend_env_overrides(
    tmp_path, monkeypatch
) -> None:
    config_path = _write_config(tmp_path)
    monkeypatch.setenv("DEPLOY_CONFIG", str(config_path))
    monkeypatch.setenv("VITE_API_BASE_URL", "http://localhost:8001")
    monkeypatch.setenv("VITE_COGNITO_DOMAIN", "https://override.invalid")
    monkeypatch.setenv(
        "VITE_COGNITO_REDIRECT_URI", "http://localhost:5173/auth/callback"
    )
    monkeypatch.setenv("VITE_COGNITO_LOGOUT_URI", "http://localhost:5173/logout")
    monkeypatch.setenv("FRONTEND_EXTRA_ENV_JSON", '{"VITE_APP_VARIANT":"dev"}')

    seen_env: dict[str, str | None] = {}
    from deploy import publish_frontend as publish_frontend_module

    real_load_deploy_config = load_deploy_config

    def _fake_load_deploy_config(*args, **kwargs):
        seen_env["VITE_API_BASE_URL"] = os.environ.get("VITE_API_BASE_URL")
        seen_env["VITE_COGNITO_DOMAIN"] = os.environ.get("VITE_COGNITO_DOMAIN")
        seen_env["VITE_COGNITO_REDIRECT_URI"] = os.environ.get(
            "VITE_COGNITO_REDIRECT_URI"
        )
        seen_env["VITE_COGNITO_LOGOUT_URI"] = os.environ.get("VITE_COGNITO_LOGOUT_URI")
        seen_env["FRONTEND_EXTRA_ENV_JSON"] = os.environ.get("FRONTEND_EXTRA_ENV_JSON")
        return real_load_deploy_config(*args, **kwargs)

    monkeypatch.setattr(
        publish_frontend_module,
        "load_deploy_config",
        _fake_load_deploy_config,
    )

    config = publish_frontend_module._load_publish_config()

    assert seen_env == {
        "VITE_API_BASE_URL": None,
        "VITE_COGNITO_DOMAIN": None,
        "VITE_COGNITO_REDIRECT_URI": None,
        "VITE_COGNITO_LOGOUT_URI": None,
        "FRONTEND_EXTRA_ENV_JSON": None,
    }
    assert config.frontend_web.build.vite_api_base_url == ""
    assert config.frontend_web.build.vite_cognito_domain == (
        "https://example.auth.us-east-1.amazoncognito.com"
    )
    assert config.frontend_web.build.vite_cognito_redirect_uri == (
        "https://app.example.com/auth/callback"
    )
    assert config.frontend_web.build.vite_cognito_logout_uri == (
        "https://app.example.com/logout"
    )


def test_build_frontend_falls_back_to_docker_when_node_is_old(
    tmp_path, monkeypatch
) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    run_calls: list[tuple[list[str], dict[str, str]]] = []
    from deploy.publish_frontend import _build_frontend

    def _fake_run_command(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
        run_calls.append((cmd, env))
        assert cwd == Path(config.frontend_web.app_dir).parent

    monkeypatch.setattr(
        "deploy.publish_frontend._local_frontend_build_supported",
        lambda: False,
    )
    monkeypatch.setattr("deploy.publish_frontend._run_command", _fake_run_command)

    _build_frontend(config)

    assert run_calls[0][0][0] == "docker"
    assert "node:22-bookworm" in run_calls[0][0]
    volume_index = run_calls[0][0].index("-v") + 1
    workdir_index = run_calls[0][0].index("-w") + 1
    assert run_calls[0][0][volume_index] == (
        f"{Path(config.frontend_web.app_dir).parent}:/workspace"
    )
    assert run_calls[0][0][workdir_index] == "/workspace/frontend"


def test_build_frontend_runs_tests_before_build(tmp_path, monkeypatch) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    run_calls: list[tuple[list[str], dict[str, str]]] = []
    from deploy.publish_frontend import _build_frontend

    monkeypatch.delenv("FRONTEND_SKIP_TESTS", raising=False)
    monkeypatch.setattr(
        "deploy.publish_frontend._local_frontend_build_supported",
        lambda: True,
    )
    monkeypatch.setattr(
        "deploy.publish_frontend._run_command",
        lambda cmd, *, cwd, env: run_calls.append((cmd, env)),
    )

    _build_frontend(config)

    assert run_calls[0][0] == ["npm", "ci", "--include=dev"]
    assert run_calls[1][0] == ["npm", "run", "test:components"]
    assert run_calls[2][0] == ["npm", "run", "build"]


def test_build_frontend_skips_tests_when_requested(tmp_path, monkeypatch) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    run_calls: list[tuple[list[str], dict[str, str]]] = []
    from deploy.publish_frontend import _build_frontend

    monkeypatch.setattr(
        "deploy.publish_frontend._local_frontend_build_supported",
        lambda: True,
    )
    monkeypatch.setattr(
        "deploy.publish_frontend._run_command",
        lambda cmd, *, cwd, env: run_calls.append((cmd, env)),
    )

    _build_frontend(config, skip_tests=True)

    assert [call[0] for call in run_calls] == [
        ["npm", "ci", "--include=dev"],
        ["npm", "run", "build"],
    ]


def test_build_frontend_skips_tests_via_env_var(tmp_path, monkeypatch) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    run_calls: list[tuple[list[str], dict[str, str]]] = []
    from deploy.publish_frontend import _build_frontend

    monkeypatch.setenv("FRONTEND_SKIP_TESTS", "1")
    monkeypatch.setattr(
        "deploy.publish_frontend._local_frontend_build_supported",
        lambda: True,
    )
    monkeypatch.setattr(
        "deploy.publish_frontend._run_command",
        lambda cmd, *, cwd, env: run_calls.append((cmd, env)),
    )

    _build_frontend(config)

    assert [call[0] for call in run_calls] == [
        ["npm", "ci", "--include=dev"],
        ["npm", "run", "build"],
    ]
