"""
Deploy the fine-tuned Qwen model to a SageMaker Asynchronous Inference endpoint.

Asynchronous Inference is the correct endpoint type for Qwen 14B because:
  - Large payload support (up to 1 GB)
  - Long inference times (up to 1 hour)
  - Scales to ZERO instances when idle — no cost between student sessions
  - Results written to S3; backend polls and streams back to the VS Code extension

Reference: https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html

This script assumes the model has already been uploaded to S3 by upload_model.py.
The endpoint name created here must match SAGEMAKER_ENDPOINT in rag_eng/.env.

Usage:
    python deploy/deploy_sagemaker.py deploy
    python deploy/deploy_sagemaker.py invoke --prompt "Why does my pointer segfault?"
    python deploy/deploy_sagemaker.py status
    python deploy/deploy_sagemaker.py cleanup

Prerequisites:
    pip install boto3
    AWS credentials configured with SageMaker + S3 + IAM permissions
    Model already uploaded: python deploy/upload_model.py upload
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid

import boto3


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Must match SAGEMAKER_ENDPOINT in rag_eng/.env / environment
ENDPOINT_NAME = os.getenv("SAGEMAKER_ENDPOINT", "codingrabbit-qwen-async")

S3_BUCKET = os.getenv("S3_DATA_BUCKET", "codingrabbit-data-dev")

# S3 URI of the packaged model (output of upload_model.py)
MODEL_DATA_URI = os.getenv(
    "MODEL_DATA_URI",
    f"s3://{S3_BUCKET}/models/qwen-finetuned/model.tar.gz",
)

# S3 prefix where SageMaker writes async inference results
# Must match the path that rag_eng/inference.py polls
ASYNC_OUTPUT_PREFIX = f"s3://{S3_BUCKET}/async-inference/output/"

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_PROFILE = os.getenv("AWS_PROFILE") or None

# ---------------------------------------------------------------------------
# Instance selection guide
#
# Qwen2-14B in bf16/fp16 ≈ 28 GB VRAM  →  ml.g5.12xlarge (4×A10G, 96GB)
# Qwen2-14B in 4-bit     ≈  8 GB VRAM  →  ml.g5.2xlarge  (1×A10G, 24GB)
# Qwen2-7B  in bf16      ≈ 14 GB VRAM  →  ml.g5.2xlarge  (1×A10G, 24GB)
#
# Start with g5.2xlarge if the model is quantized/QLoRA-merged at 4-bit.
# Scale up to g5.12xlarge if you see OOM errors.
# ---------------------------------------------------------------------------
INSTANCE_TYPE = os.getenv("SAGEMAKER_INSTANCE_TYPE", "ml.g5.2xlarge")
INITIAL_INSTANCE_COUNT = 1

# ---------------------------------------------------------------------------
# DLC image — HuggingFace PyTorch GPU
#
# Tag format: {pytorch}-transformers{transformers}-gpu-py{py}-cu{cuda}-ubuntu{os}
# Qwen2 requires transformers >= 4.40.
#
# Verify available tags at:
#   https://aws.github.io/deep-learning-containers/reference/available_images/
# ---------------------------------------------------------------------------
DLC_ACCOUNT_ID = "763104351884"
DLC_REPOSITORY = "huggingface-pytorch-inference"
DLC_TAG = "2.3.0-transformers4.40.1-gpu-py311-cu121-ubuntu20.04"

# ---------------------------------------------------------------------------
# Container environment variables
#
# HF_TASK is required.  Do NOT set HF_MODEL_ID — the model is loaded from
# the S3 model.tar.gz that SageMaker extracts to /opt/ml/model/.
#
# SAGEMAKER_MODEL_SERVER_WORKERS: 1 worker per GPU (adjust for multi-GPU)
# ---------------------------------------------------------------------------
CONTAINER_ENV = {
    "HF_TASK": "text-generation",
    "SAGEMAKER_MODEL_SERVER_WORKERS": "1",
    # Uncomment to enable bitsandbytes 4-bit loading (saves VRAM):
    # "BITSANDBYTES_NOWELCOME": "1",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session() -> boto3.Session:
    return boto3.Session(profile_name=AWS_PROFILE, region_name=AWS_REGION)


def _get_role(session: boto3.Session, role_arn: str | None) -> str:
    if role_arn:
        return role_arn
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
    print("Provide it via --role-arn or set DEFAULT_EXECUTION_ROLE_ARN.")
    sys.exit(1)


def _dlc_image_uri() -> str:
    return f"{DLC_ACCOUNT_ID}.dkr.ecr.{AWS_REGION}.amazonaws.com/{DLC_REPOSITORY}:{DLC_TAG}"


def _model_name() -> str:
    return f"{ENDPOINT_NAME}-model"


def _config_name() -> str:
    return f"{ENDPOINT_NAME}-config"


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------

def deploy(role_arn: str | None) -> None:
    """Create model, endpoint config, and async endpoint."""
    session = _get_session()
    sm = session.client("sagemaker")
    role = _get_role(session, role_arn)

    image_uri = _dlc_image_uri()
    model_name = _model_name()
    config_name = _config_name()

    print(f"Region:           {AWS_REGION}")
    print(f"Role ARN:         {role}")
    print(f"DLC image:        {image_uri}")
    print(f"Model data (S3):  {MODEL_DATA_URI}")
    print(f"Instance type:    {INSTANCE_TYPE}")
    print(f"Endpoint name:    {ENDPOINT_NAME}\n")

    # Step 1 — Create SageMaker Model
    print(f"[1/3] Creating model: {model_name}")
    try:
        sm.create_model(
            ModelName=model_name,
            PrimaryContainer={
                "Image": image_uri,
                "ModelDataUrl": MODEL_DATA_URI,
                "Environment": CONTAINER_ENV,
            },
            ExecutionRoleArn=role,
        )
        print("      Created.")
    except sm.exceptions.ClientError as exc:
        if "Cannot create already existing model" in str(exc):
            print("      Already exists, reusing.")
        else:
            raise

    # Step 2 — Create Endpoint Config with AsyncInferenceConfig
    print(f"\n[2/3] Creating endpoint config: {config_name}")
    try:
        sm.create_endpoint_config(
            EndpointConfigName=config_name,
            ProductionVariants=[
                {
                    "VariantName": "AllTraffic",
                    "ModelName": model_name,
                    "InstanceType": INSTANCE_TYPE,
                    "InitialInstanceCount": INITIAL_INSTANCE_COUNT,
                }
            ],
            AsyncInferenceConfig={
                "OutputConfig": {
                    "S3OutputPath": ASYNC_OUTPUT_PREFIX,
                    # Optional: SNS notifications on success/failure
                    # "NotificationConfig": {
                    #     "SuccessTopic": "arn:aws:sns:...:codingrabbit-inference-success",
                    #     "ErrorTopic": "arn:aws:sns:...:codingrabbit-inference-error",
                    # },
                },
                "ClientConfig": {
                    # Max items queued before returning 429 (adjust for expected concurrency)
                    "MaxConcurrentInvocationsPerInstance": 4,
                },
            },
        )
        print("      Created.")
    except sm.exceptions.ClientError as exc:
        if "Cannot create already existing" in str(exc):
            print("      Already exists, reusing.")
        else:
            raise

    # Step 3 — Create Endpoint
    print(f"\n[3/3] Deploying endpoint: {ENDPOINT_NAME}")
    print("      This may take 5–10 minutes for the GPU instance to warm up...\n")
    try:
        sm.create_endpoint(
            EndpointName=ENDPOINT_NAME,
            EndpointConfigName=config_name,
        )
    except sm.exceptions.ClientError as exc:
        if "Cannot create already existing" in str(exc):
            print(f"      Endpoint already exists. Run 'status' to check it.")
            return
        else:
            raise

    waiter = sm.get_waiter("endpoint_in_service")
    waiter.wait(EndpointName=ENDPOINT_NAME, WaiterConfig={"Delay": 30, "MaxAttempts": 40})

    print(f"\nEndpoint '{ENDPOINT_NAME}' is InService.")
    print("\nNext steps:")
    print(f"  1. Set SAGEMAKER_ENDPOINT={ENDPOINT_NAME} in your .env")
    print(f"  2. Set USE_SAGEMAKER=true")
    print(f"  3. Set MODEL_FAMILY=qwen")
    print(f"  4. Run:  uv run uvicorn rag_eng.main:app --port 8001")
    print(f"\nTo test: python deploy/deploy_sagemaker.py invoke")


# ---------------------------------------------------------------------------
# Invoke (smoke test)
# ---------------------------------------------------------------------------

def invoke(prompt: str) -> None:
    """Send a test request through the async pipeline (S3 in → S3 poll → print)."""
    session = _get_session()
    sm_runtime = session.client("sagemaker-runtime")
    s3 = session.client("s3")

    # Format with Qwen chat template
    formatted = (
        f"<|im_start|>system\n"
        f"You are CodingRabbit, a Socratic C++ teaching assistant.<|im_end|>\n"
        f"<|im_start|>user\n{prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    payload = {
        "inputs": formatted,
        "parameters": {"max_new_tokens": 512, "temperature": 0.7, "top_p": 0.9},
    }

    request_id = str(uuid.uuid4())
    input_key = f"temp/sagemaker_inputs/{request_id}.json"

    print(f"Uploading request to s3://{S3_BUCKET}/{input_key}")
    s3.put_object(Bucket=S3_BUCKET, Key=input_key, Body=json.dumps(payload))

    print(f"Invoking async endpoint: {ENDPOINT_NAME}")
    print("(First request may have a 30–90 second cold start)\n")

    response = sm_runtime.invoke_endpoint_async(
        EndpointName=ENDPOINT_NAME,
        InputLocation=f"s3://{S3_BUCKET}/{input_key}",
        ContentType="application/json",
    )
    output_uri = response["OutputLocation"]
    output_key = output_uri.replace(f"s3://{S3_BUCKET}/", "")

    print(f"Output will appear at: {output_uri}")
    print("Polling for result", end="", flush=True)

    for _ in range(60):
        try:
            obj = s3.get_object(Bucket=S3_BUCKET, Key=output_key)
            result = json.loads(obj["Body"].read().decode())
            print("\n\n--- Response ---")
            if isinstance(result, list) and result and "generated_text" in result[0]:
                print(result[0]["generated_text"])
            else:
                print(json.dumps(result, indent=2))
            return
        except s3.exceptions.NoSuchKey:
            print(".", end="", flush=True)
            time.sleep(3)

    print("\nERROR: Timed out after 3 minutes waiting for result.")
    print(f"Check CloudWatch logs for endpoint: {ENDPOINT_NAME}")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def status() -> None:
    session = _get_session()
    sm = session.client("sagemaker")
    try:
        desc = sm.describe_endpoint(EndpointName=ENDPOINT_NAME)
        state = desc["EndpointStatus"]
        print(f"Endpoint:  {ENDPOINT_NAME}")
        print(f"Status:    {state}")
        print(f"Created:   {desc['CreationTime']}")
        print(f"Updated:   {desc['LastModifiedTime']}")
        if state == "InService":
            print("\nEndpoint is ready. Set USE_SAGEMAKER=true in .env to route traffic here.")
    except sm.exceptions.ClientError:
        print(f"Endpoint '{ENDPOINT_NAME}' not found.")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def cleanup() -> None:
    """Delete endpoint, config, and model — stops all billing for this endpoint."""
    session = _get_session()
    sm = session.client("sagemaker")

    try:
        desc = sm.describe_endpoint(EndpointName=ENDPOINT_NAME)
        config_name = desc["EndpointConfigName"]
    except sm.exceptions.ClientError:
        print(f"Endpoint '{ENDPOINT_NAME}' not found.")
        return

    config_desc = sm.describe_endpoint_config(EndpointConfigName=config_name)
    model_name = config_desc["ProductionVariants"][0]["ModelName"]

    print(f"Deleting endpoint:        {ENDPOINT_NAME}")
    sm.delete_endpoint(EndpointName=ENDPOINT_NAME)

    print(f"Deleting endpoint config: {config_name}")
    sm.delete_endpoint_config(EndpointConfigName=config_name)

    print(f"Deleting model:           {model_name}")
    sm.delete_model(ModelName=model_name)

    print("\nCleanup complete. No more GPU charges for this endpoint.")
    print(f"Note: S3 model artifact at {MODEL_DATA_URI} was NOT deleted.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy Qwen fine-tune to SageMaker Async Inference"
    )
    parser.add_argument(
        "action",
        choices=["deploy", "invoke", "status", "cleanup"],
    )
    parser.add_argument("--role-arn", default=None, help="SageMaker execution role ARN")
    parser.add_argument(
        "--prompt",
        default="Why does my C++ pointer cause a segmentation fault?",
        help="Test prompt for invoke action",
    )
    args = parser.parse_args()

    if args.action == "deploy":
        deploy(args.role_arn)
    elif args.action == "invoke":
        invoke(args.prompt)
    elif args.action == "status":
        status()
    elif args.action == "cleanup":
        cleanup()


if __name__ == "__main__":
    main()
