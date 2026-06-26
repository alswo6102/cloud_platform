#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECTS_ROOT="${PROJECTS_ROOT:-/srv/projects}"
IMAGE="${IMAGE:-cloud-platform-skill-agent:latest}"
API_NAME="nsqa-platform-api"
A_PROJECT="nsqa_a"
B_PROJECT="nsqa_b"
A_TOKEN="nsqa-token-a"
B_TOKEN="nsqa-token-b"
TOKEN_JSON="{\"${A_TOKEN}\":\"${A_PROJECT}\",\"${B_TOKEN}\":\"${B_PROJECT}\"}"

PASS=0
FAIL=0
LOG_DIR="$(mktemp -d)"

cleanup_resources() {
    set +e
    timeout 30 docker-compose -p "$A_PROJECT" -f "$PROJECTS_ROOT/$A_PROJECT/docker-compose.yml" down -v >/dev/null 2>&1
    timeout 30 docker-compose -p "$B_PROJECT" -f "$PROJECTS_ROOT/$B_PROJECT/docker-compose.yml" down -v >/dev/null 2>&1
    docker rm -f \
        "${A_PROJECT}-agent-1" "${A_PROJECT}-frontend-1" "${A_PROJECT}-backend-1" \
        "${B_PROJECT}-agent-1" "${B_PROJECT}-frontend-1" "${B_PROJECT}-backend-1" >/dev/null 2>&1
    docker rm -f "$API_NAME" >/dev/null 2>&1
    docker network rm \
        "${A_PROJECT}_app_net" "${A_PROJECT}_control_net" \
        "${B_PROJECT}_app_net" "${B_PROJECT}_control_net" >/dev/null 2>&1
    rm -rf "$PROJECTS_ROOT/$A_PROJECT" "$PROJECTS_ROOT/$B_PROJECT"
}

cleanup() {
    cleanup_resources
    rm -rf "$LOG_DIR"
}
trap cleanup EXIT

run_check() {
    local id="$1"
    local label="$2"
    shift 2
    local log="$LOG_DIR/$id.log"
    if "$@" >"$log" 2>&1; then
        printf '[O] %s\n' "$label"
        PASS=$((PASS + 1))
    else
        printf '[X] %s\n' "$label"
        sed 's/^/    /' "$log"
        FAIL=$((FAIL + 1))
    fi
}

write_compose() {
    local project="$1"
    local token="$2"
    mkdir -p "$PROJECTS_ROOT/$project"
    cat >"$PROJECTS_ROOT/$project/docker-compose.yml" <<YAML
version: '3.8'
services:
  agent:
    image: ${IMAGE}
    command: sleep infinity
    environment:
      PLATFORM_NAMESPACE: ${project}
      PLATFORM_TOKEN: ${token}
      PLATFORM_API: http://platform-api:5000
      PROJECTS_ROOT: /srv/projects
    networks:
      app-net: {}
      control-net: {}
    labels:
      cloud.platform.project: ${project}
      cloud.platform.role: agent

  frontend:
    image: python:3.11-slim
    command: python -m http.server 3000
    working_dir: /tmp
    networks:
      app-net: {}
    labels:
      cloud.platform.project: ${project}
      cloud.platform.service: frontend

  backend:
    image: python:3.11-slim
    command: python -m http.server 8000
    working_dir: /tmp
    networks:
      app-net: {}
    labels:
      cloud.platform.project: ${project}
      cloud.platform.service: backend

networks:
  app-net:
    external: true
    name: ${project}_app_net
  control-net:
    external: true
    name: ${project}_control_net
YAML
}

setup_fixture() {
    cleanup_resources
    mkdir -p "$PROJECTS_ROOT"
    docker network create "${A_PROJECT}_app_net" >/dev/null
    docker network create "${A_PROJECT}_control_net" >/dev/null
    docker network create "${B_PROJECT}_app_net" >/dev/null
    docker network create "${B_PROJECT}_control_net" >/dev/null
    write_compose "$A_PROJECT" "$A_TOKEN"
    write_compose "$B_PROJECT" "$B_TOKEN"
    docker run -d \
        --name "$API_NAME" \
        --network "${A_PROJECT}_control_net" \
        --network-alias platform-api \
        -e PROJECTS_ROOT=/srv/projects \
        -e "PLATFORM_NAMESPACE_TOKENS=${TOKEN_JSON}" \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v "$PROJECTS_ROOT:/srv/projects" \
        "$IMAGE" \
        uvicorn app:app --host 0.0.0.0 --port 5000 >/dev/null
    docker network connect --alias platform-api "${B_PROJECT}_control_net" "$API_NAME"
    docker-compose -p "$A_PROJECT" -f "$PROJECTS_ROOT/$A_PROJECT/docker-compose.yml" up -d >/dev/null
    docker-compose -p "$B_PROJECT" -f "$PROJECTS_ROOT/$B_PROJECT/docker-compose.yml" up -d >/dev/null
}

wait_ready() {
    docker exec -i "${A_PROJECT}-agent-1" python - <<'PY'
import requests, time
for _ in range(60):
    try:
        if requests.get("http://platform-api:5000/health", timeout=2).json()["status"] == "ok":
            raise SystemExit(0)
    except Exception:
        time.sleep(1)
raise SystemExit("platform-api was not reachable from project agent")
PY
    docker exec -i "${A_PROJECT}-agent-1" python - <<'PY'
import requests, time
for _ in range(60):
    try:
        if requests.get("http://frontend:3000", timeout=2).status_code == 200:
            raise SystemExit(0)
    except Exception:
        time.sleep(1)
raise SystemExit("frontend was not reachable from project agent")
PY
}

check_agent_cli_uses_platform_api() {
    docker exec "${A_PROJECT}-agent-1" cloud-platform projects | python3 -c "
import json, sys
data=json.load(sys.stdin)
names=[item['name'] for item in data['projects']]
assert names == ['${A_PROJECT}'], names
"
}

check_agent_can_control_own_service() {
    docker exec "${A_PROJECT}-agent-1" cloud-platform execute service.control \
        --approve \
        --arguments '{"project":"nsqa_a","service":"frontend","action":"restart"}' \
        | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert data["result"]["verified"]["status"] == "running", data
'
}

check_agent_cannot_control_other_project() {
    if docker exec "${A_PROJECT}-agent-1" cloud-platform execute service.control \
        --approve \
        --arguments '{"project":"nsqa_b","service":"frontend","action":"restart"}'; then
        return 1
    fi
}

check_internal_service_dns() {
    docker exec -i "${A_PROJECT}-agent-1" python - <<'PY'
import requests
assert requests.get("http://frontend:3000", timeout=5).status_code == 200
assert requests.get("http://backend:8000", timeout=5).status_code == 200
PY
}

check_regular_service_cannot_see_platform_api() {
    docker exec -i "${A_PROJECT}-frontend-1" python - <<'PY'
import socket
try:
    socket.gethostbyname("platform-api")
except socket.gaierror:
    raise SystemExit(0)
raise SystemExit("frontend should not resolve platform-api because it is not on control-net")
PY
}

check_project_network_separation() {
    docker exec -i "${A_PROJECT}-agent-1" python - <<'PY'
import socket
try:
    socket.gethostbyname("nsqa_b-frontend-1")
except socket.gaierror:
    raise SystemExit(0)
raise SystemExit("project-a agent should not resolve project-b frontend")
PY
}

printf 'Namespace / Agent / Platform API QA\n'
printf '%s\n' '────────────────────────────────────'
run_check setup "Create isolated project app/control networks" setup_fixture
run_check ready "Project agent reaches platform-api and own services" wait_ready
run_check scoped_list "Project CLI sees only its own namespace" check_agent_cli_uses_platform_api
run_check own_control "Project CLI can control its own service through platform-api" check_agent_can_control_own_service
run_check cross_denied "Project CLI cannot control another project" check_agent_cannot_control_other_project
run_check service_dns "Project services are reachable on their app network" check_internal_service_dns
run_check api_hidden "Regular service cannot see platform-api" check_regular_service_cannot_see_platform_api
run_check network_split "Project app networks are separated" check_project_network_separation
printf '%s\n' '────────────────────────────────────'

if (( FAIL == 0 )); then
    printf 'RESULT: PASS %d / %d\n' "$PASS" "$((PASS + FAIL))"
    exit 0
fi
printf 'RESULT: FAIL %d passed / %d failed\n' "$PASS" "$FAIL"
exit 1
