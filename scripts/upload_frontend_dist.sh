#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 root@SERVER_IP [remote_repo_dir]" >&2
  echo "Example: $0 root@123.123.123.123 /opt/cloud_platform" >&2
  exit 1
fi

SSH_TARGET="$1"
REMOTE_REPO_DIR="${2:-/opt/cloud_platform}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/frontend/dist"

if [[ ! -f "${DIST_DIR}/index.html" ]]; then
  echo "frontend/dist/index.html not found." >&2
  echo "Run this first: cd frontend && npm run build" >&2
  exit 1
fi

rsync -av --delete "${DIST_DIR}/" "${SSH_TARGET}:${REMOTE_REPO_DIR}/frontend/dist/"

echo "Uploaded frontend dist to ${SSH_TARGET}:${REMOTE_REPO_DIR}/frontend/dist/"
echo "Open: http://SERVER_IP:8000/"
