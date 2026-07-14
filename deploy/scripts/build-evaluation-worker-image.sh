#!/usr/bin/env bash
#
# build-evaluation-worker-image.sh
#
# Build and push the dedicated ECR image for the offline evaluation worker.
#
# Usage (from repo root):
#   ./deploy/scripts/build-evaluation-worker-image.sh
#   ./deploy/scripts/build-evaluation-worker-image.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/evaluation_worker_image.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

EXTRA_ARGS=()

usage() {
  cat <<'EOF'
build-evaluation-worker-image.sh

  Build and push the dedicated ECR image for the offline evaluation worker.

  The build context is staged automatically with only the worker-safe Python
  sources. The image is pushed to the worker ECR repository configured in the
  deployment environment.

  Configuration:
    .env and deploy/deployment.yaml are loaded automatically.
    AWS_REGION / AWS_PROFILE can also be passed as CLI flags.

  Useful env vars:
    EVALUATION_WORKER_ECR_REPOSITORY
    EVALUATION_WORKER_ECR_IMAGE_TAG

  Examples:
    ./deploy/scripts/build-evaluation-worker-image.sh
    ./deploy/scripts/build-evaluation-worker-image.sh --repository-name codingrabbit-evaluation-worker --tag latest
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

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

echo ""
echo "==> evaluation worker image"
echo "    Repo:     ${REPO_ROOT}"
echo "    Config:   ${DEPLOY_CONFIG_PATH}"
echo "    Region:   ${DEPLOY_AWS_REGION}"
echo ""

ARGS=(--region "${DEPLOY_AWS_REGION}")
if [[ -n "${DEPLOY_AWS_PROFILE:-}" ]]; then
  ARGS+=(--profile "${DEPLOY_AWS_PROFILE}")
fi
ARGS+=("${EXTRA_ARGS[@]}")

exec "${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"
