#!/usr/bin/env bash
#
# provision-rag-eng-stack.sh
#
# Describe or provision the AWS stack for the rag_eng online orchestrator.
#
# Usage (from repo root):
#   ./deploy/scripts/provision-rag-eng-stack.sh describe
#   ./deploy/scripts/provision-rag-eng-stack.sh apply
#   ./deploy/scripts/provision-rag-eng-stack.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/provision_rag_eng_stack.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

ACTION=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
provision-rag-eng-stack.sh

  Describe or provision the AWS stack for the rag_eng online orchestrator.

  Actions:
    describe  Print the resolved stack wiring and missing values.
    apply     Create/update the AWS resources, build the image, and deploy ECS.

  Prerequisites:
    - AWS credentials with permission to create ECS, ECR, ELBv2, IAM, S3, and Secrets Manager resources
    - Docker installed locally for the image build/push step
    - deployment.yaml populated with the shared network/settings inputs

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
    RAG_ENG_ECS_ALB_SECURITY_GROUP_ID
    RAG_ENG_ECS_SUBNETS
    RAG_ENG_ECS_SECURITY_GROUPS
    RAG_ENG_ECS_SECRET_ARNS_JSON

  Examples:
    ./deploy/scripts/provision-rag-eng-stack.sh describe
    ./deploy/scripts/provision-rag-eng-stack.sh apply
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    describe|apply)
      ACTION="$1"
      shift
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${ACTION}" ]]; then
  echo "ERROR: Missing action. Use: describe | apply"
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
ARGS+=("${EXTRA_ARGS[@]}")

echo ""
echo "==> rag_eng stack"
echo "    Repo:     ${REPO_ROOT}"
echo "    Config:   ${DEPLOY_CONFIG_PATH}"
echo "    Region:   ${DEPLOY_AWS_REGION}"
echo "    Cluster:  ${DEPLOY_RAG_ENG_ECS_CLUSTER}"
echo "    Service:  ${DEPLOY_RAG_ENG_ECS_SERVICE_NAME}"
echo "    Target:   ${DEPLOY_RAG_ENG_ECS_TARGET_GROUP_ARN:-'(missing)'}"
echo ""

exec "${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"
