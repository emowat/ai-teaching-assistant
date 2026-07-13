#!/usr/bin/env bash
#
# deploy-evaluation-worker.sh
#
# Describe, render, or register the ECS task definition used by the offline
# evaluation worker. This mirrors the ingestion worker helper.
#
# Usage (from repo root):
#   ./deploy/scripts/deploy-evaluation-worker.sh describe
#   ./deploy/scripts/deploy-evaluation-worker.sh render-task-definition
#   ./deploy/scripts/deploy-evaluation-worker.sh render-backend-env
#   ./deploy/scripts/deploy-evaluation-worker.sh register-task-definition
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/deploy_evaluation_worker.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

ACTION=""
OUTPUT_PATH=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
deploy-evaluation-worker.sh

  Describe, render, or register the ECS evaluation worker task definition.

  Actions:
    describe               Print the resolved ECS/task wiring and missing values.
    render-task-definition  Emit the ECS task definition JSON to stdout.
    render-backend-env      Emit the backend .env fragment for ECS launch config.
    register-task-definition
                            Register the task definition with ECS via boto3.

  Prerequisites:
    - Worker image already pushed to ECR
    - ECS execution role ARN and task role ARN
    - Worker runtime env / secret ARN mappings
    - AWS CLI profile or default credentials

  Options forwarded to the Python helper:
    --region REGION    AWS region for ECS registration
    --profile PROFILE   AWS profile for boto3
    --output PATH      Write rendered JSON or env fragment to a file

  Configuration:
    .env and deploy/deployment.yaml are loaded automatically.
    Worker-specific settings live in EVALUATION_WORKER_* env vars.

  Useful env vars:
    EVALUATION_WORKER_ECS_IMAGE_URI
    EVALUATION_WORKER_ECS_EXECUTION_ROLE_ARN
    EVALUATION_WORKER_ECS_TASK_ROLE_ARN
    EVALUATION_WORKER_ECS_TASK_FAMILY
    EVALUATION_WORKER_ECS_TASK_DEFINITION
    EVALUATION_WORKER_ECS_CONTAINER_NAME
    EVALUATION_WORKER_ECS_SUBNETS
    EVALUATION_WORKER_ECS_SECURITY_GROUPS
    EVALUATION_WORKER_ECS_SECRET_ARNS_JSON

  Examples:
    ./deploy/scripts/deploy-evaluation-worker.sh describe
    ./deploy/scripts/deploy-evaluation-worker.sh render-task-definition
    ./deploy/scripts/deploy-evaluation-worker.sh render-backend-env
    ./deploy/scripts/deploy-evaluation-worker.sh register-task-definition
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    describe|render-task-definition|render-backend-env|register-task-definition)
      ACTION="$1"
      shift
      ;;
    --output)
      OUTPUT_PATH="$2"
      shift 2
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${ACTION}" ]]; then
  echo "ERROR: Missing action. Use: describe | render-task-definition | render-backend-env | register-task-definition"
  echo "Run with --help for details."
  exit 1
fi

if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PYTHON="${REPO_ROOT}/.venv/bin/python"
elif command -v python3 &>/dev/null; then
  PYTHON="python3"
else
  echo "ERROR: No Python found. Create a venv: uv venv && uv pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
  echo "ERROR: Missing ${PYTHON_SCRIPT}"
  exit 1
fi

load_deploy_config "${REPO_ROOT}" "${PYTHON}"
cd "${REPO_ROOT}"

ARGS=("${ACTION}")
if [[ -n "${OUTPUT_PATH}" ]]; then
  ARGS+=(--output "${OUTPUT_PATH}")
fi
ARGS+=("${EXTRA_ARGS[@]}")

echo ""
echo "==> ECS evaluation worker"
echo "    Repo:     ${REPO_ROOT}"
echo "    Config:   ${DEPLOY_CONFIG_PATH}"
echo "    Region:   ${DEPLOY_AWS_REGION}"
echo "    Bucket:   ${DEPLOY_S3_BUCKET}"
echo ""

exec "${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"
