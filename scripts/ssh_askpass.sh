#!/usr/bin/env bash
set -euo pipefail

: "${NCP_PASSWORD:?NCP_PASSWORD is required.}"
printf '%s\n' "$NCP_PASSWORD"
