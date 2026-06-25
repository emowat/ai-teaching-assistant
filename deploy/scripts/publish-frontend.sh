#!/usr/bin/env bash
#
# publish-frontend.sh
#
# Build and publish the frontend static bundle to S3, then invalidate CloudFront.
#
# Usage (from repo root):
#   ./deploy/scripts/publish-frontend.sh describe
#   ./deploy/scripts/publish-frontend.sh publish
#   ./deploy/scripts/publish-frontend.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/publish_frontend.py"
# shellcheck source=deploy/scripts/_load_deploy_config.sh
source "${SCRIPT_DIR}/_load_deploy_config.sh"

ACTION=""
EXTRA_ARGS=()

usage() {
  cat <<'EOF'
publish-frontend.sh

  Build and publish the frontend static bundle to S3, then invalidate CloudFront.

  Actions:
    describe  Print the resolved frontend publish settings and missing values.
    publish   Build frontend/, sync frontend/dist/ to S3, and invalidate CloudFront.

  Prerequisites:
    - AWS credentials with permission to write to the frontend bucket and create CloudFront invalidations
    - Node.js/npm installed locally for the Vite build step
    - deployment.yaml populated with frontend_web settings

  Configuration:
    .env and deploy/deployment.yaml are loaded automatically.
    The S3 bucket and CloudFront distribution are managed separately from this helper.

  Useful env vars:
    FRONTEND_ENABLED
    FRONTEND_APP_DIR
    FRONTEND_DIST_DIR
    FRONTEND_BUCKET_NAME
    FRONTEND_BUCKET_PREFIX
    FRONTEND_CLOUDFRONT_DISTRIBUTION_ID
    FRONTEND_CLOUDFRONT_INVALIDATION_PATHS
    FRONTEND_CLOUDFRONT_API_PATH_PATTERNS
    VITE_API_BASE_URL
    VITE_COGNITO_DOMAIN
    VITE_COGNITO_REDIRECT_URI
    VITE_COGNITO_LOGOUT_URI

  Examples:
    ./deploy/scripts/publish-frontend.sh describe
    ./deploy/scripts/publish-frontend.sh publish
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help|-h)
      usage
      exit 0
      ;;
    describe|publish)
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
  echo "ERROR: Missing action. Use: describe | publish"
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
echo "==> frontend publish"
echo "    Repo:        ${REPO_ROOT}"
echo "    Config:      ${DEPLOY_CONFIG_PATH}"
echo "    Region:      ${DEPLOY_AWS_REGION}"
echo "    Bucket:      ${DEPLOY_FRONTEND_BUCKET_NAME:-'(missing)'}"
echo "    Prefix:      ${DEPLOY_FRONTEND_BUCKET_PREFIX:-'(root)'}"
echo "    Dist ID:     ${DEPLOY_FRONTEND_CLOUDFRONT_DISTRIBUTION_ID:-'(missing)'}"
echo ""

exec "${PYTHON}" "${PYTHON_SCRIPT}" "${ARGS[@]}"
