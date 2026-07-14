# deploy/

Operational tooling for provisioning the **fine-tuned Qwen inference model** on **Amazon SageMaker AI**, the **`rag_eng` ECS/Fargate orchestrator service**, and the planned **frontend static hosting** stack. This folder is **not** part of the runtime application (`rag_eng`); run these scripts once (or when you need to refresh the model, endpoint, or online service wiring).

## Overview

```text
Google Drive (fine-tuned Qwen)
        │
        ▼  prepare-custom-model-from-google-drive.sh
   ./model_download/  →  ./model.tar.gz  →  s3://…/models/qwen-finetuned/
        │
        ▼  deploy-custom-model-to-sagemaker-ai.sh
   SageMaker Async Inference endpoint (GPU)
        │
        ▼  rag_eng (USE_SAGEMAKER=true)
   POST /api/chat  ← VS Code extension / Codespaces
```

| Layer | Location | Role |
|---|---|---|
| **Configuration** | `deploy/deployment.yaml` | Single source of truth for all deploy settings |
| **Shell wrappers** (start here) | `deploy/scripts/*.sh` | Human-friendly entry points with `--help` |
| **Python implementation** | `deploy/upload_model.py`, `deploy/deploy_sagemaker.py`, `deploy/deploy_ingestion_worker.py`, `deploy/deploy_evaluation_worker.py`, `deploy/evaluation_worker_image.py`, `deploy/deploy_rag_eng_ecs.py`, `deploy/provision_rag_eng_stack.py`, `deploy/sagemaker_io.py` | Download, S3 upload, SageMaker API calls, ECS task-definition helpers, evaluation-worker image build/push, rag_eng AWS provisioning, async payload helpers |
| **Application** | `rag_eng/inference.py` | Calls the live endpoint at request time |

---

## Configuration (`deployment.yaml`)

All deploy scripts read **`deploy/deployment.yaml`**. Environment variables and CLI flags override YAML values.

```bash
# Print every field, env override, and resolved values:
python deploy/deployment_config.py describe

# Export resolved settings for shell scripts:
python deploy/deployment_config.py shell-export

# Use a custom config file:
export DEPLOY_CONFIG=/path/to/my-deployment.yaml
```

**Override precedence:** CLI flag → environment variable → `deployment.yaml`

| Section | Keys | Purpose |
|---|---|---|
| `google_drive` | `folder_id`, `folder_url` | Source model on Google Drive |
| `local_paths` | `download_dir`, `tarball_path`, `partial_file_suffixes` | Local working files (gitignored) |
| `aws` | `region`, `profile`, `s3_bucket` | AWS credentials target |
| `model_artifact` | `s3_key`, `s3_uri` | S3 location of `model.tar.gz` |
| `sagemaker` | `endpoint_name`, `instance_type`, `dlc`, `container`, `async_inference`, `autoscaling` | Async endpoint setup |
| `inference_smoke_test` | `default_prompt`, `chat_template`, generation params | `invoke` smoke test |
| `huggingface_packaging` | `required_files` | Validation before packaging |
| `rag_eng` | `model_family`, `use_sagemaker`, `inference_backend` | Values to copy into `.env` after deploy |
| `evaluation_worker` | `cluster`, `task_family`, `task_definition`, `container_name`, `launch_type`, `platform_version`, `assign_public_ip`, `subnet_ids`, `security_group_ids`, `image_uri`, `execution_role_arn`, `task_role_arn`, `cpu`, `memory`, `log_group`, `log_stream_prefix`, `environment`, `secret_arn_map` | ECS task-definition defaults for the offline evaluation worker |
| `frontend_web` | `enabled`, `app_dir`, `dist_dir`, `bucket_name`, `bucket_prefix`, `default_root_object`, `spa_fallback_path`, `price_class`, `cloudfront`, `build` | Vite SPA build settings and S3 + CloudFront provisioning/publishing wiring |

The `_reference` block at the bottom of `deployment.yaml` documents each field (also printed by `describe`).

**Common env overrides:**

| Environment variable | YAML path |
|---|---|
| `S3_DATA_BUCKET` | `aws.s3_bucket` |
| `SAGEMAKER_ENDPOINT` | `sagemaker.endpoint_name` |
| `SAGEMAKER_INSTANCE_TYPE` | `sagemaker.instance_type` |
| `MODEL_DATA_URI` | `model_artifact.s3_uri` |
| `DRIVE_FOLDER_ID` | `google_drive.folder_id` |
| `AWS_REGION` | `aws.region` |
| `AWS_PROFILE` | `aws.profile` |
| `SAGEMAKER_EXECUTION_ROLE_ARN` | `sagemaker.execution_role_arn` |
| `SAGEMAKER_INFERENCE_BACKEND` | `sagemaker.container.inference_backend` / `rag_eng.inference_backend` |
| `MODEL_FAMILY` | `rag_eng.model_family` |
| `FRONTEND_ENABLED` | `frontend_web.enabled` |
| `FRONTEND_BUCKET_NAME` | `frontend_web.bucket_name` |
| `FRONTEND_BUCKET_PREFIX` | `frontend_web.bucket_prefix` |
| `FRONTEND_CLOUDFRONT_DISTRIBUTION_ID` | `frontend_web.cloudfront.distribution_id` |
| `FRONTEND_CLOUDFRONT_ALIASES` | `frontend_web.cloudfront.aliases` |
| `FRONTEND_CLOUDFRONT_ORIGIN_PROTOCOL_POLICY` | `frontend_web.cloudfront.origin_protocol_policy` |
| `VITE_API_BASE_URL` | `frontend_web.build.vite_api_base_url` |
| `VITE_COGNITO_DOMAIN` | `frontend_web.build.vite_cognito_domain` |
| `VITE_COGNITO_REDIRECT_URI` | `frontend_web.build.vite_cognito_redirect_uri` |
| `VITE_COGNITO_LOGOUT_URI` | `frontend_web.build.vite_cognito_logout_uri` |

**SageMaker execution role:** must be a dedicated IAM role that trusts `sagemaker.amazonaws.com` and can read `aws.s3_bucket`. Your SSO login role (`AWSReservedSSO_*`) is **not** valid — set `sagemaker.execution_role_arn` in `deployment.yaml`.

---

## Quick start (two commands)

From the **repository root**:

```bash
# 1) Download from Google Drive, package, upload to S3
./deploy/scripts/prepare-custom-model-from-google-drive.sh

# 2) Create SageMaker Async endpoint (15–30 min first deploy; vLLM model load)
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy

# 3) Smoke test
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh invoke
```

Then set in `.env` and restart `rag_eng`:

```bash
USE_SAGEMAKER=true
SAGEMAKER_ENDPOINT=codingrabbit-qwen-async
SAGEMAKER_INFERENCE_BACKEND=vllm
MODEL_FAMILY=qwen
S3_DATA_BUCKET=codingrabbit-data-dev
AWS_REGION=us-east-1
AWS_PROFILE=codingrabbit-dev
```

`SAGEMAKER_INFERENCE_BACKEND` must match `sagemaker.container.inference_backend` in `deployment.yaml` (currently `vllm`).

---

## Prerequisites

### Python environment

This repo uses `requirements.txt` + `.venv` (no `pyproject.toml`):

```bash
cd ~/MIDS/w210/capstone
uv venv                    # if .venv does not exist
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install gdown boto3
```

### AWS

- Credentials via `aws configure` or `AWS_PROFILE` in `.env`
- S3 bucket (default: `codingrabbit-data-dev`)
- IAM permissions: SageMaker create/delete, S3 read/write, `iam:PassRole` for the execution role

### Google Drive

- Model folder: [Google Drive](https://drive.google.com/drive/u/0/folders/14Gp0dkdI3RJi7AqH_uADkzF69ou3Ev3O) (ID hardcoded in `upload_model.py`)
- Share with **Anyone with the link**, or run `gdown auth` once

### Local artifacts (gitignored)

| Path | Purpose |
|---|---|
| `model_download/` | HuggingFace files pulled from Drive |
| `model.tar.gz` | Packaged artifact before S3 upload |

---

## Shell scripts (`deploy/scripts/`)

These are the **recommended** way to run deployment. Each script:

- Must be run from the **repo root** (or any directory — they resolve paths automatically)
- Loads `/.env` if present
- Prefers `.venv/bin/python` when available
- Delegates to the Python modules in `deploy/`

### `prepare-custom-model-from-google-drive.sh`

**Purpose:** Move the custom fine-tuned model from Google Drive into S3 in the format SageMaker expects.

**Pipeline (default — all three steps):**

1. **Download** — `gdown` fetches the Drive folder into `./model_download/`
2. **Package** — Creates `./model.tar.gz` (files at archive root for `/opt/ml/model/`). Include `chatml_template.jinja` in `model_download/` before packaging if you use a custom chat template (see below).
3. **Push** — Uploads to `s3://<S3_DATA_BUCKET>/models/qwen-finetuned/model.tar.gz`

**Usage:**

```bash
./deploy/scripts/prepare-custom-model-from-google-drive.sh              # full pipeline
./deploy/scripts/prepare-custom-model-from-google-drive.sh --help

# Interrupted download — resume (skips completed files, reuses partial transfers):
./deploy/scripts/prepare-custom-model-from-google-drive.sh --resume

# Interactive prompt if model_download/ already has files: Resume / Re-download / Quit
./deploy/scripts/prepare-custom-model-from-google-drive.sh

# Start over — wipe model_download/ and download again:
./deploy/scripts/prepare-custom-model-from-google-drive.sh --force-redownload

# Run individual steps:
./deploy/scripts/prepare-custom-model-from-google-drive.sh --download-only
./deploy/scripts/prepare-custom-model-from-google-drive.sh --package-only
./deploy/scripts/prepare-custom-model-from-google-drive.sh --push-only
```

**When to use each flag:**

| Flag | Use when |
|---|---|
| `--resume` | Connection dropped; most shards already in `model_download/` |
| `--force-redownload` | Corrupt/partial tree; you want a clean slate |
| `--download-only` | Inspecting files locally before packaging |
| `--package-only` | Download finished; ready to build `model.tar.gz` |
| `--push-only` | `model.tar.gz` exists; only S3 upload needed |

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `S3_DATA_BUCKET` | `codingrabbit-data-dev` | Destination bucket |
| `AWS_REGION` | `us-east-1` | S3 region |
| `AWS_PROFILE` | (none) | Optional named profile |

**Success output:** `s3://<bucket>/models/qwen-finetuned/model.tar.gz` — used by the SageMaker deploy script as `MODEL_DATA_URI`.

---

### `restore-guardrail-checkpoint.sh`

**Purpose:** Download the fine-tuned CodeBERT guardrail checkpoint from S3 and extract it into the local Hugging Face checkpoint directory used by `output_guardrails/semantic_guardrail.py`.

**Default source and target:**

- S3 source: `s3://codingrabbit-data-dev/models/guardrails/codebert_v2_1/model.tar.gz`
- Local checkpoint target: `output_guardrails/models/checkpoints/codebert_v2_1`

**Usage:**

```bash
./deploy/scripts/restore-guardrail-checkpoint.sh
./deploy/scripts/restore-guardrail-checkpoint.sh --help
```

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `GUARDRAILS_CODEBERT_S3_URI` | `s3://codingrabbit-data-dev/models/guardrails/codebert_v2_1/model.tar.gz` | Source model artifact |
| `GUARDRAILS_CODEBERT_CHECKPOINT_DIR` | `output_guardrails/models/checkpoints/codebert_v2_1` | Local checkpoint directory |
| `AWS_PROFILE` | (none) | Optional named profile for S3 download |
| `AWS_REGION` | (none) | Optional region override for S3 download |

**Success output:** the local checkpoint directory contains `config.json`, tokenizer files, and model weights, ready for `output_guardrails.semantic_guardrail.predict_safety()`.

### `rag-eng-startup.sh`

**Purpose:** ECS entrypoint for the online orchestrator. It restores both guardrail checkpoints from S3, then starts `uvicorn`.

**Behavior:**

- restores the input guardrail checkpoint with `deploy/restore_input_guardrail_checkpoint.py`
- restores the output guardrail checkpoint with `deploy/restore_guardrail_checkpoint.py`
- then runs `uvicorn rag_eng.main:app --host 0.0.0.0 --port 8001 --proxy-headers --forwarded-allow-ips '*'`
- sets `GRADIO_ROOT_PATH=/gradio` and `GRADIO_PUBLIC_ORIGIN` to the public
  CloudFront origin so the embedded console generates HTTPS-safe asset and API
  links without breaking the mounted route

This keeps the Docker image small while ensuring the checkpoints are present in the task filesystem before the service starts.

---

### `deploy-ingestion-worker.sh`

**Purpose:** Describe, render, or register the ECS Fargate task definition used by the on-demand ingestion worker.

The script does not launch jobs itself. The backend already owns job launches via `/admin/ingestion/launch`; this helper only makes the ECS wiring reproducible.

| Action | What it does |
|---|---|
| `describe` | Print the resolved ECS task-definition settings and any missing values |
| `render-task-definition` | Emit the ECS task-definition JSON payload |
| `render-backend-env` | Emit the backend `.env` fragment for `INGESTION_ECS_*` values |
| `register-task-definition` | Register the task definition with ECS using boto3 |

**Usage:**

```bash
./deploy/scripts/deploy-ingestion-worker.sh describe
./deploy/scripts/deploy-ingestion-worker.sh render-task-definition
./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
./deploy/scripts/deploy-ingestion-worker.sh register-task-definition
```

**Required worker settings:**

| Variable | Description |
|---|---|
| `INGESTION_ECS_IMAGE_URI` | ECR image URI for the worker container |
| `INGESTION_ECS_EXECUTION_ROLE_ARN` | ECS task execution role ARN |
| `INGESTION_ECS_TASK_ROLE_ARN` | ECS task role ARN |
| `INGESTION_ECS_TASK_FAMILY` | Task family name used for registration |
| `INGESTION_ECS_TASK_DEFINITION` | Task definition name/ARN used by the backend launcher |
| `INGESTION_ECS_CONTAINER_NAME` | Container name inside the task definition |
| `INGESTION_ECS_SUBNETS` | Comma-separated ECS subnets for `run-task` |
| `INGESTION_ECS_SECURITY_GROUPS` | Comma-separated ECS security groups for `run-task` |
| `INGESTION_ECS_SECRET_ARNS_JSON` | Optional JSON map of secret env names to Secrets Manager ARNs |

**Recommended secret mapping keys:**

- `INGESTION_JOBS_DATABASE_URL`
- `COURSE_REGISTRY_DATABASE_URL`
- `QDRANT_API_KEY`

**Example:**

```bash
export INGESTION_ECS_IMAGE_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-ingestion:latest
export INGESTION_ECS_EXECUTION_ROLE_ARN=arn:aws:iam::123456789012:role/ecsTaskExecutionRole
export INGESTION_ECS_TASK_ROLE_ARN=arn:aws:iam::123456789012:role/codingrabbit-ingestion-task
export INGESTION_ECS_TASK_FAMILY=codingrabbit-ingestion-worker
export INGESTION_ECS_TASK_DEFINITION=codingrabbit-ingestion-worker
export INGESTION_ECS_CONTAINER_NAME=ingestion-worker
export INGESTION_ECS_SUBNETS=subnet-123,subnet-456
export INGESTION_ECS_SECURITY_GROUPS=sg-123
export INGESTION_ECS_SECRET_ARNS_JSON='{"INGESTION_JOBS_DATABASE_URL":"arn:aws:secretsmanager:...","QDRANT_API_KEY":"arn:aws:secretsmanager:..."}'
```

**Success output:** the helper prints the rendered task definition, the backend launch env fragment, or the ECS registration response, depending on the chosen action.

---

### `deploy-evaluation-worker.sh`

**Purpose:** Describe, render, or register the ECS Fargate task definition used by the offline evaluation worker.

The evaluation worker runs model-judging jobs on demand. It uses its own dedicated image and reuses the shared AWS wiring, but launches as a separate one-off task family so runs stay isolated from the online `rag_eng` service.

| Action | What it does |
|---|---|
| `describe` | Print the resolved ECS task-definition settings and any missing values |
| `render-task-definition` | Emit the ECS task-definition JSON payload |
| `render-backend-env` | Emit the backend `.env` fragment for `EVALUATION_WORKER_ECS_*` values |
| `register-task-definition` | Register the task definition with ECS using boto3 |

**Usage:**

First build and push the dedicated worker image:

```bash
./deploy/scripts/build-evaluation-worker-image.sh
```

Then render or register the task definition:

```bash
./deploy/scripts/deploy-evaluation-worker.sh describe
./deploy/scripts/deploy-evaluation-worker.sh render-task-definition
./deploy/scripts/deploy-evaluation-worker.sh render-backend-env
./deploy/scripts/deploy-evaluation-worker.sh register-task-definition
```

**Required worker settings:**

| Variable | Description |
|---|---|
| `EVALUATION_WORKER_ECS_IMAGE_URI` | ECR image URI for the dedicated worker container |
| `EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN` | ECS task execution role ARN |
| `EVALUATION_WORKER_ECS_TASK_ROLE_ARN` | ECS task role ARN |
| `EVALUATION_WORKER_ECS_TASK_FAMILY` | Task family name used for registration |
| `EVALUATION_WORKER_ECS_TASK_DEFINITION` | Task definition name/ARN used by the launcher |
| `EVALUATION_WORKER_ECS_CONTAINER_NAME` | Container name inside the task definition |
| `EVALUATION_WORKER_ECS_SUBNETS` | Comma-separated ECS subnets for `run-task` |
| `EVALUATION_WORKER_ECS_SECURITY_GROUPS` | Comma-separated ECS security groups for `run-task` |
| `EVALUATION_WORKER_ECS_SECRET_ARNS_JSON` | Optional JSON map of secret env names to Secrets Manager ARNs |

**Recommended secret mapping keys:**

- `COURSE_REGISTRY_DATABASE_URL`
- `OPENAI_API_KEY`

**Success output:** the helper prints the rendered task definition, the backend launch env fragment, or the ECS registration response, depending on the chosen action.

---

## AWS wiring checklist for ingestion

Use this when you are ready to make the on-demand ingestion worker live in AWS.

### 1. Build and push the worker image to ECR

Create or reuse an ECR repository for the ingestion worker, then build and push
the image from the repo root:

```bash
docker build -f ingestion_worker/Dockerfile -t codingrabbit-ingestion:latest .
docker tag codingrabbit-ingestion:latest 123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-ingestion:latest
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-ingestion:latest
```

The helper expects the final image URI in `INGESTION_ECS_IMAGE_URI`.

### 2. Create the ECS task roles

You need two roles:

- **Task execution role**
  - trusted by `ecs-tasks.amazonaws.com`
  - permissions for ECR image pulls, CloudWatch Logs, and Secrets Manager value injection
- **Task role**
  - trusted by `ecs-tasks.amazonaws.com`
  - permissions for the worker’s AWS calls at runtime, primarily S3 read/write for uploads, parsed envelopes, and prepared chunks

The worker itself reads Qdrant and PostgreSQL over the network, so those do not need AWS IAM permissions.

### 3. Register the ECS task definition

Set the task-definition values, then register it through the helper:

```bash
export INGESTION_ECS_IMAGE_URI=123456789012.dkr.ecr.us-east-1.amazonaws.com/codingrabbit-ingestion:latest
export INGESTION_ECS_EXECUTION_ROLE_ARN=arn:aws:iam::123456789012:role/ecsTaskExecutionRole
export INGESTION_ECS_TASK_ROLE_ARN=arn:aws:iam::123456789012:role/codingrabbit-ingestion-task
export INGESTION_ECS_TASK_FAMILY=codingrabbit-ingestion-worker
export INGESTION_ECS_LOG_GROUP=/ecs/codingrabbit-ingestion-worker
export INGESTION_ECS_LOG_STREAM_PREFIX=ecs
export INGESTION_ECS_SECRET_ARNS_JSON='{"INGESTION_JOBS_DATABASE_URL":"arn:aws:secretsmanager:...","QDRANT_API_KEY":"arn:aws:secretsmanager:..."}'

./deploy/scripts/deploy-ingestion-worker.sh register-task-definition
```

The helper will register a task definition with:

- `awsvpc` networking
- `FARGATE` compatibility
- the worker container name from `INGESTION_ECS_CONTAINER_NAME`
- CloudWatch Logs configuration
- secret mappings for the worker env vars listed below

### 4. Copy the backend launch settings into `.env`

The backend launcher needs the ECS control-plane values, not the image URI:

```bash
./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
```

Recommended backend `.env` values:

| Variable | Purpose |
|---|---|
| `AWS_REGION` | ECS region |
| `AWS_PROFILE` | Optional named profile for local admin launches |
| `INGESTION_ECS_CLUSTER` | ECS cluster name |
| `INGESTION_ECS_TASK_DEFINITION` | Task definition name or ARN |
| `INGESTION_ECS_CONTAINER_NAME` | Container name inside the task definition |
| `INGESTION_ECS_LAUNCH_TYPE` | Usually `FARGATE` |
| `INGESTION_ECS_PLATFORM_VERSION` | Usually `LATEST` |
| `INGESTION_ECS_ASSIGN_PUBLIC_IP` | Usually `ENABLED` for dev launches |
| `INGESTION_ECS_SUBNETS` | Comma-separated subnet IDs |
| `INGESTION_ECS_SECURITY_GROUPS` | Comma-separated security group IDs |

The worker task definition itself should keep its own runtime env values for:

- `INGESTION_JOB_ID`
- `INGESTION_JOB_KIND`
- `INGESTION_JOBS_DATABASE_URL` or `COURSE_REGISTRY_DATABASE_URL`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `EMBEDDING_MODEL`
- `QDRANT_COLLECTION_MIT13`
- `QDRANT_COLLECTION_MIT14`

### `deploy-rag-eng-ecs.sh`

**Purpose:** Describe, render, register, or deploy the ECS/Fargate service that runs the `rag_eng` orchestrator behind an ALB.

This is the online application runtime for `/api/chat`, `/query`, `/me`, and the admin APIs. It is separate from the SageMaker model deployment scripts.

| Action | What it does |
|---|---|
| `describe` | Print the resolved orchestrator service wiring and any missing values |
| `render-task-definition` | Emit the ECS task-definition JSON payload |
| `render-service-spec` | Emit the ECS service spec JSON payload |
| `register-task-definition` | Register the task definition with ECS using boto3 |
| `deploy` | Register the task definition and create/update the ECS service |
| `status` | Print the current ECS service status |

**Usage:**

```bash
./deploy/scripts/deploy-rag-eng-ecs.sh describe
./deploy/scripts/deploy-rag-eng-ecs.sh render-task-definition
./deploy/scripts/deploy-rag-eng-ecs.sh render-service-spec
./deploy/scripts/deploy-rag-eng-ecs.sh register-task-definition
./deploy/scripts/deploy-rag-eng-ecs.sh deploy
./deploy/scripts/deploy-rag-eng-ecs.sh status
```

**Required service settings:**

| Variable | Description |
|---|---|
| `RAG_ENG_ECS_IMAGE_URI` | ECR image URI for the orchestrator container |
| `RAG_ENG_ECS_EXECUTION_ROLE_ARN` | ECS task execution role ARN |
| `RAG_ENG_ECS_TASK_ROLE_ARN` | ECS task role ARN |
| `RAG_ENG_ECS_CLUSTER` | ECS cluster name |
| `RAG_ENG_ECS_SERVICE_NAME` | ECS service name |
| `RAG_ENG_ECS_TASK_FAMILY` | Task family name |
| `RAG_ENG_ECS_TASK_DEFINITION` | Task definition name or ARN used by the backend launcher |
| `RAG_ENG_ECS_CONTAINER_NAME` | Container name inside the task definition |
| `RAG_ENG_ECS_SUBNETS` | Comma-separated ECS subnets for the service |
| `RAG_ENG_ECS_SECURITY_GROUPS` | Comma-separated ECS security groups for the service |
| `RAG_ENG_ECS_TARGET_GROUP_ARN` | ALB target group ARN for the service |

**Notes:**

- `rag_eng_ecs.environment` in `deploy/deployment.yaml` stores the non-secret runtime env baked into the task definition.
- `rag_eng_ecs.secret_arn_map` stores the Secrets Manager ARNs for secret env vars injected at task launch.
- `APP_PORT` is set to `8001` in the task definition and matches the local `uvicorn` command.
- The runtime behavior knobs that should stay editable without rebuilding the task definition live in [`rag_eng/runtime_config.yaml`](/home/user/MIDS/w210/capstone/rag_eng/runtime_config.yaml).

### `provision-rag-eng-stack.sh`

**Purpose:** Provision the AWS infrastructure for the `rag_eng` online orchestrator, then build/push the Docker image and deploy the ECS service.

**What it creates or updates:**

- ECR repository for the orchestrator image
- ECS cluster for the online service
- ECS execution role and task role
- CloudWatch log group
- Secrets Manager entries for the runtime secret env vars
- ALB security group, application load balancer, target group, and listener
- ECS task definition and ECS service

**Usage:**

```bash
./deploy/scripts/provision-rag-eng-stack.sh describe
./deploy/scripts/provision-rag-eng-stack.sh apply
./deploy/scripts/provision-rag-eng-stack.sh apply --skip-preflight
```

**Notes:**

- The script expects the `rag_eng_ecs` block in `deploy/deployment.yaml` to contain the shared network and runtime settings.
- The resulting ARNs and DNS name are printed as JSON so they can be copied back into `deploy/deployment.yaml`.
- `apply` runs a local preflight gate first: `git diff --check`, `ruff check deploy/provision_rag_eng_stack.py deploy/deploy_rag_eng_ecs.py deploy/deployment_config.py rag_eng`, and the local `pytest` battery for the backend/deploy code. Use `--skip-preflight` or `RAG_ENG_SKIP_PREFLIGHT=1` only when you need an emergency bypass.

### Frontend static hosting

The React/Vite frontend lives in [`frontend/`](/home/user/MIDS/w210/capstone/frontend) and reads the repo-root `.env` at build time. The deployment config now includes a `frontend_web` section for the S3 + CloudFront publishing slice.

The infrastructure helper is [`deploy/scripts/provision-frontend-stack.sh`](/home/user/MIDS/w210/capstone/deploy/scripts/provision-frontend-stack.sh).

The current helper is [`deploy/scripts/publish-frontend.sh`](/home/user/MIDS/w210/capstone/deploy/scripts/publish-frontend.sh).

What it does:

- build `frontend/` into `frontend/dist/`
- upload the static bundle to S3
- delete stale objects under the configured bucket prefix
- invalidate the configured CloudFront distribution

Build behavior:

- If the local Node.js runtime is new enough for the current Vite toolchain, the helper builds directly on the host.
- If the local Node.js runtime is too old, the helper automatically falls back to a Dockerized Node 22 build so the publish flow still works on older workstations.

Required config for this flow:

- `frontend_web.bucket_name`
- `frontend_web.cloudfront.distribution_id`
- `frontend_web.cloudfront.invalidation_paths`
- `frontend_web.build.vite_api_base_url`
- `frontend_web.build.vite_cognito_domain`
- `frontend_web.build.vite_cognito_redirect_uri`
- `frontend_web.build.vite_cognito_logout_uri`

For production publishing, the Cognito callback/logout URLs must match the
actual CloudFront origin used by the static site, not the local dev server.
The localhost values remain appropriate for `npm run dev`; the CloudFront
values belong in `deploy/deployment.yaml` so the published bundle is built with
the correct origin baked in.
The frontend publish helper intentionally ignores repo-root `.env` overrides
for the build-time `VITE_*` frontend URLs so the deployment file stays the
source of truth for production bundle settings.

The relevant values live in:

- `frontend_web.app_dir`
- `frontend_web.dist_dir`
- `frontend_web.bucket_name`
- `frontend_web.bucket_prefix`
- `frontend_web.cloudfront.distribution_id`
- `frontend_web.cloudfront.aliases`
- `frontend_web.cloudfront.api_path_patterns`
- `frontend_web.cloudfront.origin_protocol_policy`
- `frontend_web.build.vite_api_base_url`
- `frontend_web.build.vite_cognito_domain`
- `frontend_web.build.vite_cognito_redirect_uri`
- `frontend_web.build.vite_cognito_logout_uri`

The provision helper creates the missing S3 bucket and CloudFront distribution ID, then prints the resolved values so they can be copied into `deploy/deployment.yaml`.

### 5. Smoke test the control plane

After the task definition and backend `.env` values are in place:

1. Restart `rag_eng`
2. Call the admin launch endpoint:
   - `POST /admin/ingestion/launch`
3. Poll job status:
   - `GET /admin/ingestion/jobs/{job_id}`
4. Confirm the worker marks the Aurora job complete and activates the corpus version for `chunk-index`

If the ECS task launches but the job stays queued or failed, inspect:
- CloudWatch logs for the ingestion task
- the `ecs_response` and `message` fields returned by the job API
- the task-role / execution-role permissions and secret mappings

---

### `deploy-custom-model-to-sagemaker-ai.sh`

**Purpose:** Create and manage a **SageMaker Asynchronous Inference** endpoint that loads the S3 model artifact.

Async Inference is used because the fine-tuned Qwen model is large and inference can take tens of seconds. **`deploy` configures Application Auto Scaling** so the endpoint scales to **0 GPU instances when idle** (no inference charges). See [async autoscaling](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference-autoscale.html).

| Action | What it does | Typical duration |
|---|---|---|
| `deploy` | Create Model + EndpointConfig + Endpoint + auto scaling | 15–30 minutes (first vLLM load) |
| `invoke` | Send test prompt via async S3 in/out pipeline | 1–5 min if scaled to 0 |
| `status` | Print endpoint state and instance count | Instant |
| `cleanup` | Delete endpoint, auto scaling, config, model | 2–5 minutes |

**Usage:**

```bash
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh status
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh invoke
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh invoke --prompt "Explain pointer dereference in C++"

./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh cleanup   # stop billing
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh --help
```

**Optional:**

```bash
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy --role-arn arn:aws:iam::ACCOUNT:role/SageMakerRole
```

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `SAGEMAKER_ENDPOINT` | `codingrabbit-qwen-async` | Endpoint name; must match `rag_eng` `.env` |
| `S3_DATA_BUCKET` | `codingrabbit-data-dev` | Bucket for model + async I/O |
| `MODEL_DATA_URI` | `s3://<bucket>/models/qwen-finetuned/model.tar.gz` | Model artifact |
| `SAGEMAKER_INSTANCE_TYPE` | `ml.g5.2xlarge` | GPU instance (see sizing below) |
| `AWS_REGION` | `us-east-1` | Region |
| `AWS_PROFILE` | (none) | Optional named profile |

**After `deploy` succeeds:** set `USE_SAGEMAKER=true` in `.env` and restart `rag_eng`. The VS Code extension’s `codingRabbit.apiUrl` should point at your deployed API (`POST /api/chat`).

---

### `deploy-aurora-course-registry.sh`

**Purpose:** Bootstrap the Aurora PostgreSQL course registry schema and seed the
initial course mappings used by `rag/course_registry.py`.

**What it does:**

1. Reads the versioned schema file at `deploy/sql/aurora_course_registry.sql`
2. Executes the DDL and seed statements through the Aurora Data API
3. Verifies the resulting `courses` and `course_aliases` rows

**Temporary dev access reminder:** if you open Aurora to your laptop for local
development, revert the public access change, route table change, and any
temporary security-group exception after the backend is deployed.

**Usage:**

```bash
./deploy/scripts/deploy-aurora-course-registry.sh apply \
  --resource-arn arn:aws:rds:us-east-1:123456789012:cluster:my-course-registry \
  --secret-arn arn:aws:secretsmanager:us-east-1:123456789012:secret:my-db-secret \
  --database postgres \
  --region us-east-1 \
  --profile codingrabbit-dev
```

**Environment variables:**

| Variable | Default | Description |
|---|---|---|
| `AURORA_COURSE_REGISTRY_RESOURCE_ARN` | — | Aurora cluster resource ARN for the Data API |
| `AURORA_COURSE_REGISTRY_SECRET_ARN` | — | Secrets Manager ARN for the DB credentials |
| `AURORA_COURSE_REGISTRY_DATABASE` | `postgres` | Aurora database name |
| `AURORA_COURSE_REGISTRY_SQL_FILE` | `deploy/sql/aurora_course_registry.sql` | SQL bootstrap file |
| `AWS_REGION` | `us-east-1` | AWS region for the Data API client |
| `AWS_PROFILE` | — | Optional named AWS profile |

If the Data API call fails, the script exits non-zero and the cluster is left in
its previous committed state.

---

## Python modules (advanced / CI)

Use these directly if you need finer control or automation without the shell wrappers.

### `upload_model.py`

```bash
python deploy/upload_model.py upload                    # download + package + push
python deploy/upload_model.py download --resume
python deploy/upload_model.py package --local-dir ./model_download
python deploy/upload_model.py push --tar ./model.tar.gz
```

### `deploy_sagemaker.py`

```bash
python deploy/deploy_sagemaker.py deploy
python deploy/deploy_sagemaker.py invoke
python deploy/deploy_sagemaker.py status
python deploy/deploy_sagemaker.py cleanup
```

---

## vLLM inference stack

The endpoint uses the **AWS Deep Learning Container** `huggingface-vllm` (not the legacy `huggingface-pytorch-inference` pipeline). Key settings in `deployment.yaml`:

| Setting | Purpose |
|---|---|
| `sagemaker.dlc.repository: huggingface-vllm` | vLLM OpenAI-compatible server inside SageMaker |
| `sagemaker.container.inference_backend: vllm` | Async invoke uses OpenAI-style `messages` JSON |
| `SM_VLLM_QUANTIZATION: bitsandbytes` | 4-bit load at container startup — no AWQ re-export needed |
| `SM_VLLM_CHAT_TEMPLATE` | Path to custom Jinja template inside `/opt/ml/model/` |

**bitsandbytes inflight quantization:** the full bf16 weights in `model.tar.gz` are quantized to 4-bit when vLLM starts. This fits Qwen2-14B on `ml.g5.2xlarge` without re-uploading a pre-quantized artifact.

**Request format:** `deploy/sagemaker_io.py` builds payloads like:

```json
{
  "messages": [
    {"role": "system", "content": "You are a Socratic TA..."},
    {"role": "user", "content": "Why does my pointer segfault?"}
  ],
  "max_tokens": 512,
  "temperature": 0.7,
  "top_p": 0.9
}
```

vLLM applies the chat template on the endpoint. `rag_eng` does **not** pre-format `<|im_start|>` tokens when `SAGEMAKER_INFERENCE_BACKEND=vllm`.

---

## Custom chat template

The fine-tuned model was trained with **ChatML** (`<|im_start|>` role blocks and end-of-turn tokens). If HuggingFace metadata from Colab is wrong, ship an explicit Jinja file and point vLLM at it.

**Source template:** `deploy/templates/chatml_template.jinja`

**Repackage and redeploy:**

```bash
cp deploy/templates/chatml_template.jinja model_download/chatml_template.jinja
./deploy/scripts/prepare-custom-model-from-google-drive.sh --package-only
./deploy/scripts/prepare-custom-model-from-google-drive.sh --push-only
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy
```

Verify the template is at the archive root:

```bash
tar -tzf model.tar.gz | grep chatml_template.jinja
```

`deployment.yaml` sets `SM_VLLM_CHAT_TEMPLATE: /opt/ml/model/chatml_template.jinja`, which maps to vLLM’s `--chat-template` flag.

---

## Auto scaling (scale to zero)

`deploy` registers **two** Application Auto Scaling policies when `sagemaker.autoscaling.enabled: true`:

| Policy | Metric | When it applies |
|---|---|---|
| **Target tracking** | `ApproximateBacklogSizePerInstance` | Instance count ≥ 1 — scale out/in based on queue depth |
| **Step scaling from zero** | `HasBacklogWithoutCapacity` | Instance count = 0 but queue has requests — wake the endpoint |

With `min_capacity: 0`, the step policy is required; target tracking alone cannot wake a scaled-down endpoint.

**Cold-start latency** after long idle ≈ alarm wake time + instance launch + vLLM model load (often **5–15+ minutes** total). Tune in `deployment.yaml`:

```yaml
autoscaling:
  min_capacity: 0
  scale_from_zero_alarm:
    period_seconds: 30        # lower = faster wake (default ~30s vs AWS example ~2 min)
    evaluation_periods: 1
    datapoints_to_alarm: 1
```

See inline comments in `deployment.yaml` and [AWS async autoscaling docs](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference-autoscale.html).

---

## GPU instance sizing

| Model | Format | VRAM | Instance | ~Cost/hr |
|---|---|---|---|---|
| Qwen2-14B | bf16/fp16 | ~28 GB | `ml.g5.12xlarge` | ~$5.67 |
| Qwen2-14B | 4-bit bitsandbytes (inflight) | ~8 GB | `ml.g5.2xlarge` | ~$1.21 |
| Qwen2-7B | bf16 | ~14 GB | `ml.g5.2xlarge` | ~$1.21 |

When `min_capacity: 0`, you pay **$0/hr** for GPU while idle; cold starts add latency on the first request after scale-down.

If deploy fails with CUDA OOM, set before running deploy:

```bash
export SAGEMAKER_INSTANCE_TYPE=ml.g5.12xlarge
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy
```

---

## How this connects to `rag_eng`

```text
POST /api/chat  (VS Code extension, Ollama-compatible JSON)
      │
      ▼
rag_eng/service.py → run_chat()
      │  Parse [Code_Context], [Terminal_Context] from messages
      │  run_retrieval() → Qdrant + Cohere (real RAG)
      │  get_system_prompt() → 22 pedagogical rules
      ▼
rag_eng/inference.py → run_inference()
      │  USE_SAGEMAKER=true, SAGEMAKER_INFERENCE_BACKEND=vllm:
      │    OpenAI messages JSON (via sagemaker_io.build_async_payload)
      │    PUT request JSON → s3://…/temp/sagemaker_inputs/
      │    invoke_endpoint_async
      │    Poll S3 for output
      │    Stream chunks back to extension
      │  (Legacy huggingface backend: manual Qwen chat template via MODEL_FAMILY)
      ▼
SageMaker Async Endpoint (vLLM DLC)  ← deploy-custom-model-to-sagemaker-ai.sh
      │  Applies chatml_template.jinja; bitsandbytes 4-bit load
      ▼
Fine-tuned Qwen  ← s3://…/models/qwen-finetuned/model.tar.gz
```

**Important:** Deployment scripts run **once**. `rag_eng` only **invokes** the endpoint at runtime; it does not create infrastructure.

---

## Troubleshooting

| Problem | What to try |
|---|---|
| `uv add` fails with no `pyproject.toml` | Use `uv pip install gdown boto3` instead |
| Download interrupted | `./deploy/scripts/prepare-custom-model-from-google-drive.sh --resume` |
| `config.json` missing when packaging | Download not complete; resume or re-download |
| SageMaker deploy fails / OOM | Larger instance: `SAGEMAKER_INSTANCE_TYPE=ml.g5.12xlarge` |
| `invoke` times out | Endpoint may be scaled to 0; cold start can take 5–15+ min (alarm + provision + vLLM load) |
| Still paying when idle | Run `status` — instances should drop to 0 after scale-in cooldown (~10 min); or run `cleanup` |
| Extension still hits Ollama | Set `USE_SAGEMAKER=true` and restart `rag_eng` |
| Wrong chat template / garbage output | With vLLM: repackage `chatml_template.jinja`, push, redeploy. Legacy HF backend: set `MODEL_FAMILY=qwen` |
| SSO role rejected at deploy | Set `sagemaker.execution_role_arn` to a dedicated SageMaker execution role (not `AWSReservedSSO_*`) |

---

## File layout

```text
deploy/
├── README.md                                          ← this file
├── deployment.yaml                                    ← configuration (edit this first)
├── deployment_config.py                               ← YAML loader + describe CLI
├── sagemaker_io.py                                    ← vLLM / HuggingFace async payload helpers
├── templates/
│   └── chatml_template.jinja                          ← ChatML template shipped in model.tar.gz
├── scripts/
│   ├── _load_deploy_config.sh                         ← shared bash helper
│   ├── prepare-custom-model-from-google-drive.sh      ← Step 1: Drive → S3
│   └── deploy-custom-model-to-sagemaker-ai.sh         ← Step 2: S3 → SageMaker
├── upload_model.py                                    ← Python: download/package/push
└── deploy_sagemaker.py                                ← Python: endpoint lifecycle + autoscaling
```
