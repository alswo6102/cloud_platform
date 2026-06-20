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

if ssh_base "for attempt in \$(seq 1 30); do curl -fsS 'http://127.0.0.1:$REMOTE_PORT/_stcore/health' >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1"; then
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

if ssh_base "docker inspect -f '{{.State.Running}}' '$REMOTE_AGENT_NAME' 2>/dev/null | grep -qx true"; then
  ok "skill_agent_container"
else
  fail "skill_agent_container"
fi

if ssh_base "for attempt in \$(seq 1 30); do docker exec '$REMOTE_SERVICE_NAME' python -c \"import requests; requests.get('http://$REMOTE_AGENT_NAME:8080/health', timeout=5).raise_for_status()\" >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1"; then
  ok "skill_agent_health"
else
  fail "skill_agent_health"
fi
