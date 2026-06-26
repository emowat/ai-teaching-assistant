#!/bin/sh
#
# rag-eng-startup.sh
#
# ECS entrypoint for the rag_eng orchestrator.
# Restores the input and output guardrail checkpoints from S3, then starts
# uvicorn.
#
set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  echo "ERROR: No Python found on PATH." >&2
  exit 1
fi

echo "==> restoring input guardrail checkpoint"
"${PYTHON}" "${REPO_ROOT}/deploy/restore_input_guardrail_checkpoint.py" &
INPUT_RESTORE_PID=$!

echo "==> restoring output guardrail checkpoint"
"${PYTHON}" "${REPO_ROOT}/deploy/restore_guardrail_checkpoint.py" &
OUTPUT_RESTORE_PID=$!

INPUT_RESTORE_STATUS=0
OUTPUT_RESTORE_STATUS=0
wait "${INPUT_RESTORE_PID}" || INPUT_RESTORE_STATUS=$?
wait "${OUTPUT_RESTORE_PID}" || OUTPUT_RESTORE_STATUS=$?

if [ "${INPUT_RESTORE_STATUS}" -ne 0 ] || [ "${OUTPUT_RESTORE_STATUS}" -ne 0 ]; then
  echo "ERROR: Guardrail checkpoint restore failed." >&2
  exit 1
fi

APP_PORT="${APP_PORT:-8001}"
echo "==> starting rag_eng on port ${APP_PORT}"
exec "${PYTHON}" -m uvicorn rag_eng.main:app \
  --host 0.0.0.0 \
  --port "${APP_PORT}" \
  --proxy-headers \
  --forwarded-allow-ips '*'
