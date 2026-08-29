#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

load_env() {
  if [[ -f "$ROOT_DIR/.env.local" ]]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.env.local"
  fi

  : "${NCP_HOST:?NCP_HOST is required. Copy .env.example to .env.local.}"
  : "${NCP_USER:?NCP_USER is required.}"
  : "${NCP_PORT:=22}"
  : "${NCP_AUTH_METHOD:=password}"
  : "${REMOTE_DIR:=/opt/cloud_platform}"
  : "${REMOTE_PROJECTS_ROOT:=/srv/projects}"
  : "${REMOTE_AGENT_NAME:=cloud-platform-skill-agent}"
  : "${REMOTE_WEB_NAME:=cloud-platform-web-api}"
  : "${REMOTE_WEB_PORT:=8000}"

  if [[ "$NCP_AUTH_METHOD" == "key" ]]; then
    : "${NCP_SSH_KEY:?NCP_SSH_KEY is required when NCP_AUTH_METHOD=key.}"
  elif [[ "$NCP_AUTH_METHOD" == "password" ]]; then
    : "${NCP_PASSWORD:?NCP_PASSWORD is required when NCP_AUTH_METHOD=password.}"
  else
    echo "FAIL invalid_auth_method"
    exit 1
  fi
}

ssh_target() {
  echo "${NCP_USER}@${NCP_HOST}"
}

ssh_base() {
  if [[ "$NCP_AUTH_METHOD" == "key" ]]; then
    ssh -i "$NCP_SSH_KEY" -p "$NCP_PORT" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new \
      "$(ssh_target)" "$@"
  else
    NCP_PASSWORD="$NCP_PASSWORD" \
    SSH_ASKPASS="$ROOT_DIR/scripts/ssh_askpass.sh" \
    SSH_ASKPASS_REQUIRE=force \
    DISPLAY=codex \
    ssh -p "$NCP_PORT" \
      -o PreferredAuthentications=password \
      -o PubkeyAuthentication=no \
      -o StrictHostKeyChecking=accept-new \
      "$(ssh_target)" "$@"
  fi
}

# rsync mirrors REMOTE_DIR with --delete, so anything the server holds and the
# working copy does not is destroyed on every deploy. Two kinds of path have to
# survive that: state the platform owns (accounts, runtime configuration) and
# state the operator's tooling owns. node_modules is excluded from the other
# direction too -- 109MB of host-specific binaries that the server cannot build
# with anyway, on a disk that runs at 89% full.
RSYNC_EXCLUDES=(
  ".git/"
  ".idea/"
  ".DS_Store"
  "__pycache__/"
  ".pytest_cache/"
  ".ruff_cache/"
  "node_modules/"
  ".env.local"
  ".agent.env"
  ".agent.env.bak.*"
  ".platform.env"
  "data/"
  "output/"
  ".claude/"
  ".codex"
  ".codex_refs/"
  ".agents/"
  ".impeccable/"
)

rsync_exclude_args() {
  local pattern
  for pattern in "${RSYNC_EXCLUDES[@]}"; do
    printf -- '--exclude\n%s\n' "$pattern"
  done
}

rsync_base() {
  local ssh_cmd
  local -a exclude_args=()
  while IFS= read -r line; do
    exclude_args+=("$line")
  done < <(rsync_exclude_args)
  if [[ "$NCP_AUTH_METHOD" == "key" ]]; then
    ssh_cmd="ssh -i $NCP_SSH_KEY -p $NCP_PORT -o StrictHostKeyChecking=accept-new"
    rsync -az --delete \
      "${exclude_args[@]}" \
      -e "$ssh_cmd" \
      "$@"
  else
    ssh_cmd="ssh -p $NCP_PORT -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new"
    NCP_PASSWORD="$NCP_PASSWORD" \
    SSH_ASKPASS="$ROOT_DIR/scripts/ssh_askpass.sh" \
    SSH_ASKPASS_REQUIRE=force \
    DISPLAY=codex \
    rsync -az --delete \
      "${exclude_args[@]}" \
      -e "$ssh_cmd" \
      "$@"
  fi
}

ok() {
  printf 'OK %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1"
  exit 1
}
