#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

ssh_base "bash -s" <<'REMOTE'
set -euo pipefail

QA_PROJECT="__codex_qa"
QA_ROOT="/srv/projects/$QA_PROJECT"
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
docker-compose -p "$QA_PROJECT" start web >>/tmp/cloud_platform_qa.log 2>&1
wait_for_http
docker-compose -p "$QA_PROJECT" down --volumes >>/tmp/cloud_platform_qa.log 2>&1
rm -rf "$QA_ROOT"

echo "OK smoke_compose_lifecycle"
REMOTE

ssh_base "docker exec '$REMOTE_SERVICE_NAME' python -m py_compile /app/admin.py" >/dev/null && ok "dashboard_python_compile"
ssh_base "docker exec '$REMOTE_SERVICE_NAME' sh -lc 'command -v docker-compose >/dev/null'" \
  && ok "dashboard_has_docker_compose"
