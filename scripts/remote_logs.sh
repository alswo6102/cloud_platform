#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

TAIL_LINES="${1:-80}"
ssh_base "printf '%s\n' '--- dashboard ---'; docker logs --tail '$TAIL_LINES' '$REMOTE_SERVICE_NAME' 2>&1 || true; printf '%s\n' '--- skill-agent ---'; docker logs --tail '$TAIL_LINES' '$REMOTE_AGENT_NAME' 2>&1 || true"
