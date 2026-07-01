# Shared helper — source from deploy/scripts/*.sh
# shellcheck shell=bash

load_deploy_config() {
  local repo_root="$1"
  local python_bin="$2"
  local config_helper="${repo_root}/deploy/deployment_config.py"

  if [[ -z "${PYTHON_CMD:-}" ]]; then
    if command -v uv >/dev/null 2>&1; then
      PYTHON_CMD="uv run python"
    else
      PYTHON_CMD="python"
    fi
  fi

  if [[ ! -f "${config_helper}" ]]; then
    echo "ERROR: Missing ${config_helper}"
    exit 1
  fi

  if [[ -f "${repo_root}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${repo_root}/.env"
    set +a
  fi

  eval "$(${python_bin} "${config_helper}" shell-export)"
}
