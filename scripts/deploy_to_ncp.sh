#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

ssh_base "mkdir -p '$REMOTE_DIR'"
rsync_base "$ROOT_DIR/" "$(ssh_target):$REMOTE_DIR/"
ok "sync"

ssh_base "cd '$REMOTE_DIR' && docker build -t cloud-platform-dashboard:latest . >/tmp/cloud_platform_dashboard_build.log 2>&1"
ok "docker_build"

ssh_base "cd '$REMOTE_DIR' && docker build -f agent/Dockerfile -t cloud-platform-skill-agent:latest . >/tmp/cloud_platform_skill_agent_build.log 2>&1"
ok "skill_agent_build"

{
  printf 'LLM_API_KEY=%s\n' "${LLM_API_KEY:-}"
  printf 'LLM_API_URL=%s\n' "${LLM_API_URL:-}"
  printf 'LLM_MODEL=%s\n' "${LLM_MODEL:-}"
  printf 'PROJECTS_ROOT=/srv/projects\n'
  printf 'SKILLS_ROOT=/app/skills\n'
  printf 'DOCS_ROOT=/app/docs\n'
  printf 'AUDIT_LOG=/var/log/skill-agent/audit.jsonl\n'
} | ssh_base "umask 077; cat > '$REMOTE_DIR/.agent.env'"

ssh_base "docker network inspect cloud-platform-internal >/dev/null 2>&1 || docker network create cloud-platform-internal >/dev/null"
ssh_base "docker volume inspect cloud-platform-skill-agent-audit >/dev/null 2>&1 || docker volume create cloud-platform-skill-agent-audit >/dev/null"

ssh_base "docker rm -f '$REMOTE_AGENT_NAME' >/dev/null 2>&1 || true"
ssh_base "docker run -d --name '$REMOTE_AGENT_NAME' \
  --restart unless-stopped \
  --network cloud-platform-internal \
  --env-file '$REMOTE_DIR/.agent.env' \
  --security-opt no-new-privileges \
  --cap-drop ALL \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v '$REMOTE_PROJECTS_ROOT:/srv/projects' \
  -v cloud-platform-skill-agent-audit:/var/log/skill-agent \
  cloud-platform-skill-agent:latest >/dev/null"
ok "skill_agent_started"

ssh_base "docker rm -f '$REMOTE_SERVICE_NAME' >/dev/null 2>&1 || true"
ssh_base "docker run -d --name '$REMOTE_SERVICE_NAME' \
  --restart unless-stopped \
  --network cloud-platform-internal \
  -p '$REMOTE_PORT:8501' \
  -e 'PUBLIC_IP=$NCP_HOST' \
  -e 'SKILL_AGENT_URL=http://$REMOTE_AGENT_NAME:8080' \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v '$REMOTE_PROJECTS_ROOT:/srv/projects' \
  cloud-platform-dashboard:latest >/dev/null"
ok "dashboard_container_started"
