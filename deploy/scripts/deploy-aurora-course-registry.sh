#!/usr/bin/env bash
#
# deploy-aurora-course-registry.sh
#
# Bootstrap the Aurora PostgreSQL course registry schema and seed rows.
#
# Usage (from repo root):
#   ./deploy/scripts/deploy-aurora-course-registry.sh apply \
#     --resource-arn arn:aws:rds:...:cluster:... \
#     --secret-arn arn:aws:secretsmanager:...:secret:... \
#     --region us-east-1 \
#     --profile codingrabbit-dev
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/deploy_aurora_course_registry.py"

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
  echo "ERROR: No Python found. Create a venv: uv venv && uv pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "${PYTHON_SCRIPT}" ]]; then
  echo "ERROR: Missing ${PYTHON_SCRIPT}"
  exit 1
fi

cd "${REPO_ROOT}"
exec "${PYTHON}" "${PYTHON_SCRIPT}" "$@"
