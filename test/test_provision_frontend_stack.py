from __future__ import annotations

from pathlib import Path

from botocore.exceptions import ClientError

from deploy.provision_frontend_stack import (
    FRONTEND_BUCKET_PREFIX,
    _bucket_name,
    _bucket_policy,
    _build_distribution_config,
    _find_managed_policy_id,
    _ensure_oac,
    _spa_function_code,
    describe_config,
)
from deploy.deployment_config import load_deploy_config


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "deployment.yaml"
    path.write_text(
        """
aws:
  region: us-east-1
  profile: codingrabbit-dev
  s3_bucket: codingrabbit-data-dev
rag_eng_ecs:
  target_group_arn: arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/rag-eng/1234567890123456
frontend_web:
  enabled: true
  app_dir: ./frontend
  dist_dir: ./frontend/dist
  bucket_name: ""
  bucket_prefix: web
  default_root_object: index.html
  spa_fallback_path: /index.html
  price_class: PriceClass_100
  cloudfront:
    distribution_id: ""
    aliases: []
    certificate_arn: null
    comment: CodingRabbit frontend
    create_oac: true
    invalidation_paths:
      - /*
    api_path_patterns:
      - /api/*
      - /admin/*
      - /health
    cache_static_assets: true
    cache_html_seconds: 60
  build:
    vite_api_base_url: ""
    vite_cognito_domain: https://example.auth.us-east-1.amazoncognito.com
    vite_cognito_redirect_uri: https://app.example.com/auth/callback
    vite_cognito_logout_uri: https://app.example.com/logout
    extra_env: {}
""",
        encoding="utf-8",
    )
    return path


def test_frontend_bucket_name_auto_generates_from_account(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    assert _bucket_name(config, "123456789012") == (
        f"{FRONTEND_BUCKET_PREFIX}-123456789012-us-east-1"
    )


def test_build_distribution_config_contains_s3_and_alb_origins(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    payload = _build_distribution_config(
        config=config,
        bucket_name="codingrabbit-frontend-123456789012-us-east-1",
        account_id="123456789012",
        alb_dns_name="internal-rag-eng-alb-123.us-east-1.elb.amazonaws.com",
        oac_id="oac-123",
        spa_function_arn="arn:aws:cloudfront::123456789012:function/codingrabbit-frontend-spa-rewrite",
        cache_disabled_id="cache-disabled",
        cache_optimized_id="cache-optimized",
        origin_request_policy_id="origin-request-policy",
    )

    origins = {origin["Id"]: origin for origin in payload["Origins"]["Items"]}
    assert origins["frontend-s3"]["DomainName"].startswith(
        "codingrabbit-frontend-123456789012-us-east-1.s3."
    )
    assert origins["frontend-s3"]["OriginAccessControlId"] == "oac-123"
    assert origins["rag-eng-alb"]["DomainName"] == (
        "internal-rag-eng-alb-123.us-east-1.elb.amazonaws.com"
    )
    assert payload["DefaultCacheBehavior"]["CachePolicyId"] == "cache-disabled"
    assert payload["DefaultCacheBehavior"]["FunctionAssociations"]["Items"][0][
        "FunctionARN"
    ].endswith("codingrabbit-frontend-spa-rewrite")
    assert payload["CacheBehaviors"]["Items"][0]["PathPattern"] == "/assets/*"
    assert payload["CacheBehaviors"]["Items"][1]["CachePolicyId"] == "cache-disabled"
    assert payload["CacheBehaviors"]["Items"][1]["OriginRequestPolicyId"] == (
        "origin-request-policy"
    )


def test_bucket_policy_scopes_read_access_to_distribution() -> None:
    policy = _bucket_policy(
        "codingrabbit-frontend-123456789012-us-east-1",
        "arn:aws:cloudfront::123456789012:distribution/EDIST",
        "123456789012",
    )
    assert "cloudfront.amazonaws.com" in policy
    assert "arn:aws:cloudfront::123456789012:distribution/EDIST" in policy


def test_find_managed_policy_id_iterates_without_paginator() -> None:
    class DummyCloudFront:
        def __init__(self) -> None:
            self.calls: list[dict[str, str]] = []

        def list_cache_policies(self, **kwargs):
            self.calls.append(kwargs)
            if "Marker" not in kwargs:
                return {
                    "CachePolicyList": {
                        "Items": [
                            {
                                "CachePolicy": {
                                    "Id": "cache-other",
                                    "CachePolicyConfig": {"Name": "Other"},
                                }
                            }
                        ],
                        "IsTruncated": True,
                        "NextMarker": "page-2",
                    }
                }
            return {
                "CachePolicyList": {
                    "Items": [
                        {
                            "CachePolicy": {
                                "Id": "cache-disabled",
                                "CachePolicyConfig": {
                                    "Name": "Managed-CachingDisabled"
                                },
                            }
                        }
                    ],
                    "IsTruncated": False,
                }
            }

        def list_origin_request_policies(self, **kwargs):
            self.calls.append(kwargs)
            return {
                "OriginRequestPolicyList": {
                    "Items": [
                        {
                            "OriginRequestPolicy": {
                                "Id": "origin-request",
                                "OriginRequestPolicyConfig": {
                                    "Name": "Managed-AllViewerExceptHostHeader"
                                },
                            }
                        }
                    ],
                    "IsTruncated": False,
                }
            }

    cloudfront = DummyCloudFront()

    cache_policy_id = _find_managed_policy_id(
        cloudfront,
        policy_kind="cache",
        policy_name="Managed-CachingDisabled",
    )
    origin_request_policy_id = _find_managed_policy_id(
        cloudfront,
        policy_kind="origin_request",
        policy_name="Managed-AllViewerExceptHostHeader",
    )

    assert cache_policy_id == "cache-disabled"
    assert origin_request_policy_id == "origin-request"
    assert cloudfront.calls[0]["Type"] == "managed"
    assert cloudfront.calls[1]["Marker"] == "page-2"


def test_ensure_oac_recovers_from_existing_name_conflict() -> None:
    class DummyCloudFront:
        def __init__(self) -> None:
            self.lookups = 0

        class _Paginator:
            def __init__(self, parent: "DummyCloudFront") -> None:
                self.parent = parent

            def paginate(self, **kwargs):
                self.parent.lookups += 1
                if self.parent.lookups == 1:
                    yield {
                        "OriginAccessControlList": {
                            "Items": [],
                            "IsTruncated": False,
                        }
                    }
                    return
                yield {
                    "OriginAccessControlList": {
                        "Items": [
                            {
                                "Id": "oac-existing",
                                "Name": "codingrabbit-frontend-oac",
                            }
                        ],
                        "IsTruncated": False,
                    }
                }

        def get_paginator(self, name: str):
            assert name == "list_origin_access_controls"
            return self._Paginator(self)

        def create_origin_access_control(self, **kwargs):
            raise ClientError(
                {
                    "Error": {
                        "Code": "OriginAccessControlAlreadyExists",
                        "Message": "already exists",
                    }
                },
                "CreateOriginAccessControl",
            )

    cloudfront = DummyCloudFront()

    assert _ensure_oac(cloudfront, bucket_name="codingrabbit-frontend-123") == (
        "oac-existing"
    )
    assert cloudfront.lookups >= 2


def test_describe_config_reports_frontend_missing_values(tmp_path) -> None:
    config = load_deploy_config(_write_config(tmp_path))
    lines = describe_config(config)

    assert any("Bucket name:" in line for line in lines)
    assert any("Distribution ID:" in line for line in lines)
    assert any("Missing values:" in line for line in lines)


def test_spa_function_rewrites_directory_routes() -> None:
    code = _spa_function_code()
    assert "index.html" in code
    assert "uri.indexOf('.')" in code
