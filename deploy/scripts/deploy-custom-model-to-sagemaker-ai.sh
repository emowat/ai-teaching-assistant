#!/usr/bin/env bash
#
# deploy-custom-model-to-sagemaker-ai.sh
#
# Create, test, inspect, or tear down a SageMaker Asynchronous Inference
# endpoint for the fine-tuned Qwen model uploaded to S3.
#
# This is step 2 of the CodingRabbit inference deployment pipeline.
# Requires prepare-custom-model-from-google-drive.sh to have completed first.
#
# Usage (from repo root):
#   ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy
#   ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh invoke
#   ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh status
#   ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh cleanup
#   ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/deploy_sagemaker.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

ACTION=""
ROLE_ARN=""
PROMPT=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
deploy-custom-model-to-sagemaker-ai.sh

  Step 2: Deploy the custom model to Amazon SageMaker AI (Async Inference).

  What this script does:
    deploy   — Create SageMaker Model + EndpointConfig + Async Endpoint
               Loads model from s3://<bucket>/models/qwen-finetuned/model.tar.gz
               Uses GPU instance (default ml.g5.2xlarge). Takes 5–15 minutes.
    invoke   — Smoke-test the endpoint (upload request to S3, poll for output)
    status   — Print endpoint state (Creating / InService / Failed)
    cleanup  — Delete endpoint, config, and model (stops GPU billing)

  Prerequisites:
    - Model already in S3 (run prepare-custom-model-from-google-drive.sh first)
    - SageMaker execution IAM role with S3 + SageMaker permissions
    - Python dep:  uv pip install boto3

  Usage:
    ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh deploy
    ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh invoke
    ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh status
    ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh cleanup

  Options:
    --role-arn ARN    SageMaker execution role (auto-detected if omitted)
    --prompt TEXT     Test prompt for invoke (default: C++ segfault question)
    --help            Show this message

  Configuration:
    deploy/deployment.yaml  — primary settings (see: python deploy/deployment_config.py describe)
    .env / env vars         — override YAML (SAGEMAKER_ENDPOINT, S3_DATA_BUCKET, …)

  After deploy succeeds, add to .env and restart rag_eng (values from deployment.yaml):
    USE_SAGEMAKER=true
    SAGEMAKER_ENDPOINT=<sagemaker.endpoint_name>
    MODEL_FAMILY=<rag_eng.model_family>
    S3_DATA_BUCKET=<aws.s3_bucket>

  Docs:
    https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    deploy|invoke|status|cleanup)
      ACTION="$1"
      shift
      ;;
    --role-arn)
      ROLE_ARN="$2"
      shift 2
      ;;
    --prompt)
      PROMPT="$2"
      shift 2
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${ACTION}" ]]; then
  echo "ERROR: Missing action. Use: deploy | invoke | status | cleanup"
  echo "Run with --help for details."
  exit 1
fi

cd "${REPO_ROOT}"

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo "ERROR: No Python found. Create a venv:  uv venv && uv pip install boto3 pyyaml"
  exit 1
fi

if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
  echo "ERROR: Missing ${PYTHON_SCRIPT}"
  exit 1
fi

load_deploy_config "${REPO_ROOT}" "${PYTHON}"

ARGS=("${ACTION}")
[[ -n "${ROLE_ARN}" ]] && ARGS+=(--role-arn "${ROLE_ARN}")
[[ -n "${PROMPT}" ]] && ARGS+=(--prompt "${PROMPT}")
ARGS+=("${EXTRA_ARGS[@]}")

echo ""
echo "==> SageMaker AI: ${ACTION}"
echo "    Repo:     ${REPO_ROOT}"
echo "    Config:   ${DEPLOY_CONFIG_PATH}"
echo "    Endpoint: ${DEPLOY_ENDPOINT_NAME}"
echo "    Region:   ${DEPLOY_AWS_REGION}"
echo "    Bucket:   ${DEPLOY_S3_BUCKET}"
echo "    Model:    ${DEPLOY_MODEL_DATA_URI}"
echo "    Instance: ${DEPLOY_INSTANCE_TYPE}"
echo ""

"${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"

case "${ACTION}" in
  deploy)
    echo ""
    echo "When status is InService, test with:"
    echo "  ./deploy/scripts/deploy-custom-model-to-sagemaker-ai.sh invoke"
  ;;
  cleanup)
    echo ""
    echo "Endpoint removed. S3 model artifact was NOT deleted."
  ;;
esac
