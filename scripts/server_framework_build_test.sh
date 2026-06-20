#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FIXTURE="$(mktemp -d)"
IMAGE=cloud-platform-framework-fixture:qa
CONTAINER=cloud-platform-framework-fixture-qa

cleanup() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker image rm "$IMAGE" >/dev/null 2>&1 || true
    rm -rf "$FIXTURE"
}
trap cleanup EXIT

python3 - "$ROOT_DIR" "$FIXTURE" <<'PYTHON'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
fixture = Path(sys.argv[2])
sys.path.insert(0, str(root))

from deployment_presets import render_dockerfile

(fixture / "Dockerfile").write_text(render_dockerfile("express"))
(fixture / "package.json").write_text(json.dumps({
    "name": "framework-fixture",
    "version": "1.0.0",
    "scripts": {"start": "node server.js"},
}))
(fixture / "server.js").write_text(
    "require('http').createServer((req,res)=>{res.end('OK')})"
    ".listen(Number(process.env.PORT || 3000), '0.0.0.0');"
)
PYTHON

docker build -t "$IMAGE" "$FIXTURE" >/dev/null
docker run -d --name "$CONTAINER" -p 127.0.0.1::3000 "$IMAGE" >/dev/null

for _ in $(seq 1 20); do
    PORT="$(docker port "$CONTAINER" 3000/tcp | awk -F: 'NR==1 {print $NF}')"
    if [[ -n "$PORT" ]] && curl -fsS "http://127.0.0.1:$PORT" | grep -q '^OK$'; then
        printf 'OK framework_fixture_build\n'
        exit 0
    fi
    sleep 1
done

docker logs "$CONTAINER"
exit 1
