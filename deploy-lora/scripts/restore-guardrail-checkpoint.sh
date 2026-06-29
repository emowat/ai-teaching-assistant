#!/usr/bin/env bash
#
# restore-guardrail-checkpoint.sh
#
# Download the fine-tuned CodeBERT guardrail checkpoint from S3 and
# extract it into the local Hugging Face checkpoint directory used by
# output_guardrails/semantic_guardrail.py.
#
# Usage:
#   ./deploy/scripts/restore-guardrail-checkpoint.sh
#   ./deploy/scripts/restore-guardrail-checkpoint.sh --help
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
PYTHON_SCRIPT="${REPO_ROOT}/deploy/restore_guardrail_checkpoint.py"

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
"${PYTHON}" "${PYTHON_SCRIPT}" "$@"

