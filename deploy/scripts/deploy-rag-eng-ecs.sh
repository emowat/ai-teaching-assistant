#!/usr/bin/env bash
#
# deploy-rag-eng-ecs.sh
#
# Describe, render, or deploy the ECS service for the rag_eng orchestrator.
#
# Usage (from repo root):
#   ./deploy/scripts/deploy-rag-eng-ecs.sh describe
#   ./deploy/scripts/deploy-rag-eng-ecs.sh render-task-definition
#   ./deploy/scripts/deploy-rag-eng-ecs.sh render-service-spec
#   ./deploy/scripts/deploy-rag-eng-ecs.sh register-task-definition
#   ./deploy/scripts/deploy-rag-eng-ecs.sh deploy
#   ./deploy/scripts/deploy-rag-eng-ecs.sh status
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/deploy_rag_eng_ecs.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

ACTION=""
OUTPUT_PATH=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
deploy-rag-eng-ecs.sh

  Describe, render, register, or deploy the rag_eng ECS/Fargate service.

  Actions:
    describe               Print the resolved ECS service wiring and missing values.
    render-task-definition  Emit the ECS task definition JSON to stdout.
    render-service-spec     Emit the ECS service spec JSON to stdout.
    register-task-definition
                           Register the task definition with ECS via boto3.
    deploy                  Register the task definition and create/update the service.
    status                  Print the current ECS service status.

  Prerequisites:
    - Orchestrator image already pushed to ECR
    - ECS execution role ARN and task role ARN
    - ALB target group ARN and ECS networking values
    - AWS CLI profile or default credentials

  Options forwarded to the Python helper:
    --region REGION    AWS region for ECS calls
    --profile PROFILE   AWS profile for boto3
    --output PATH      Write rendered JSON to a file
    --config PATH      Alternative deploy/deployment.yaml path

  Configuration:
    .env and deploy/deployment.yaml are loaded automatically.
    rag_eng-specific settings live in rag_eng_ecs under deploy/deployment.yaml.

  Useful env vars:
    RAG_ENG_ECS_CLUSTER
    RAG_ENG_ECS_SERVICE_NAME
    RAG_ENG_ECS_TASK_FAMILY
    RAG_ENG_ECS_TASK_DEFINITION
    RAG_ENG_ECS_CONTAINER_NAME
    RAG_ENG_ECS_TARGET_GROUP_ARN
    RAG_ENG_ECS_SUBNETS
    RAG_ENG_ECS_SECURITY_GROUPS
    RAG_ENG_ECS_SECRET_ARNS_JSON

  Examples:
    ./deploy/scripts/deploy-rag-eng-ecs.sh describe
    ./deploy/scripts/deploy-rag-eng-ecs.sh render-task-definition
    ./deploy/scripts/deploy-rag-eng-ecs.sh render-service-spec
    ./deploy/scripts/deploy-rag-eng-ecs.sh register-task-definition
    ./deploy/scripts/deploy-rag-eng-ecs.sh deploy
    ./deploy/scripts/deploy-rag-eng-ecs.sh status
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    describe|render-task-definition|render-service-spec|register-task-definition|deploy|status)
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
  echo "ERROR: Missing action. Use: describe | render-task-definition | render-service-spec | register-task-definition | deploy | status"
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
echo "==> rag_eng ECS service"
echo "    Repo:     ${REPO_ROOT}"
echo "    Config:   ${DEPLOY_CONFIG_PATH}"
echo "    Region:   ${DEPLOY_AWS_REGION}"
echo "    Cluster:  ${DEPLOY_RAG_ENG_ECS_CLUSTER}"
echo "    Service:  ${DEPLOY_RAG_ENG_ECS_SERVICE_NAME}"
echo "    Target:   ${DEPLOY_RAG_ENG_ECS_TARGET_GROUP_ARN:-'(missing)'}"
echo ""

exec "${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"
