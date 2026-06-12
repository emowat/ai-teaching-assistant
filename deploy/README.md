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
| **Shell wrappers** (start here) | `deploy/scripts/*.sh` | Human-friendly entry points with `--help` |
| **Python implementation** | `deploy/upload_model.py`, `deploy/deploy_sagemaker.py` | Download, S3 upload, SageMaker API calls |
| **Application** | `rag_eng/inference.py` | Calls the live endpoint at request time |

---

## Quick start (two commands)

From the **repository root**:

```bash
# 1) Download from Google Drive, package, upload to S3
./deploy/scripts/prepare-custom-model-from-google-drive.sh

# 2) Create SageMaker Async endpoint (~5–15 min)
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy

# 3) Smoke test
./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh invoke
```

Then set in `.env` and restart `rag_eng`:

```bash
USE_SAGEMAKER=true
SAGEMAKER_ENDPOINT=codingrabbit-qwen-async
MODEL_FAMILY=qwen
S3_DATA_BUCKET=codingrabbit-data-dev
AWS_REGION=us-east-1
```

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
2. **Package** — Creates `./model.tar.gz` (files at archive root for `/opt/ml/model/`)
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

### `deploy-custom-model-to-sagemaker-ai.sh`

**Purpose:** Create and manage a **SageMaker Asynchronous Inference** endpoint that loads the S3 model artifact.

Async Inference is used because the fine-tuned Qwen model is large, inference can take tens of seconds, and the endpoint can **scale to zero** when idle. See [AWS Async Inference docs](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html).

**Actions:**

| Action | What it does | Typical duration |
|---|---|---|
| `deploy` | Create Model + EndpointConfig + Endpoint | 5–15 minutes |
| `invoke` | Send test prompt via async S3 in/out pipeline | 30–90 s cold start |
| `status` | Print endpoint state | Instant |
| `cleanup` | Delete endpoint, config, model (stops GPU charges) | 2–5 minutes |

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

## GPU instance sizing

| Model | Format | VRAM | Instance | ~Cost/hr |
|---|---|---|---|---|
| Qwen2-14B | bf16/fp16 | ~28 GB | `ml.g5.12xlarge` | ~$5.67 |
| Qwen2-14B | 4-bit / QLoRA merged | ~8 GB | `ml.g5.2xlarge` | ~$1.21 |
| Qwen2-7B | bf16 | ~14 GB | `ml.g5.2xlarge` | ~$1.21 |

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
      │  USE_SAGEMAKER=true:
      │    Format Qwen chat template (MODEL_FAMILY=qwen)
      │    PUT request JSON → s3://…/temp/sagemaker_inputs/
      │    invoke_endpoint_async
      │    Poll S3 for output
      │    Stream chunks back to extension
      ▼
SageMaker Async Endpoint  ← created by deploy-custom-model-to-sagemaker-ai.sh
      │
      ▼
Fine-tuned Qwen  ← loaded from s3://…/models/qwen-finetuned/model.tar.gz
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
| `invoke` times out | Check `status`; first call has cold start; see CloudWatch logs |
| Extension still hits Ollama | Set `USE_SAGEMAKER=true` and restart `rag_eng` |
| Wrong chat template / garbage output | Set `MODEL_FAMILY=qwen` for Qwen models |

---

## File layout

```text
deploy/
├── README.md                                          ← this file
├── scripts/
│   ├── prepare-custom-model-from-google-drive.sh      ← Step 1: Drive → S3
│   └── deploy-custom-model-to-sagemaker-ai.sh         ← Step 2: S3 → SageMaker
├── upload_model.py                                    ← Python: download/package/push
└── deploy_sagemaker.py                                ← Python: endpoint lifecycle
```
