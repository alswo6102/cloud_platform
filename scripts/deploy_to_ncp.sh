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

ssh_base "docker rm -f '$REMOTE_SERVICE_NAME' >/dev/null 2>&1 || true"
ssh_base "docker run -d --name '$REMOTE_SERVICE_NAME' \
  --restart unless-stopped \
  -p '$REMOTE_PORT:8501' \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v '$REMOTE_PROJECTS_ROOT:/srv/projects' \
  cloud-platform-dashboard:latest >/dev/null"
ok "dashboard_container_started"
