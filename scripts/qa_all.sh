#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/remote_prepare_server.sh"
"$SCRIPT_DIR/server_env_check.sh"
"$SCRIPT_DIR/deploy_to_ncp.sh"
"$SCRIPT_DIR/remote_healthcheck.sh"
"$SCRIPT_DIR/remote_smoke_test.sh"

printf 'OK qa_all\n'
