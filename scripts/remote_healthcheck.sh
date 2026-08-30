#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

if ssh_base "test -d '$REMOTE_PROJECTS_ROOT'"; then
  ok "projects_root"
else
  fail "projects_root"
fi

if ssh_base "docker inspect -f '{{.State.Running}}' '$REMOTE_AGENT_NAME' 2>/dev/null | grep -qx true"; then
  ok "skill_agent_container"
else
  fail "skill_agent_container"
fi

# The agent reaches the Docker daemon through the mounted socket, and losing
# that is the failure that looks like every skill breaking at once.
if ssh_base "docker exec '$REMOTE_AGENT_NAME' docker ps >/dev/null"; then
  ok "skill_agent_docker_access"
else
  fail "skill_agent_docker_access"
fi

if ssh_base "for attempt in \$(seq 1 30); do docker exec '$REMOTE_AGENT_NAME' python -c \"import requests; requests.get('http://127.0.0.1:8080/health', timeout=5).raise_for_status()\" >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1"; then
  ok "skill_agent_health"
else
  fail "skill_agent_health"
fi

if ssh_base "docker inspect -f '{{.State.Running}}' '$REMOTE_WEB_NAME' 2>/dev/null | grep -qx true"; then
  ok "web_api_container"
else
  fail "web_api_container"
fi

if ssh_base "for attempt in \$(seq 1 30); do curl -fsS 'http://127.0.0.1:$REMOTE_WEB_PORT/api/health' >/dev/null 2>&1 && exit 0; sleep 1; done; exit 1"; then
  ok "console_health"
else
  fail "console_health"
fi
