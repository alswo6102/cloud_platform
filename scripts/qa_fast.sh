#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$SCRIPT_DIR/server_env_check.sh"
"$SCRIPT_DIR/remote_healthcheck.sh"
"$SCRIPT_DIR/remote_skill_test.sh"
"$SCRIPT_DIR/remote_audit.sh"
"$SCRIPT_DIR/external_access_check.sh"

printf 'OK qa_fast\n'
