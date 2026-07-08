#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_NAME="${IMAGE_NAME:-cloud-platform-web-api:dev}"
CONTAINER_NAME="${CONTAINER_NAME:-cloud-platform-web-api}"
NETWORK_NAME="${NETWORK_NAME:-cloud-platform-internal}"
HOST_PORT="${HOST_PORT:-8000}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://localhost:${HOST_PORT}}"
DATA_DIR="${DATA_DIR:-${ROOT_DIR}/data}"
FRONTEND_DIST="${FRONTEND_DIST:-${ROOT_DIR}/frontend/dist}"
CONTAINER_FRONTEND_DIST="${CONTAINER_FRONTEND_DIST:-/var/www/cloud-platform-console}"

if ! docker network inspect "${NETWORK_NAME}" >/dev/null 2>&1; then
  echo "Docker network not found: ${NETWORK_NAME}" >&2
  exit 1
fi

docker build -t "${IMAGE_NAME}" -f "${ROOT_DIR}/web/Dockerfile" "${ROOT_DIR}"

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
mkdir -p "${DATA_DIR}"
mkdir -p "${FRONTEND_DIST}"
docker run -d \
  --name "${CONTAINER_NAME}" \
  --network "${NETWORK_NAME}" \
  -e SKILL_AGENT_URL="${SKILL_AGENT_URL:-http://cloud-platform-skill-agent:8080}" \
  -e AUTH_STORE="${AUTH_STORE:-/var/lib/cloud-platform/auth.json}" \
  -e FRONTEND_DIST="${CONTAINER_FRONTEND_DIST}" \
  -e PUBLIC_BASE_URL="${PUBLIC_BASE_URL}" \
  -v "${DATA_DIR}:/var/lib/cloud-platform" \
  -v "${FRONTEND_DIST}:${CONTAINER_FRONTEND_DIST}:ro" \
  -p "${HOST_PORT}:8000" \
  "${IMAGE_NAME}"

echo "React console API and static frontend are running at http://localhost:${HOST_PORT}"
echo "Static frontend directory: ${FRONTEND_DIST}"
