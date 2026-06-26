#!/usr/bin/env bash
#
# provision-frontend-stack.sh
#
# Describe or provision the frontend S3 + CloudFront stack.
#
# Usage (from repo root):
#   ./deploy/scripts/provision-frontend-stack.sh describe
#   ./deploy/scripts/provision-frontend-stack.sh apply
#   ./deploy/scripts/provision-frontend-stack.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/provision_frontend_stack.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

ACTION=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
provision-frontend-stack.sh

  Describe or provision the frontend S3 + CloudFront stack.

  Actions:
    describe  Print the resolved frontend infra settings and missing values.
    apply     Create/update the frontend S3 bucket and CloudFront distribution.

  Prerequisites:
    - AWS credentials with permission to create S3 and CloudFront resources
    - deployment.yaml populated with the rag_eng ALB target group ARN
    - the existing rag_eng ALB/service deployed in AWS

  Configuration:
    .env and deploy/deployment.yaml are loaded automatically.
    The provisioner will derive a bucket name if none is configured yet.

  Useful env vars:
    FRONTEND_ENABLED
    FRONTEND_APP_DIR
    FRONTEND_BUCKET_NAME
    FRONTEND_CLOUDFRONT_DISTRIBUTION_ID
    FRONTEND_CLOUDFRONT_ALIASES
    FRONTEND_CLOUDFRONT_CERTIFICATE_ARN
    FRONTEND_CLOUDFRONT_INVALIDATION_PATHS

  Examples:
    ./deploy/scripts/provision-frontend-stack.sh describe
    ./deploy/scripts/provision-frontend-stack.sh apply
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
echo "==> frontend infrastructure"
echo "    Repo:        ${REPO_ROOT}"
echo "    Config:      ${DEPLOY_CONFIG_PATH}"
echo "    Region:      ${DEPLOY_AWS_REGION}"
echo "    Bucket:      ${DEPLOY_FRONTEND_BUCKET_NAME:-'(auto-generate)'}"
echo "    Dist ID:     ${DEPLOY_FRONTEND_CLOUDFRONT_DISTRIBUTION_ID:-'(missing)'}"
echo "    Target group: ${DEPLOY_RAG_ENG_ECS_TARGET_GROUP_ARN:-'(missing)'}"
echo ""

exec "${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"
