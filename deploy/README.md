# deploy/

Operational tooling for provisioning the **fine-tuned Qwen inference model** on **Amazon SageMaker AI**. This folder is **not** part of the runtime application (`rag_eng`); run these scripts once (or when you need to refresh the model or endpoint).

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
| **Python implementation** | `deploy/upload_model.py`, `deploy/deploy_sagemaker.py`, `deploy/sagemaker_io.py` | Download, S3 upload, SageMaker API calls, async payload helpers |
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
