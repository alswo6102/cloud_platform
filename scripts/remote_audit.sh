#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

ssh_base "REMOTE_SERVICE_NAME='$REMOTE_SERVICE_NAME' REMOTE_AGENT_NAME='$REMOTE_AGENT_NAME' REMOTE_PORT='$REMOTE_PORT' bash -s" <<'REMOTE'
set -euo pipefail

docker info >/dev/null
echo "OK docker_daemon"

compose_version="$(docker-compose version --short)"
case "$compose_version" in
  2.*) echo "OK docker_compose_v2_$compose_version" ;;
  *) echo "FAIL docker_compose_v1_$compose_version"; exit 1 ;;
esac

swap_bytes="$(swapon --show=SIZE --bytes --noheadings | awk '{total += $1} END {print total + 0}')"
if [ "$swap_bytes" -ge 2147000000 ]; then
  echo "OK swap_2gb"
else
  echo "FAIL swap_too_small"
  exit 1
fi

dashboard_running="$(docker inspect -f '{{.State.Running}}' "$REMOTE_SERVICE_NAME")"
dashboard_restart="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$REMOTE_SERVICE_NAME")"
test "$dashboard_running" = "true"
test "$dashboard_restart" = "unless-stopped"
echo "OK dashboard_always_on"

agent_running="$(docker inspect -f '{{.State.Running}}' "$REMOTE_AGENT_NAME")"
agent_restart="$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$REMOTE_AGENT_NAME")"
agent_ports="$(docker inspect -f '{{json .NetworkSettings.Ports}}' "$REMOTE_AGENT_NAME")"
test "$agent_running" = "true"
test "$agent_restart" = "unless-stopped"
test "$agent_ports" = "{}"
echo "OK skill_agent_internal_only"

curl -fsS "http://127.0.0.1:$REMOTE_PORT/_stcore/health" >/dev/null
echo "OK dashboard_health"

docker exec "$REMOTE_SERVICE_NAME" docker ps >/dev/null
echo "OK dashboard_docker_socket"

if docker ps --filter status=restarting --format '{{.Names}}' | grep -q .; then
  echo "FAIL restarting_containers"
  docker ps --filter status=restarting --format '  {{.Names}}'
  exit 1
fi
echo "OK no_restarting_containers"

if docker ps --filter health=unhealthy --format '{{.Names}}' | grep -q .; then
  echo "FAIL unhealthy_containers"
  docker ps --filter health=unhealthy --format '  {{.Names}}'
  exit 1
fi
echo "OK no_unhealthy_containers"

python3 - <<'PYTHON'
from collections import defaultdict
from pathlib import Path

import yaml

projects_root = Path("/srv/projects")
port_owners = defaultdict(list)
compose_count = 0

for compose_file in projects_root.glob("*/docker-compose.yml"):
    compose_count += 1
    data = yaml.safe_load(compose_file.read_text()) or {}
    project = compose_file.parent.name
    for service_name, service in data.get("services", {}).items():
        for port_config in service.get("ports", []):
            value = str(port_config).split("/")[0]
            parts = value.rsplit(":", 2)
            if len(parts) >= 2 and parts[-2].isdigit():
                port_owners[int(parts[-2])].append(f"{project}/{service_name}")

duplicates = {port: owners for port, owners in port_owners.items() if len(owners) > 1}
if duplicates:
    for port, owners in sorted(duplicates.items()):
        print(f"FAIL duplicate_port_{port}={' '.join(owners)}")
    raise SystemExit(1)

print(f"OK compose_files_{compose_count}")
print("OK no_duplicate_compose_ports")
PYTHON

df -P / | awk 'NR == 2 {gsub("%", "", $5); if ($5 >= 95) {print "FAIL disk_usage_" $5 "%"; exit 1} print "OK disk_usage_" $5 "%"}'
REMOTE

ok "remote_audit"
