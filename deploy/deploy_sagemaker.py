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

_DEPLOY_DIR = Path(__file__).resolve().parent
if str(_DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(_DEPLOY_DIR))

from deployment_config import DeployConfig, load_deploy_config


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
    async_output = sm_cfg.async_output_uri(cfg.aws.region)

    print(f"Config file:      {cfg.config_path}")
    print(f"Region:           {cfg.aws.region}")
    print(f"Role ARN:         {role}")
    print(f"DLC image:        {image_uri}")
    print(f"Model data (S3):  {model_data_uri}")
    print(f"Instance type:    {sm_cfg.instance_type}")
    print(f"Endpoint name:    {sm_cfg.endpoint_name}\n")

    print(f"[1/3] Creating model: {model_name}")
    try:
        sm.create_model(
            ModelName=model_name,
            PrimaryContainer={
                "Image": image_uri,
                "ModelDataUrl": model_data_uri,
                "Environment": sm_cfg.container.as_env_dict(),
            },
            ExecutionRoleArn=role,
        )
        print("      Created.")
    except sm.exceptions.ClientError as exc:
        if "Cannot create already existing model" in str(exc):
            print("      Already exists, reusing.")
        else:
            raise

    ai = sm_cfg.async_inference
    print(f"\n[2/3] Creating endpoint config: {config_name}")
    try:
        sm.create_endpoint_config(
            EndpointConfigName=config_name,
            ProductionVariants=[
                {
                    "VariantName": "AllTraffic",
                    "ModelName": model_name,
                    "InstanceType": sm_cfg.instance_type,
                    "InitialInstanceCount": sm_cfg.initial_instance_count,
                }
            ],
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
    except sm.exceptions.ClientError as exc:
        if "Cannot create already existing" in str(exc):
            print("      Already exists, reusing.")
        else:
            raise

    print(f"\n[3/3] Deploying endpoint: {sm_cfg.endpoint_name}")
    print("      This may take 5–10 minutes for the GPU instance to warm up...\n")
    try:
        sm.create_endpoint(
            EndpointName=sm_cfg.endpoint_name,
            EndpointConfigName=config_name,
        )
    except sm.exceptions.ClientError as exc:
        if "Cannot create already existing" in str(exc):
            print("      Endpoint already exists. Run 'status' to check it.")
            return
        raise

    waiter = sm.get_waiter("endpoint_in_service")
    waiter.wait(
        EndpointName=sm_cfg.endpoint_name,
        WaiterConfig={
            "Delay": ai.deploy_wait_delay_seconds,
            "MaxAttempts": ai.deploy_wait_max_attempts,
        },
    )

    print(f"\nEndpoint '{sm_cfg.endpoint_name}' is InService.")
    print("\nNext steps — add to .env and restart rag_eng:")
    print(f"  USE_SAGEMAKER=true")
    print(f"  SAGEMAKER_ENDPOINT={sm_cfg.endpoint_name}")
    print(f"  MODEL_FAMILY={cfg.rag_eng.model_family}")
    print(f"  S3_DATA_BUCKET={cfg.aws.s3_bucket}")
    print(f"\nTo test: python deploy/deploy_sagemaker.py invoke")


def invoke(cfg: DeployConfig, prompt: str) -> None:
    """Send a test request through the async pipeline (S3 in → S3 poll → print)."""
    session = _get_session(cfg)
    sm_runtime = session.client("sagemaker-runtime")
    s3 = session.client("s3")

    smoke = cfg.inference_smoke_test
    formatted = _format_qwen_prompt(cfg, prompt)
    payload = {
        "inputs": formatted,
        "parameters": {
            "max_new_tokens": smoke.max_new_tokens,
            "temperature": smoke.temperature,
            "top_p": smoke.top_p,
        },
    }

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
            if isinstance(result, list) and result and "generated_text" in result[0]:
                print(result[0]["generated_text"])
            else:
                print(json.dumps(result, indent=2))
            return
        except s3.exceptions.NoSuchKey:
            print(".", end="", flush=True)
            time.sleep(ai.invoke_poll_interval_seconds)

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
            print("\nEndpoint is ready. Set USE_SAGEMAKER=true in .env to route traffic here.")
    except sm.exceptions.ClientError:
        print(f"Endpoint '{endpoint}' not found.")


def cleanup(cfg: DeployConfig) -> None:
    """Delete endpoint, config, and model — stops all billing for this endpoint."""
    session = _get_session(cfg)
    sm = session.client("sagemaker")
    endpoint = cfg.sagemaker.endpoint_name

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
