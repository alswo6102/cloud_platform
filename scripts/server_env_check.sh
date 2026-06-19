#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

if ssh_base "echo connected" >/dev/null; then
  ok "ssh"
else
  fail "ssh_auth_or_connection"
fi

ssh_base "command -v python3 >/dev/null" && ok "python3" || fail "python3_missing"
ssh_base "command -v docker >/dev/null" && ok "docker_cli" || fail "docker_missing"

if ssh_base "docker compose version >/dev/null 2>&1 || docker-compose --version >/dev/null 2>&1"; then
  ok "docker_compose"
else
  fail "docker_compose_missing"
fi

if ssh_base "docker ps >/dev/null 2>&1"; then
  ok "docker_access"
else
  fail "docker_access_denied"
fi

ssh_base "mkdir -p '$REMOTE_DIR' '$REMOTE_PROJECTS_ROOT'" && ok "remote_dirs"
