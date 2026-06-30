"""
Deploy the fine-tuned Qwen model to a SageMaker Asynchronous Inference endpoint.

Configuration: deploy/deployment.yaml (see deployment_config.py)

Reference: https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

_DEPLOY_DIR = Path(__file__).resolve().parent
if str(_DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOY_DIR))

from deployment_config import DeployConfig, load_deploy_config  # noqa: E402
from sagemaker_io import build_async_payload, parse_async_response  # noqa: E402


def _get_session(cfg: DeployConfig) -> boto3.Session:
    return boto3.Session(profile_name=cfg.aws.profile, region_name=cfg.aws.region)


def _get_role(session: boto3.Session, cfg: DeployConfig, role_arn: str | None) -> str:
    if role_arn:
        return role_arn
    if cfg.sagemaker.execution_role_arn:
        return cfg.sagemaker.execution_role_arn
    try:
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        arn = identity["Arn"]
        if ":assumed-role/" in arn:
            role_name = arn.split(":assumed-role/")[1].split("/")[0]
            if role_name.startswith("AWSReservedSSO_"):
                print("ERROR: Cannot use your SSO login role as the SageMaker execution role.")
                print("SSO roles are not assumable by sagemaker.amazonaws.com.")
                print("Set sagemaker.execution_role_arn in deployment.yaml, e.g.:")
                print("  arn:aws:iam::ACCOUNT:role/service-role/SageMaker-ExecutionRole-...")
                sys.exit(1)
            iam = session.client("iam")
            return iam.get_role(RoleName=role_name)["Role"]["Arn"]
        if ":role/" in arn:
            return arn
    except Exception:
        pass
    print("ERROR: Cannot resolve SageMaker execution role ARN.")
    print("Set sagemaker.execution_role_arn in deployment.yaml or pass --role-arn.")
    sys.exit(1)


def _format_qwen_prompt(cfg: DeployConfig, user_prompt: str) -> str:
    """Match Qwen chat template used in rag_eng/inference.py."""
    system = cfg.inference_smoke_test.system_message
    eot = "<|im_end|>"
    return (
        f"<|im_start|>system\n{system}{eot}\n"
        f"<|im_start|>user\n{user_prompt}{eot}\n"
        f"<|im_start|>assistant\n"
    )


def _is_not_found(exc: Exception) -> bool:
    if not isinstance(exc, ClientError):
        return False
    code = exc.response.get("Error", {}).get("Code", "")
    return code in {
        "ValidationException",
        "ResourceNotFound",
        "ObjectNotFoundException",
    }


def _describe_model(sm, model_name: str) -> dict | None:
    try:
        return sm.describe_model(ModelName=model_name)
    except Exception as exc:
        if _is_not_found(exc):
            return None
        raise


def _describe_endpoint_config(sm, config_name: str) -> dict | None:
    try:
        return sm.describe_endpoint_config(EndpointConfigName=config_name)
    except Exception as exc:
        if _is_not_found(exc):
            return None
        raise


def _model_matches(
    desc: dict | None,
    *,
    image_uri: str,
    model_data_uri: str,
    env: dict[str, str],
) -> bool:
    if desc is None:
        return False
    container = desc["PrimaryContainer"]
    return (
        container.get("Image") == image_uri
        and container.get("ModelDataUrl") == model_data_uri
        and container.get("Environment", {}) == env
    )


def _config_matches(
    desc: dict | None,
    *,
    sm_cfg,
    model_name: str,
    async_output: str,
) -> bool:
    if desc is None:
        return False
    variant = desc["ProductionVariants"][0]
    if variant["InstanceType"] != sm_cfg.instance_type:
        return False
    if variant["ModelName"] != model_name:
        return False
    if sm_cfg.inference_ami_version:
        if variant.get("InferenceAmiVersion") != sm_cfg.inference_ami_version:
            return False
    output_path = (
        desc.get("AsyncInferenceConfig", {})
        .get("OutputConfig", {})
        .get("S3OutputPath", "")
    )
    return output_path.rstrip("/") == async_output.rstrip("/")


def _delete_endpoint_if_present(sm, endpoint_name: str) -> None:
    try:
        sm.describe_endpoint(EndpointName=endpoint_name)
    except Exception as exc:
        if _is_not_found(exc):
            return
        raise
    print(f"      Deleting endpoint: {endpoint_name}")
    sm.delete_endpoint(EndpointName=endpoint_name)
    waiter = sm.get_waiter("endpoint_deleted")
    waiter.wait(EndpointName=endpoint_name)


def _reconcile_stale_resources(
    session: boto3.Session,
    sm,
    cfg: DeployConfig,
    *,
    model_name: str,
    config_name: str,
    image_uri: str,
    async_output: str,
) -> tuple[bool, bool]:
    """Drop model/config/endpoint that no longer match deployment.yaml."""
    env = cfg.sagemaker.container.as_env_dict()
    model_data_uri = cfg.model_data_uri
    endpoint_name = cfg.sagemaker.endpoint_name

    existing_model = _describe_model(sm, model_name)
    existing_config = _describe_endpoint_config(sm, config_name)

    model_ok = _model_matches(
        existing_model,
        image_uri=image_uri,
        model_data_uri=model_data_uri,
        env=env,
    )
    config_ok = _config_matches(
        existing_config,
        sm_cfg=cfg.sagemaker,
        model_name=model_name,
        async_output=async_output,
    )

    if model_ok and config_ok:
        return True, True

    print("\nDeploy settings changed — removing stale SageMaker resources.")
    if existing_config and not config_ok:
        old_type = existing_config["ProductionVariants"][0]["InstanceType"]
        print(f"  Instance type: {old_type} → {cfg.sagemaker.instance_type}")
    if existing_model and not model_ok:
        old_image = existing_model["PrimaryContainer"].get("Image", "unknown")
        print(f"  Container image changed (was: {old_image})")

    _teardown_autoscaling(session, cfg)
    _delete_endpoint_if_present(sm, endpoint_name)

    if existing_config and not config_ok:
        print(f"      Deleting endpoint config: {config_name}")
        sm.delete_endpoint_config(EndpointConfigName=config_name)
        config_ok = False

    if existing_model and not model_ok:
        print(f"      Deleting model: {model_name}")
        sm.delete_model(ModelName=model_name)
        model_ok = False

    print()
    return model_ok, config_ok


def _setup_autoscaling(session: boto3.Session, cfg: DeployConfig) -> None:
    """Register scale-to-zero auto scaling for the async endpoint variant."""
    asc = cfg.sagemaker.autoscaling
    if not asc.enabled:
        print("\nAuto scaling disabled in deployment.yaml (instances stay at initial count).")
        return

    endpoint = cfg.sagemaker.endpoint_name
    resource_id = cfg.sagemaker.autoscaling_resource_id()
    autos = session.client("application-autoscaling")
    cw = session.client("cloudwatch")

    print(f"\n[4/4] Configuring auto scaling ({asc.min_capacity}–{asc.max_capacity} instances)")
    autos.register_scalable_target(
        ServiceNamespace="sagemaker",
        ResourceId=resource_id,
        ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        MinCapacity=asc.min_capacity,
        MaxCapacity=asc.max_capacity,
    )

    autos.put_scaling_policy(
        PolicyName=f"{endpoint}-TargetTracking-Backlog",
        PolicyType="TargetTrackingScaling",
        ServiceNamespace="sagemaker",
        ResourceId=resource_id,
        ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        TargetTrackingScalingPolicyConfiguration={
            "TargetValue": asc.target_backlog_per_instance,
            "CustomizedMetricSpecification": {
                "MetricName": "ApproximateBacklogSizePerInstance",
                "Namespace": "AWS/SageMaker",
                "Dimensions": [{"Name": "EndpointName", "Value": endpoint}],
                "Statistic": "Average",
            },
            "ScaleInCooldown": asc.scale_in_cooldown_seconds,
            "ScaleOutCooldown": asc.scale_out_cooldown_seconds,
        },
    )

    step_response = autos.put_scaling_policy(
        PolicyName=f"{endpoint}-HasBacklogWithoutCapacity",
        PolicyType="StepScaling",
        ServiceNamespace="sagemaker",
        ResourceId=resource_id,
        ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        StepScalingPolicyConfiguration={
            "AdjustmentType": "ChangeInCapacity",
            "MetricAggregationType": "Average",
            "Cooldown": asc.scale_from_zero_cooldown_seconds,
            "StepAdjustments": [
                {"MetricIntervalLowerBound": 0, "ScalingAdjustment": 1},
            ],
        },
    )

    alarm_name = f"{endpoint}-HasBacklogWithoutCapacity"
    alarm = asc.scale_from_zero_alarm
    cw.put_metric_alarm(
        AlarmName=alarm_name,
        MetricName="HasBacklogWithoutCapacity",
        Namespace="AWS/SageMaker",
        Statistic="Average",
        EvaluationPeriods=alarm.evaluation_periods,
        DatapointsToAlarm=alarm.datapoints_to_alarm,
        Threshold=1,
        ComparisonOperator="GreaterThanOrEqualToThreshold",
        TreatMissingData="missing",
        Dimensions=[{"Name": "EndpointName", "Value": endpoint}],
        Period=alarm.period_seconds,
        AlarmActions=[step_response["PolicyARN"]],
    )
    worst_case_wake_sec = alarm.period_seconds * alarm.evaluation_periods
    print(
        f"      Enabled — scales to {asc.min_capacity} when idle; "
        f"queued requests trigger scale-out "
        f"(HasBacklogWithoutCapacity alarm: up to ~{worst_case_wake_sec}s)."
    )


def _teardown_autoscaling(session: boto3.Session, cfg: DeployConfig) -> None:
    """Remove auto scaling policies and CloudWatch alarm for the endpoint variant."""
    asc = cfg.sagemaker.autoscaling
    if not asc.enabled:
        return

    endpoint = cfg.sagemaker.endpoint_name
    resource_id = cfg.sagemaker.autoscaling_resource_id()
    autos = session.client("application-autoscaling")
    cw = session.client("cloudwatch")
    alarm_name = f"{endpoint}-HasBacklogWithoutCapacity"

    print(f"Removing auto scaling for: {endpoint}")
    try:
        cw.delete_alarms(AlarmNames=[alarm_name])
    except ClientError:
        pass

    try:
        autos.deregister_scalable_target(
            ServiceNamespace="sagemaker",
            ResourceId=resource_id,
            ScalableDimension="sagemaker:variant:DesiredInstanceCount",
        )
    except ClientError as exc:
        if not _is_not_found(exc):
            raise


def deploy(cfg: DeployConfig, role_arn: str | None) -> None:
    """Create model, endpoint config, and async endpoint."""
    session = _get_session(cfg)
    sm = session.client("sagemaker")
    role = _get_role(session, cfg, role_arn)

    sm_cfg = cfg.sagemaker
    image_uri = sm_cfg.dlc.image_uri(cfg.aws.region)
    model_name = sm_cfg.model_name()
    config_name = sm_cfg.config_name()
    model_data_uri = cfg.model_data_uri
    async_output = sm_cfg.async_output_uri(cfg.aws.s3_bucket)

    print(f"Config file:      {cfg.config_path}")
    print(f"Region:           {cfg.aws.region}")
    print(f"Role ARN:         {role}")
    print(f"DLC image:        {image_uri}")
    print(f"Model data (S3):  {model_data_uri}")
    print(f"Async output:     {async_output}")
    print(f"Instance type:    {sm_cfg.instance_type}")
    print(f"Inference:        {sm_cfg.container.inference_backend}")
    print(f"Endpoint name:    {sm_cfg.endpoint_name}\n")

    container_env = sm_cfg.container.as_env_dict()
    model_ok, config_ok = _reconcile_stale_resources(
        session,
        sm,
        cfg,
        model_name=model_name,
        config_name=config_name,
        image_uri=image_uri,
        async_output=async_output,
    )

    print(f"[1/4] Creating model: {model_name}")
    if model_ok:
        print("      Up to date, reusing.")
    else:
        sm.create_model(
            ModelName=model_name,
            PrimaryContainer={
                "Image": image_uri,
                "ModelDataUrl": model_data_uri,
                "Environment": container_env,
            },
            ExecutionRoleArn=role,
        )
        print("      Created.")

    ai = sm_cfg.async_inference
    print(f"\n[2/4] Creating endpoint config: {config_name}")
    if config_ok:
        print("      Up to date, reusing.")
    else:
        production_variant: dict = {
            "VariantName": "AllTraffic",
            "ModelName": model_name,
            "InstanceType": sm_cfg.instance_type,
            "InitialInstanceCount": sm_cfg.initial_instance_count,
        }
        if sm_cfg.inference_ami_version:
            production_variant["InferenceAmiVersion"] = sm_cfg.inference_ami_version
        sm.create_endpoint_config(
            EndpointConfigName=config_name,
            ProductionVariants=[production_variant],
            AsyncInferenceConfig={
                "OutputConfig": {"S3OutputPath": async_output},
                "ClientConfig": {
                    "MaxConcurrentInvocationsPerInstance": (
                        ai.max_concurrent_invocations_per_instance
                    ),
                },
            },
        )
        print("      Created.")

    print(f"\n[3/4] Deploying endpoint: {sm_cfg.endpoint_name}")
    print("      vLLM + 4-bit load can take 15–30 minutes on first deploy...\n")
    endpoint_existed = False
    try:
        sm.create_endpoint(
            EndpointName=sm_cfg.endpoint_name,
            EndpointConfigName=config_name,
        )
    except sm.exceptions.ClientError as exc:
        if "Cannot create already existing" in str(exc):
            print("      Endpoint already exists.")
            endpoint_existed = True
        else:
            raise

    if not endpoint_existed:
        waiter = sm.get_waiter("endpoint_in_service")
        try:
            waiter.wait(
                EndpointName=sm_cfg.endpoint_name,
                WaiterConfig={
                    "Delay": ai.deploy_wait_delay_seconds,
                    "MaxAttempts": ai.deploy_wait_max_attempts,
                },
            )
        except Exception as exc:
            desc = sm.describe_endpoint(EndpointName=sm_cfg.endpoint_name)
            state = desc.get("EndpointStatus", "unknown")
            if state != "InService":
                reason = desc.get("FailureReason", "")
                print(f"\nDeploy waiter stopped: {exc}")
                print(f"Endpoint status: {state}")
                if reason:
                    print(f"Failure reason:  {reason}")
                print(
                    "Check status with: "
                    "./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh status"
                )
                sys.exit(1)
            print("\nWaiter timed out, but endpoint is InService.")

    _setup_autoscaling(session, cfg)

    print(f"\nEndpoint '{sm_cfg.endpoint_name}' is InService.")
    print("\nNext steps — add to .env and restart rag_eng:")
    print("  USE_SAGEMAKER=true")
    print(f"  SAGEMAKER_ENDPOINT={sm_cfg.endpoint_name}")
    print(f"  MODEL_FAMILY={cfg.rag_eng.model_family}")
    print(f"  SAGEMAKER_INFERENCE_BACKEND={cfg.rag_eng.inference_backend}")
    print(f"  S3_DATA_BUCKET={cfg.aws.s3_bucket}")
    if cfg.sagemaker.autoscaling.enabled:
        print(
            f"\nAuto scaling: {cfg.sagemaker.autoscaling.min_capacity}–"
            f"{cfg.sagemaker.autoscaling.max_capacity} instances "
            "(0 when idle = no GPU charges)."
        )
    print("\nTo test: python deploy/deploy_sagemaker.py invoke")


def invoke(cfg: DeployConfig, prompt: str) -> None:
    """Send a test request through the async pipeline (S3 in → S3 poll → print)."""
    session = _get_session(cfg)
    sm_runtime = session.client("sagemaker-runtime")
    s3 = session.client("s3")

    smoke = cfg.inference_smoke_test
    backend = cfg.sagemaker.container.inference_backend
    messages = [
        {"role": "system", "content": smoke.system_message},
        {"role": "user", "content": prompt},
    ]
    formatted = _format_qwen_prompt(cfg, prompt) if backend == "huggingface" else None
    payload = build_async_payload(
        backend,
        messages,
        max_tokens=smoke.max_new_tokens,
        temperature=smoke.temperature,
        top_p=smoke.top_p,
        formatted_prompt=formatted,
    )

    request_id = str(uuid.uuid4())
    input_prefix = cfg.sagemaker.runtime_io.input_s3_prefix.rstrip("/")
    input_key = f"{input_prefix}/{request_id}.json"
    bucket = cfg.aws.s3_bucket
    endpoint = cfg.sagemaker.endpoint_name

    print(f"Uploading request to s3://{bucket}/{input_key}")
    s3.put_object(Bucket=bucket, Key=input_key, Body=json.dumps(payload))

    print(f"Invoking async endpoint: {endpoint}")
    print("(First request may have a 30–90 second cold start)\n")

    response = sm_runtime.invoke_endpoint_async(
        EndpointName=endpoint,
        InputLocation=f"s3://{bucket}/{input_key}",
        ContentType="application/json",
    )
    output_uri = response["OutputLocation"]
    output_key = output_uri.replace(f"s3://{bucket}/", "")

    ai = cfg.sagemaker.async_inference
    timeout_sec = ai.invoke_poll_interval_seconds * ai.invoke_poll_max_attempts
    print(f"Output will appear at: {output_uri}")
    print(f"Polling for result (timeout {timeout_sec}s)", end="", flush=True)

    for _ in range(ai.invoke_poll_max_attempts):
        try:
            obj = s3.get_object(Bucket=bucket, Key=output_key)
            result = json.loads(obj["Body"].read().decode())
            print("\n\n--- Response ---")
            print(parse_async_response(backend, result))
            return
        except s3.exceptions.NoSuchKey:
            print(".", end="", flush=True)
            time.sleep(ai.invoke_poll_interval_seconds)
        except ValueError as exc:
            print(f"\nERROR: {exc}")
            print(json.dumps(result, indent=2))
            return

    print(f"\nERROR: Timed out after {timeout_sec}s waiting for result.")
    print(f"Check CloudWatch logs for endpoint: {endpoint}")


def status(cfg: DeployConfig) -> None:
    session = _get_session(cfg)
    sm = session.client("sagemaker")
    endpoint = cfg.sagemaker.endpoint_name
    try:
        desc = sm.describe_endpoint(EndpointName=endpoint)
        state = desc["EndpointStatus"]
        print(f"Config:    {cfg.config_path}")
        print(f"Endpoint:  {endpoint}")
        print(f"Status:    {state}")
        print(f"Created:   {desc['CreationTime']}")
        print(f"Updated:   {desc['LastModifiedTime']}")
        if state == "InService":
            pending = desc.get("PendingDeploymentSummary") or {}
            variants = pending.get("ProductionVariants") or []
            if variants:
                current = variants[0].get("CurrentInstanceCount")
                desired = variants[0].get("DesiredInstanceCount")
                if current is not None:
                    print(f"Instances: {current} running (desired: {desired})")
            asc = cfg.sagemaker.autoscaling
            if asc.enabled:
                print(
                    f"Auto scaling: {asc.min_capacity}–{asc.max_capacity} "
                    "(0 when idle = no GPU cost)"
                )
            print("\nEndpoint is ready. Set USE_SAGEMAKER=true in .env to route traffic here.")
    except sm.exceptions.ClientError:
        print(f"Endpoint '{endpoint}' not found.")


def cleanup(cfg: DeployConfig) -> None:
    """Delete endpoint, config, and model — stops all billing for this endpoint."""
    session = _get_session(cfg)
    sm = session.client("sagemaker")
    endpoint = cfg.sagemaker.endpoint_name

    _teardown_autoscaling(session, cfg)

    try:
        desc = sm.describe_endpoint(EndpointName=endpoint)
        config_name = desc["EndpointConfigName"]
    except sm.exceptions.ClientError:
        print(f"Endpoint '{endpoint}' not found.")
        return

    config_desc = sm.describe_endpoint_config(EndpointConfigName=config_name)
    model_name = config_desc["ProductionVariants"][0]["ModelName"]

    print(f"Deleting endpoint:        {endpoint}")
    sm.delete_endpoint(EndpointName=endpoint)

    print(f"Deleting endpoint config: {config_name}")
    sm.delete_endpoint_config(EndpointConfigName=config_name)

    print(f"Deleting model:           {model_name}")
    sm.delete_model(ModelName=model_name)

    print("\nCleanup complete. No more GPU charges for this endpoint.")
    print(f"Note: S3 model artifact at {cfg.model_data_uri} was NOT deleted.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy Qwen fine-tune to SageMaker Async Inference"
    )
    parser.add_argument(
        "action",
        choices=["deploy", "invoke", "status", "cleanup"],
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to deployment.yaml (default: deploy/deployment.yaml or DEPLOY_CONFIG)",
    )
    parser.add_argument("--role-arn", default=None, help="SageMaker execution role ARN")
    parser.add_argument(
        "--prompt",
        default=None,
        help="Test prompt for invoke (default from deployment.yaml)",
    )
    args = parser.parse_args()

    cfg = load_deploy_config(args.config)
    prompt = args.prompt or cfg.inference_smoke_test.default_prompt

    if args.action == "deploy":
        deploy(cfg, args.role_arn)
    elif args.action == "invoke":
        invoke(cfg, prompt)
    elif args.action == "status":
        status(cfg)
    elif args.action == "cleanup":
        cleanup(cfg)


if __name__ == "__main__":
    main()
