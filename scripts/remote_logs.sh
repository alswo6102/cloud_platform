#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

TAIL_LINES="${1:-80}"
ssh_base "docker logs --tail '$TAIL_LINES' '$REMOTE_SERVICE_NAME' 2>&1 || (cd '$REMOTE_DIR' && tail -n '$TAIL_LINES' /tmp/cloud_platform_dashboard_build.log 2>/dev/null || true)"
