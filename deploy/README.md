# deploy/

One-time operational scripts for provisioning the SageMaker inference endpoint.
These are **not** application code — run them once to set up infrastructure.

## Scripts

| Script | Purpose |
|---|---|
| `upload_model.py` | Download Qwen fine-tune from Google Drive → package → upload to S3 |
| `deploy_sagemaker.py` | Create SageMaker Async Inference endpoint from the S3 model |

## Full deployment flow

### 1. Install dependencies

```bash
pip install gdown boto3
```

### 2. Upload model to S3

```bash
# Full flow: download from Drive, package as model.tar.gz, upload to S3
python deploy/upload_model.py upload

# Or step by step:
python deploy/upload_model.py download            # → ./model_download/
python deploy/upload_model.py package             # → ./model.tar.gz
python deploy/upload_model.py push                # → s3://codingrabbit-data-dev/models/qwen-finetuned/model.tar.gz
```

The Drive folder ID is hardcoded: `14Gp0dkdI3RJi7AqH_uADkzF69ou3Ev3O`.
The folder must be shared with "Anyone with the link" or you must be authenticated with `gdown auth`.

### 3. Deploy the endpoint

```bash
python deploy/deploy_sagemaker.py deploy
# Takes 5–10 minutes while the GPU instance warms up
```

### 4. Smoke test

```bash
python deploy/deploy_sagemaker.py invoke
# First request has a 30–90 second cold start (async inference)
```

### 5. Wire into rag_eng

Add to `.env`:
```bash
USE_SAGEMAKER=true
SAGEMAKER_ENDPOINT=codingrabbit-qwen-async
MODEL_FAMILY=qwen
S3_DATA_BUCKET=codingrabbit-data-dev
AWS_REGION=us-east-1
```

Restart `rag_eng` — `POST /api/chat` now routes through SageMaker.

### 6. Shutdown when not in use

Async Inference endpoints scale to zero automatically when idle.
To delete entirely (stop all billing):

```bash
python deploy/deploy_sagemaker.py cleanup
```

---

## Instance sizing guide

| Model | Format | VRAM needed | Recommended instance | Cost/hr |
|---|---|---|---|---|
| Qwen2-14B | bf16/fp16 | ~28 GB | `ml.g5.12xlarge` (4×A10G, 96GB) | ~$5.67 |
| Qwen2-14B | 4-bit quantized | ~8 GB | `ml.g5.2xlarge` (1×A10G, 24GB) | ~$1.21 |
| Qwen2-7B | bf16 | ~14 GB | `ml.g5.2xlarge` (1×A10G, 24GB) | ~$1.21 |

Set `SAGEMAKER_INSTANCE_TYPE=ml.g5.12xlarge` before deploying if the model is fp16.

## How it connects to rag_eng

```
POST /api/chat  (VS Code extension)
      │
      ▼
rag_eng/service.py → run_chat()
      │  extracts context blocks, runs Qdrant RAG
      ▼
rag_eng/inference.py → run_inference()
      │  USE_SAGEMAKER=true path:
      │  1. Format prompt with Qwen chat template (<|im_start|>)
      │  2. Upload payload JSON to s3://codingrabbit-data-dev/temp/sagemaker_inputs/
      │  3. invoke_endpoint_async → SageMaker queues request
      │  4. Poll S3 output prefix for result (2s intervals)
      │  5. Simulate streaming back to extension
      ▼
SageMaker Async Endpoint (this script creates it)
      │
      ▼
Qwen2-14B fine-tuned model (loaded from s3://…/models/qwen-finetuned/model.tar.gz)
```
