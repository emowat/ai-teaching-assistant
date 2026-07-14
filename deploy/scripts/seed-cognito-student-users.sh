#!/usr/bin/env bash
#
# seed-cognito-student-users.sh
#
# Create or update a fixed set of student test users in Cognito, add them to the
# Students group, and seed matching Aurora application users plus section
# memberships for extension/bootstrap testing.
#
# Usage (from repo root):
#   AWS_PROFILE=codingrabbit-dev AWS_REGION=us-east-1 ./deploy/scripts/seed-cognito-student-users.sh
#
# Optional overrides:
#   SECTION_ID=mit14-extension-student-smoke
#   TEMP_PASSWORD='StudentPass#12345'
#   USER_POOL_ID=us-east-1_...
#   STUDENT_GROUP=Students
#   AURORA_COURSE_REGISTRY_RESOURCE_ARN=...
#   AURORA_COURSE_REGISTRY_SECRET_ARN=...
#   AURORA_COURSE_REGISTRY_DATABASE=postgres
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

require_var() {
  local name="$1"
  local value="${!name:-}"
  if [[ -z "${value}" ]]; then
    echo "ERROR: ${name} is required."
    exit 1
  fi
}

sql_quote() {
  local value="$1"
  value="${value//\'/\'\'}"
  printf "%s" "${value}"
}

lookup_cognito_username() {
  local email="$1"
  aws cognito-idp list-users \
    --user-pool-id "${USER_POOL_ID}" \
    --filter "email = \"${email}\"" \
    --query 'Users[0].Username' \
    --output text 2>/dev/null || true
}

lookup_cognito_sub() {
  local email="$1"
  local sub=""
  for _ in 1 2 3 4 5; do
    sub="$(aws cognito-idp list-users \
      --user-pool-id "${USER_POOL_ID}" \
      --filter "email = \"${email}\"" \
      --query 'Users[0].Attributes[?Name==`sub`].Value | [0]' \
      --output text 2>/dev/null || true)"
    if [[ -n "${sub}" && "${sub}" != "None" ]]; then
      printf "%s" "${sub}"
      return 0
    fi
    sleep 1
  done

  echo "ERROR: Unable to resolve Cognito sub for ${email}." >&2
  exit 1
}

ensure_section_exists() {
  local section_id="$1"
  local resource_arn="$2"
  local secret_arn="$3"
  local database="$4"

  local found
  found="$(aws rds-data execute-statement \
    --resource-arn "${resource_arn}" \
    --secret-arn "${secret_arn}" \
    --database "${database}" \
    --sql "SELECT section_id FROM sections WHERE section_id = '${section_id}';" \
    --query 'records[0][0].stringValue' \
    --output text 2>/dev/null || true)"

  if [[ -z "${found}" || "${found}" == "None" ]]; then
    echo "ERROR: Section ${section_id} does not exist in Aurora." >&2
    exit 1
  fi
}

USER_POOL_ID="${USER_POOL_ID:-${COGNITO_USER_POOL_ID:-}}"
STUDENT_GROUP="${STUDENT_GROUP:-Students}"
SECTION_ID="${SECTION_ID:-mit14-extension-student-smoke}"
TEMP_PASSWORD="${TEMP_PASSWORD:-StudentPass#12345}"
AURORA_COURSE_REGISTRY_DATABASE="${AURORA_COURSE_REGISTRY_DATABASE:-postgres}"

require_var USER_POOL_ID
require_var AURORA_COURSE_REGISTRY_RESOURCE_ARN
require_var AURORA_COURSE_REGISTRY_SECRET_ARN
require_var AWS_REGION

declare -A DISPLAY_NAMES=(
  [koreenpaterson@gmail.com]="Koreen Paterson"
  [asherrera@csumb.edu]="Ash Herrera"
  [kevinguan9696@hotmail.com]="Kevin Guan"
  [jonluke.mowat@gmail.com]="Jonluke Mowat"
  [ericmowat@gmail.com]="Eric Mowat"
  [joyceshen@berkeley.edu]="Joyce Shen"
  [korinreid@berkeley.edu]="Korin Reid"
  [student_t_distribution@berkeley.edu]="Student T Distribution"
  [student_lambda@berkeley.edu]="Student Lambda"
  [student_iterator@berkeley.edu]="Student Iterator"
)

EMAILS=(
  koreenpaterson@gmail.com
  asherrera@csumb.edu
  kevinguan9696@hotmail.com
  jonluke.mowat@gmail.com
  ericmowat@gmail.com
  joyceshen@berkeley.edu
  korinreid@berkeley.edu
  student_t_distribution@berkeley.edu
  student_lambda@berkeley.edu
  student_iterator@berkeley.edu
)

SQL_FILE="$(mktemp "${TMPDIR:-/tmp}/seed_students.XXXXXX.sql")"
cleanup() {
  rm -f "${SQL_FILE}"
}
trap cleanup EXIT

echo "Checking Aurora section ${SECTION_ID}..."
ensure_section_exists \
  "${SECTION_ID}" \
  "${AURORA_COURSE_REGISTRY_RESOURCE_ARN}" \
  "${AURORA_COURSE_REGISTRY_SECRET_ARN}" \
  "${AURORA_COURSE_REGISTRY_DATABASE}"

: > "${SQL_FILE}"

for email in "${EMAILS[@]}"; do
  display_name="${DISPLAY_NAMES[${email}]}"

  username="$(lookup_cognito_username "${email}")"
  if [[ -z "${username}" || "${username}" == "None" ]]; then
    echo "Creating Cognito user ${email}..."
    aws cognito-idp admin-create-user \
      --user-pool-id "${USER_POOL_ID}" \
      --username "${email}" \
      --user-attributes Name=email,Value="${email}" Name=email_verified,Value=true \
      --message-action SUPPRESS >/dev/null
    username="${email}"
  else
    echo "Updating existing Cognito user ${email}..."
  fi

  aws cognito-idp admin-set-user-password \
    --user-pool-id "${USER_POOL_ID}" \
    --username "${username}" \
    --password "${TEMP_PASSWORD}" \
    --permanent >/dev/null

  aws cognito-idp admin-add-user-to-group \
    --user-pool-id "${USER_POOL_ID}" \
    --username "${username}" \
    --group-name "${STUDENT_GROUP}" >/dev/null

  cognito_sub="$(lookup_cognito_sub "${email}")"
  safe_email="$(sql_quote "${email}")"
  safe_display_name="$(sql_quote "${display_name}")"
  safe_section_id="$(sql_quote "${SECTION_ID}")"
  safe_cognito_sub="$(sql_quote "${cognito_sub}")"

  cat >> "${SQL_FILE}" <<SQL
WITH upsert_user AS (
  INSERT INTO users (email, display_name, primary_role, status, cognito_sub)
  VALUES ('${safe_email}', '${safe_display_name}', 'student', 'active', '${safe_cognito_sub}')
  ON CONFLICT (email) DO UPDATE
    SET display_name = EXCLUDED.display_name,
        primary_role = 'student',
        status = 'active',
        cognito_sub = EXCLUDED.cognito_sub,
        updated_at = now()
  RETURNING user_id
)
INSERT INTO section_memberships (section_id, user_id, role_in_section, status)
SELECT '${safe_section_id}', user_id, 'student', 'active'
FROM upsert_user
ON CONFLICT (section_id, user_id) DO UPDATE
  SET role_in_section = 'student',
      status = 'active',
      updated_at = now();
SQL

  echo "Prepared Aurora seed for ${email}"
done

echo "Applying Aurora seed rows..."
"${PYTHON}" "${PYTHON_SCRIPT}" apply \
  --resource-arn "${AURORA_COURSE_REGISTRY_RESOURCE_ARN}" \
  --secret-arn "${AURORA_COURSE_REGISTRY_SECRET_ARN}" \
  --database "${AURORA_COURSE_REGISTRY_DATABASE}" \
  --sql-file "${SQL_FILE}"

echo "Done. Seeded Cognito group ${STUDENT_GROUP} and Aurora section ${SECTION_ID}."
