#!/usr/bin/env bash
#
# prepare-custom-model-from-google-drive.sh
#
# Download the fine-tuned Qwen model from Google Drive, package it as
# model.tar.gz, and upload the artifact to S3 for SageMaker deployment.
#
# This is step 1 of the CodingRabbit inference deployment pipeline.
# Run deploy-custom-model-to-sagemaker-ai.sh after this completes.
#
# Usage (from repo root):
#   ./deploy/scripts/prepare-custom-model-from-google-drive.sh
#   ./deploy/scripts/prepare-custom-model-from-google-drive.sh --resume
#   ./deploy/scripts/prepare-custom-model-from-google-drive.sh --download-only
#   ./deploy/scripts/prepare-custom-model-from-google-drive.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/upload_model.py"

DOWNLOAD_ONLY=false
PACKAGE_ONLY=false
PUSH_ONLY=false
RESUME=false
FORCE_REDOWNLOAD=false
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
prepare-custom-model-from-google-drive.sh

  Step 1: Prepare the custom fine-tuned model for SageMaker.

  What this script does (default = all three sub-steps):
    1. DOWNLOAD  — Fetch HuggingFace model files from Google Drive into
                   ./model_download/ (supports resume after interruptions)
    2. PACKAGE   — Create ./model.tar.gz in SageMaker-compatible layout
    3. PUSH      — Upload model.tar.gz to S3 (codingrabbit-data-dev by default)

  Prerequisites:
    - AWS credentials configured (aws configure or AWS_PROFILE)
    - Python deps:  uv pip install gdown boto3
    - Google Drive folder shared or:  gdown auth

  Options:
    --download-only       Only download from Google Drive (no package/push)
    --package-only        Only package an existing ./model_download/
    --push-only           Only upload an existing ./model.tar.gz to S3
    --resume              Resume a partial Drive download (skip completed files)
    --force-redownload    Delete local model_download/ and download again
    --help                Show this message

  Examples:
    # Full pipeline (download → package → S3):
    ./deploy/scripts/prepare-custom-model-from-google-drive.sh

    # Connection dropped mid-download:
    ./deploy/scripts/prepare-custom-model-from-google-drive.sh --resume

    # Download finished locally; package and upload only:
    ./deploy/scripts/prepare-custom-model-from-google-drive.sh --package-only
    ./deploy/scripts/prepare-custom-model-from-google-drive.sh --push-only

  Environment (optional, from repo .env):
    S3_DATA_BUCKET   — target bucket (default: codingrabbit-data-dev)
    AWS_REGION       — default: us-east-1
    AWS_PROFILE      — named AWS profile

  Output:
    s3://<bucket>/models/qwen-finetuned/model.tar.gz
    Set MODEL_DATA_URI to this URI before deploying SageMaker.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    --download-only)
      DOWNLOAD_ONLY=true
      shift
      ;;
    --package-only)
      PACKAGE_ONLY=true
      shift
      ;;
    --push-only)
      PUSH_ONLY=true
      shift
      ;;
    --resume)
      RESUME=true
      shift
      ;;
    --force-redownload)
      FORCE_REDOWNLOAD=true
      shift
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

cd "${REPO_ROOT}"

if [[ -f "${REPO_ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
fi

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo "ERROR: No Python found. Create a venv:  uv venv && uv pip install gdown boto3"
  exit 1
fi

if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
  echo "ERROR: Missing ${PYTHON_SCRIPT}"
  exit 1
fi

_run() {
  echo ""
  echo "==> $*"
  echo ""
  "${PYTHON}" "${PYTHON_SCRIPT}" "$@"
}

DL_ARGS=()
[[ "${RESUME}" == true ]] && DL_ARGS+=(--resume)
[[ "${FORCE_REDOWNLOAD}" == true ]] && DL_ARGS+=(--force-redownload)

if [[ "${DOWNLOAD_ONLY}" == true ]]; then
  _run download "${DL_ARGS[@]}" "${EXTRA_ARGS[@]}"
elif [[ "${PACKAGE_ONLY}" == true ]]; then
  _run package "${EXTRA_ARGS[@]}"
elif [[ "${PUSH_ONLY}" == true ]]; then
  _run push "${EXTRA_ARGS[@]}"
else
  _run download "${DL_ARGS[@]}"
  _run package
  _run push
fi

echo ""
echo "Done. Model artifact is in S3."
echo "Next: ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy"
