#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

if ssh_base "docker inspect -f '{{.State.Running}}' '$REMOTE_SERVICE_NAME' 2>/dev/null | grep -qx true"; then
  ok "dashboard_container"
else
  fail "dashboard_container"
fi

if ssh_base "curl -fsS 'http://127.0.0.1:$REMOTE_PORT/_stcore/health' >/dev/null"; then
  ok "streamlit_health"
else
  fail "streamlit_health"
fi

if ssh_base "test -d '$REMOTE_PROJECTS_ROOT'"; then
  ok "projects_root"
else
  fail "projects_root"
fi

if ssh_base "docker exec '$REMOTE_SERVICE_NAME' docker ps >/dev/null"; then
  ok "dashboard_docker_access"
else
  fail "dashboard_docker_access"
fi
