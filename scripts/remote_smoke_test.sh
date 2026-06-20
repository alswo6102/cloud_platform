#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

ssh_base "bash -s" <<'REMOTE'
set -euo pipefail

QA_PROJECT="codex-qa"
QA_ROOT="/srv/projects/__codex_qa"
QA_PORT="19051"

wait_for_http() {
  local attempts=30
  while ! curl -fsS "http://127.0.0.1:$QA_PORT" >/dev/null 2>&1; do
    attempts=$((attempts - 1))
    if [ "$attempts" -eq 0 ]; then
      return 1
    fi
    sleep 1
  done
}

if [ -d "$QA_ROOT" ]; then
  (cd "$QA_ROOT" && docker-compose -p "$QA_PROJECT" down --volumes) >/dev/null 2>&1 || true
fi
rm -rf "$QA_ROOT"
mkdir -p "$QA_ROOT/web"

cat > "$QA_ROOT/web/Dockerfile" <<'DOCKERFILE'
FROM python:3.11-slim
WORKDIR /app
RUN printf 'ok\n' > index.html
EXPOSE 3000
CMD ["python", "-m", "http.server", "3000", "--bind", "0.0.0.0"]
DOCKERFILE

cat > "$QA_ROOT/docker-compose.yml" <<COMPOSE
version: "3.8"
services:
  web:
    build:
      context: ./web
    restart: always
    ports:
      - "$QA_PORT:3000"
    labels:
      - "is_web_service=true"
COMPOSE

cd "$QA_ROOT"
docker-compose -p "$QA_PROJECT" up -d --build web >/tmp/cloud_platform_qa.log 2>&1
wait_for_http
docker-compose -p "$QA_PROJECT" stop web >>/tmp/cloud_platform_qa.log 2>&1
docker exec -w "$QA_ROOT" cloud-platform-dashboard \
  docker-compose -p "$QA_PROJECT" up -d --no-build web >>/tmp/cloud_platform_qa.log 2>&1
wait_for_http
docker-compose -p "$QA_PROJECT" down --volumes >>/tmp/cloud_platform_qa.log 2>&1
rm -rf "$QA_ROOT"

echo "OK smoke_compose_lifecycle"
echo "OK smoke_dashboard_start"
REMOTE

ssh_base "docker exec '$REMOTE_SERVICE_NAME' python -m py_compile /app/admin.py" >/dev/null && ok "dashboard_python_compile"
ssh_base "docker exec -i '$REMOTE_SERVICE_NAME' python -" <<'PYTHON'
import ast
from pathlib import Path

import docker
import yaml

source = Path("/app/admin.py").read_text()
tree = ast.parse(source)
function_names = {
    "get_published_ports",
    "get_reserved_host_ports",
    "find_next_available_port",
}
functions = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name in function_names
]
namespace = {
    "Path": Path,
    "yaml": yaml,
    "docker": docker,
    "PROJECTS_ROOT": Path("/srv/projects"),
    "START_PORT": 9000,
    "END_PORT": 9100,
}
exec(compile(ast.Module(body=functions, type_ignores=[]), "/app/admin.py", "exec"), namespace)

assert namespace["get_published_ports"]("9000:3000") == {9000}
assert namespace["get_published_ports"]("127.0.0.1:9001:3000/tcp") == {9001}
assert namespace["get_published_ports"]({"published": "9002"}) == {9002}
assert namespace["find_next_available_port"]() == 9002
PYTHON
ok "dashboard_port_allocator"
ssh_base "docker exec '$REMOTE_SERVICE_NAME' sh -lc 'command -v docker-compose >/dev/null'" \
  && ok "dashboard_has_docker_compose"
