#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

check_port() {
  local port="$1"
  if nc -z -w 5 "$NCP_HOST" "$port" >/dev/null 2>&1; then
    ok "external_port_$port"
  else
    fail "external_port_$port"
  fi
}

check_port "$REMOTE_PORT"

published_ports="$(
  ssh_base "docker ps --format '{{.Ports}}'" \
    | grep -Eo '0\.0\.0\.0:[0-9]+' \
    | cut -d: -f2 \
    | awk '$1 >= 9000 && $1 <= 9100' \
    | sort -nu
)"

while IFS= read -r port; do
  [ -n "$port" ] && check_port "$port"
done <<<"$published_ports"

ok "external_access"
