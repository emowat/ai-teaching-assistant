"""Provision the S3 + CloudFront frontend delivery stack.

This helper owns the frontend infrastructure boundary:

- create a private S3 bucket for the built Vite assets
- create or update a CloudFront distribution that serves the SPA from S3
  and routes API/admin paths to the existing `rag_eng` ALB
- publish a CloudFront Function that rewrites SPA routes to `/index.html`

The helper intentionally does not build or upload assets. That remains the job
of `deploy/publish_frontend.py`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
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

from deployment_config import DeployConfig, load_deploy_config  # noqa: E402


FRONTEND_BUCKET_PREFIX = "codingrabbit-frontend"
OAC_NAME = "codingrabbit-frontend-oac"
SPA_FUNCTION_NAME = "codingrabbit-frontend-spa-rewrite"

MANAGED_CACHE_POLICY_NAMES = {
    "cached": "Managed-CachingOptimized",
    "disabled": "Managed-CachingDisabled",
}

MANAGED_ORIGIN_REQUEST_POLICY_NAMES = {
    "all_viewer_except_host_header": "Managed-AllViewerExceptHostHeader",
}


@dataclass
class FrontendProvisionResult:
    bucket_name: str
    distribution_id: str
    distribution_domain_name: str
    oac_id: str
    function_name: str


def _session(config: DeployConfig) -> boto3.Session:
    return boto3.Session(
        profile_name=config.aws.profile,
        region_name=config.aws.region,
    )


def _account_id(config: DeployConfig) -> str:
    sts = _session(config).client("sts")
    return sts.get_caller_identity()["Account"]


def _repo_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate
    return (REPO_ROOT / candidate).resolve()


def _bucket_name(config: DeployConfig, account_id: str) -> str:
    configured = config.frontend_web.bucket_name.strip()
    if configured:
        return configured
    return f"{FRONTEND_BUCKET_PREFIX}-{account_id}-{config.aws.region}"


def _target_group_dns_name(config: DeployConfig, session: boto3.Session) -> str:
    if not config.rag_eng_ecs.target_group_arn:
        raise RuntimeError(
            "rag_eng_ecs.target_group_arn is required for frontend provisioning."
        )

    elbv2 = session.client("elbv2")
    tg = elbv2.describe_target_groups(
        TargetGroupArns=[config.rag_eng_ecs.target_group_arn]
    )["TargetGroups"][0]
    load_balancer_arns = tg.get("LoadBalancerArns", [])
    if not load_balancer_arns:
        raise RuntimeError(
            f"Target group {config.rag_eng_ecs.target_group_arn} is not attached to a load balancer."
        )
    lb = elbv2.describe_load_balancers(LoadBalancerArns=[load_balancer_arns[0]])[
        "LoadBalancers"
    ][0]
    return lb["DNSName"]


def _list_managed_policy_items(
    cloudfront,
    *,
    operation_name: str,
    response_key: str,
) -> list[dict[str, Any]]:
    """Return all managed policy summaries for a CloudFront list operation."""

    items: list[dict[str, Any]] = []
    marker: str | None = None

    while True:
        request_kwargs: dict[str, Any] = {"Type": "managed", "MaxItems": "100"}
        if marker:
            request_kwargs["Marker"] = marker

        response = getattr(cloudfront, operation_name)(**request_kwargs)
        policy_list = response[response_key]
        items.extend(policy_list.get("Items", []))

        if not policy_list.get("IsTruncated"):
            break

        next_marker = policy_list.get("NextMarker")
        if not next_marker or next_marker == marker:
            break
        marker = next_marker

    return items


def _find_managed_policy_id(
    cloudfront,
    *,
    policy_kind: str,
    policy_name: str,
) -> str:
    if policy_kind == "cache":
        for item in _list_managed_policy_items(
            cloudfront,
            operation_name="list_cache_policies",
            response_key="CachePolicyList",
        ):
            cache_policy = item.get("CachePolicy", {})
            if cache_policy.get("CachePolicyConfig", {}).get("Name") == policy_name:
                return cache_policy["Id"]
    elif policy_kind == "origin_request":
        for item in _list_managed_policy_items(
            cloudfront,
            operation_name="list_origin_request_policies",
            response_key="OriginRequestPolicyList",
        ):
            origin_request_policy = item.get("OriginRequestPolicy", {})
            if (
                origin_request_policy.get("OriginRequestPolicyConfig", {}).get("Name")
                == policy_name
            ):
                return origin_request_policy["Id"]
    raise RuntimeError(f"Unable to find managed CloudFront policy: {policy_name}")


def _find_oac_id(cloudfront, name: str) -> str | None:
    paginator = cloudfront.get_paginator("list_origin_access_controls")
    for page in paginator.paginate():
        for item in page.get("OriginAccessControlList", {}).get("Items", []):
            if item.get("Name") == name:
                return item["Id"]
    return None


def _ensure_bucket(
    s3,
    *,
    bucket_name: str,
    region: str,
) -> None:
    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in {"404", "403", "NoSuchBucket"}:
            raise
        create_kwargs: dict[str, Any] = {"Bucket": bucket_name}
        if region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**create_kwargs)

    s3.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_ownership_controls(
        Bucket=bucket_name,
        OwnershipControls={
            "Rules": [
                {
                    "ObjectOwnership": "BucketOwnerEnforced",
                }
            ]
        },
    )
    s3.put_bucket_encryption(
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "AES256",
                    }
                }
            ]
        },
    )


def _ensure_oac(cloudfront, *, bucket_name: str) -> str:
    existing_id = _find_oac_id(cloudfront, OAC_NAME)
    if existing_id:
        return existing_id

    try:
        response = cloudfront.create_origin_access_control(
            OriginAccessControlConfig={
                "Name": OAC_NAME,
                "Description": f"Origin access control for {bucket_name}",
                "SigningProtocol": "sigv4",
                "SigningBehavior": "always",
                "OriginAccessControlOriginType": "s3",
            }
        )
        return response["OriginAccessControl"]["Id"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code != "OriginAccessControlAlreadyExists":
            raise

        for _ in range(10):
            existing_id = _find_oac_id(cloudfront, OAC_NAME)
            if existing_id:
                return existing_id
            time.sleep(1)

        raise RuntimeError(
            f"Origin access control {OAC_NAME} already exists but could not be read back."
        ) from exc


def _spa_function_code() -> str:
    return (
        "function handler(event) {\n"
        "  var request = event.request;\n"
        "  var uri = request.uri;\n"
        "  if (uri === '/' || uri.indexOf('.') === -1) {\n"
        "    request.uri = '/index.html';\n"
        "  }\n"
        "  return request;\n"
        "}\n"
    )


def _ensure_spa_function(cloudfront) -> dict[str, str]:
    try:
        response = cloudfront.get_function(Name=SPA_FUNCTION_NAME)
        etag = response["ETag"]
        response = cloudfront.update_function(
            Name=SPA_FUNCTION_NAME,
            IfMatch=etag,
            FunctionConfig={
                "Comment": "Rewrite SPA routes to /index.html",
                "Runtime": "cloudfront-js-1.0",
            },
            FunctionCode=_spa_function_code(),
        )
        etag = response["ETag"]
        publish = cloudfront.publish_function(Name=SPA_FUNCTION_NAME, IfMatch=etag)
        metadata = publish["FunctionSummary"]["FunctionMetadata"]
        return {
            "name": SPA_FUNCTION_NAME,
            "arn": metadata["FunctionARN"],
        }
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code not in {"NoSuchFunctionExists", "ResourceNotFoundException"}:
            raise

    response = cloudfront.create_function(
        Name=SPA_FUNCTION_NAME,
        FunctionConfig={
            "Comment": "Rewrite SPA routes to /index.html",
            "Runtime": "cloudfront-js-1.0",
        },
        FunctionCode=_spa_function_code(),
    )
    etag = response["ETag"]
    publish = cloudfront.publish_function(Name=SPA_FUNCTION_NAME, IfMatch=etag)
    metadata = publish["FunctionSummary"]["FunctionMetadata"]
    return {
        "name": SPA_FUNCTION_NAME,
        "arn": metadata["FunctionARN"],
    }


def _cloudfront_function_association(function_arn: str) -> dict[str, Any]:
    return {
        "FunctionAssociations": {
            "Quantity": 1,
            "Items": [
                {
                    "EventType": "viewer-request",
                    "FunctionARN": function_arn,
                }
            ],
        }
    }


def _build_distribution_config(
    *,
    config: DeployConfig,
    bucket_name: str,
    account_id: str,
    alb_dns_name: str,
    oac_id: str,
    spa_function_arn: str,
    cache_disabled_id: str,
    cache_optimized_id: str,
    origin_request_policy_id: str,
) -> dict[str, Any]:
    frontend = config.frontend_web
    origins = [
        {
            "Id": "frontend-s3",
            "DomainName": f"{bucket_name}.s3.{config.aws.region}.amazonaws.com",
            "OriginAccessControlId": oac_id,
            "S3OriginConfig": {
                "OriginAccessIdentity": "",
            },
        },
        {
            "Id": "rag-eng-alb",
            "DomainName": alb_dns_name,
            "CustomOriginConfig": {
                "HTTPPort": 80,
                "HTTPSPort": 443,
                "OriginProtocolPolicy": "https-only",
                "OriginSslProtocols": {
                    "Quantity": 1,
                    "Items": ["TLSv1.2"],
                },
            },
        },
    ]

    cache_behaviors = []
    for path_pattern in frontend.cloudfront.api_path_patterns:
        cache_behaviors.append(
            {
                "PathPattern": path_pattern,
                "TargetOriginId": "rag-eng-alb",
                "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": {
                    "Quantity": 7,
                    "Items": [
                        "GET",
                        "HEAD",
                        "OPTIONS",
                        "PUT",
                        "POST",
                        "PATCH",
                        "DELETE",
                    ],
                    "CachedMethods": {
                        "Quantity": 2,
                        "Items": ["GET", "HEAD"],
                    },
                },
                "Compress": True,
                "CachePolicyId": cache_disabled_id,
                "OriginRequestPolicyId": origin_request_policy_id,
            }
        )

    cache_behaviors.insert(
        0,
        {
            "PathPattern": "/assets/*",
            "TargetOriginId": "frontend-s3",
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
                "CachedMethods": {
                    "Quantity": 2,
                    "Items": ["GET", "HEAD"],
                },
            },
            "Compress": True,
            "CachePolicyId": cache_optimized_id,
        },
    )

    distribution_config: dict[str, Any] = {
        "CallerReference": f"codingrabbit-frontend-{account_id}-{int(time.time())}",
        "Comment": frontend.cloudfront.comment,
        "Enabled": True,
        "DefaultRootObject": frontend.default_root_object,
        "PriceClass": frontend.price_class,
        "HttpVersion": "http2and3",
        "IsIPV6Enabled": True,
        "Origins": {"Quantity": len(origins), "Items": origins},
        "DefaultCacheBehavior": {
            "TargetOriginId": "frontend-s3",
            "ViewerProtocolPolicy": "redirect-to-https",
            "AllowedMethods": {
                "Quantity": 2,
                "Items": ["GET", "HEAD"],
                "CachedMethods": {
                    "Quantity": 2,
                    "Items": ["GET", "HEAD"],
                },
            },
            "Compress": True,
            "CachePolicyId": cache_disabled_id,
            **_cloudfront_function_association(spa_function_arn),
        },
        "CacheBehaviors": {
            "Quantity": len(cache_behaviors),
            "Items": cache_behaviors,
        },
        "ViewerCertificate": {
            "CloudFrontDefaultCertificate": True,
            "MinimumProtocolVersion": "TLSv1.2_2021",
        },
        "Restrictions": {
            "GeoRestriction": {
                "RestrictionType": "none",
                "Quantity": 0,
            }
        },
    }

    if frontend.cloudfront.aliases:
        if not frontend.cloudfront.certificate_arn:
            raise RuntimeError(
                "frontend_web.cloudfront.certificate_arn is required when aliases are configured."
            )
        distribution_config["Aliases"] = {
            "Quantity": len(frontend.cloudfront.aliases),
            "Items": list(frontend.cloudfront.aliases),
        }
        distribution_config["ViewerCertificate"] = {
            "ACMCertificateArn": frontend.cloudfront.certificate_arn,
            "SSLSupportMethod": "sni-only",
            "MinimumProtocolVersion": "TLSv1.2_2021",
        }

    return distribution_config


def _bucket_policy(bucket_name: str, distribution_arn: str, account_id: str) -> str:
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowCloudFrontRead",
                "Effect": "Allow",
                "Principal": {"Service": "cloudfront.amazonaws.com"},
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*",
                "Condition": {
                    "StringEquals": {
                        "AWS:SourceArn": distribution_arn,
                        "AWS:SourceAccount": account_id,
                    }
                },
            }
        ],
    }
    return json.dumps(policy, indent=2, sort_keys=True)


def _apply_bucket_policy(
    s3, *, bucket_name: str, distribution_arn: str, account_id: str
) -> None:
    s3.put_bucket_policy(
        Bucket=bucket_name,
        Policy=_bucket_policy(bucket_name, distribution_arn, account_id),
    )


def _distribution_arn(account_id: str, distribution_id: str) -> str:
    return f"arn:aws:cloudfront::{account_id}:distribution/{distribution_id}"


def _create_distribution(
    cloudfront,
    *,
    config: DeployConfig,
    bucket_name: str,
    account_id: str,
    alb_dns_name: str,
    oac_id: str,
    spa_function_arn: str,
) -> dict[str, str]:
    cache_disabled_id = _find_managed_policy_id(
        cloudfront,
        policy_kind="cache",
        policy_name=MANAGED_CACHE_POLICY_NAMES["disabled"],
    )
    cache_optimized_id = _find_managed_policy_id(
        cloudfront,
        policy_kind="cache",
        policy_name=MANAGED_CACHE_POLICY_NAMES["cached"],
    )
    origin_request_policy_id = _find_managed_policy_id(
        cloudfront,
        policy_kind="origin_request",
        policy_name=MANAGED_ORIGIN_REQUEST_POLICY_NAMES[
            "all_viewer_except_host_header"
        ],
    )

    distribution_config = _build_distribution_config(
        config=config,
        bucket_name=bucket_name,
        account_id=account_id,
        alb_dns_name=alb_dns_name,
        oac_id=oac_id,
        spa_function_arn=spa_function_arn,
        cache_disabled_id=cache_disabled_id,
        cache_optimized_id=cache_optimized_id,
        origin_request_policy_id=origin_request_policy_id,
    )
    response = cloudfront.create_distribution(DistributionConfig=distribution_config)
    distribution = response["Distribution"]
    return {
        "id": distribution["Id"],
        "domain_name": distribution["DomainName"],
        "status": distribution["Status"],
    }


def _ensure_distribution(
    cloudfront,
    *,
    config: DeployConfig,
    bucket_name: str,
    account_id: str,
    alb_dns_name: str,
    oac_id: str,
    spa_function_arn: str,
) -> dict[str, str]:
    if config.frontend_web.cloudfront.distribution_id:
        distribution_id = config.frontend_web.cloudfront.distribution_id
        current = cloudfront.get_distribution(Id=distribution_id)["Distribution"]
        return {
            "id": current["Id"],
            "domain_name": current["DomainName"],
            "status": current["Status"],
        }
    return _create_distribution(
        cloudfront,
        config=config,
        bucket_name=bucket_name,
        account_id=account_id,
        alb_dns_name=alb_dns_name,
        oac_id=oac_id,
        spa_function_arn=spa_function_arn,
    )


def _write_frontend_config_hint(bucket_name: str, distribution_id: str) -> None:
    print("\nCopy these resolved frontend values into deploy/deployment.yaml:")
    print("  frontend_web.enabled: true")
    print(f"  frontend_web.bucket_name: {bucket_name}")
    print(f"  frontend_web.cloudfront.distribution_id: {distribution_id}")


def describe_config(config: DeployConfig) -> list[str]:
    frontend = config.frontend_web
    lines = [
        "==> frontend infrastructure",
        f"    Region:             {config.aws.region}",
        f"    Profile:            {config.aws.profile or '(default credential chain)'}",
        f"    Enabled:            {frontend.enabled}",
        f"    App dir:            {_repo_path(frontend.app_dir)}",
        f"    Bucket name:        {frontend.bucket_name or '(will auto-generate)'}",
        f"    Distribution ID:    {frontend.cloudfront.distribution_id or '(missing)'}",
        f"    Target group ARN:   {config.rag_eng_ecs.target_group_arn or '(missing)'}",
        f"    API path patterns:  {frontend.cloudfront.api_path_patterns}",
        f"    SPA fallback path:  {frontend.spa_fallback_path}",
    ]
    missing = []
    if not config.rag_eng_ecs.target_group_arn:
        missing.append("RAG_ENG_ECS_TARGET_GROUP_ARN")
    if not _repo_path(frontend.app_dir).is_dir():
        missing.append("FRONTEND_APP_DIR")
    lines.append(
        "    Missing values:      " + (", ".join(missing) if missing else "(none)")
    )
    return lines


def provision_frontend(config: DeployConfig) -> FrontendProvisionResult:
    session = _session(config)
    s3 = session.client("s3")
    cloudfront = session.client("cloudfront")

    account_id = _account_id(config)
    bucket_name = _bucket_name(config, account_id)
    alb_dns_name = _target_group_dns_name(config, session)

    print(f"[1/3] Ensuring S3 bucket {bucket_name}")
    _ensure_bucket(s3, bucket_name=bucket_name, region=config.aws.region)

    print("[2/3] Ensuring CloudFront origin access control and SPA function")
    oac_id = _ensure_oac(cloudfront, bucket_name=bucket_name)
    spa_function = _ensure_spa_function(cloudfront)

    print("[3/3] Creating or reading CloudFront distribution")
    dist = _ensure_distribution(
        cloudfront,
        config=config,
        bucket_name=bucket_name,
        account_id=account_id,
        alb_dns_name=alb_dns_name,
        oac_id=oac_id,
        spa_function_arn=spa_function["arn"],
    )
    distribution_arn = _distribution_arn(account_id, dist["id"])
    _apply_bucket_policy(
        s3,
        bucket_name=bucket_name,
        distribution_arn=distribution_arn,
        account_id=account_id,
    )

    return FrontendProvisionResult(
        bucket_name=bucket_name,
        distribution_id=dist["id"],
        distribution_domain_name=dist["domain_name"],
        oac_id=oac_id,
        function_name=spa_function["name"],
    )


def _print_summary(result: FrontendProvisionResult) -> None:
    print("\nFrontend provisioning summary")
    print(
        json.dumps(
            {
                "bucket_name": result.bucket_name,
                "distribution_id": result.distribution_id,
                "distribution_domain_name": result.distribution_domain_name,
                "origin_access_control_id": result.oac_id,
                "function_name": result.function_name,
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision frontend infra")
    parser.add_argument(
        "command",
        choices=["describe", "apply"],
        help="describe | apply",
    )
    args = parser.parse_args()

    config = load_deploy_config()

    if args.command == "describe":
        for line in describe_config(config):
            print(line)
        return

    result = provision_frontend(config)
    _print_summary(result)
    _write_frontend_config_hint(result.bucket_name, result.distribution_id)


if __name__ == "__main__":
    main()
