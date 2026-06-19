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
  : "${REMOTE_APP:=admin.py}"
  : "${REMOTE_PORT:=8501}"
  : "${REMOTE_PROJECTS_ROOT:=/srv/projects}"
  : "${REMOTE_SERVICE_NAME:=cloud-platform-dashboard}"

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

rsync_base() {
  local ssh_cmd
  if [[ "$NCP_AUTH_METHOD" == "key" ]]; then
    ssh_cmd="ssh -i $NCP_SSH_KEY -p $NCP_PORT -o StrictHostKeyChecking=accept-new"
    rsync -az --delete \
      --exclude ".git/" \
      --exclude ".idea/" \
      --exclude ".env.local" \
      --exclude ".DS_Store" \
      --exclude "__pycache__/" \
      --exclude ".pytest_cache/" \
      --exclude ".ruff_cache/" \
      -e "$ssh_cmd" \
      "$@"
  else
    ssh_cmd="ssh -p $NCP_PORT -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=accept-new"
    NCP_PASSWORD="$NCP_PASSWORD" \
    SSH_ASKPASS="$ROOT_DIR/scripts/ssh_askpass.sh" \
    SSH_ASKPASS_REQUIRE=force \
    DISPLAY=codex \
    rsync -az --delete \
      --exclude ".git/" \
      --exclude ".idea/" \
      --exclude ".env.local" \
      --exclude ".DS_Store" \
      --exclude "__pycache__/" \
      --exclude ".pytest_cache/" \
      --exclude ".ruff_cache/" \
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
