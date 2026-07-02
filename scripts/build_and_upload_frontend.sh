#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 root@SERVER_IP [remote_repo_dir]" >&2
  echo "Example: $0 root@101.79.20.5 /opt/cloud_platform" >&2
  exit 1
fi

SSH_TARGET="$1"
REMOTE_REPO_DIR="${2:-/opt/cloud_platform}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="${ROOT_DIR}/frontend"

cd "${ROOT_DIR}"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Pulling latest source..."
  git pull --ff-only origin main
fi

cd "${FRONTEND_DIR}"

if [[ ! -d node_modules ]]; then
  echo "Installing frontend dependencies..."
  npm install
else
  echo "Frontend dependencies already installed. Skipping npm install."
fi

echo "Building frontend..."
npm run build

cd "${ROOT_DIR}"

echo "Uploading dist to ${SSH_TARGET}:${REMOTE_REPO_DIR}/frontend/dist/ ..."
"${ROOT_DIR}/scripts/upload_frontend_dist.sh" "${SSH_TARGET}" "${REMOTE_REPO_DIR}"

echo
echo "Done."
echo "Open: http://${SSH_TARGET#*@}:8000/"
