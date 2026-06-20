#!/usr/bin/env bash
#
# deploy-ingestion-worker.sh
#
# Describe, render, or register the ECS task definition used by the ingestion
# worker. This is the repo-side helper for the on-demand Fargate worker.
#
# Usage (from repo root):
#   ./deploy/scripts/deploy-ingestion-worker.sh describe
#   ./deploy/scripts/deploy-ingestion-worker.sh render-task-definition
#   ./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
#   ./deploy/scripts/deploy-ingestion-worker.sh register-task-definition
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/deploy_ingestion_worker.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

ACTION=""
OUTPUT_PATH=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
deploy-ingestion-worker.sh

  Describe, render, or register the ECS ingestion worker task definition.

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
    Worker-specific settings live in INGESTION_ECS_* env vars.

  Useful env vars:
    INGESTION_ECS_IMAGE_URI
    INGESTION_ECS_EXECUTION_ROLE_ARN
    INGESTION_ECS_TASK_ROLE_ARN
    INGESTION_ECS_TASK_FAMILY
    INGESTION_ECS_TASK_DEFINITION
    INGESTION_ECS_CONTAINER_NAME
    INGESTION_ECS_SUBNETS
    INGESTION_ECS_SECURITY_GROUPS
    INGESTION_ECS_SECRET_ARNS_JSON

  Examples:
    ./deploy/scripts/deploy-ingestion-worker.sh describe
    ./deploy/scripts/deploy-ingestion-worker.sh render-task-definition
    ./deploy/scripts/deploy-ingestion-worker.sh render-backend-env
    ./deploy/scripts/deploy-ingestion-worker.sh register-task-definition
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

cd "${REPO_ROOT}"

ARGS=("${ACTION}")
if [[ -n "${OUTPUT_PATH}" ]]; then
  ARGS+=(--output "${OUTPUT_PATH}")
fi
ARGS+=("${EXTRA_ARGS[@]}")

echo ""
echo "==> ECS ingestion worker"
echo "    Repo:     ${REPO_ROOT}"
echo "    Config:   ${DEPLOY_CONFIG_PATH}"
echo "    Region:   ${DEPLOY_AWS_REGION}"
echo "    Bucket:   ${DEPLOY_S3_BUCKET}"
echo ""

exec "${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"
