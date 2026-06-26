#!/usr/bin/env bash
set -euo pipefail

THRESHOLD_PERCENT="${CLEANUP_DISK_THRESHOLD_PERCENT:-85}"
KEEP_STORAGE="${CLEANUP_BUILDER_KEEP_STORAGE:-1GB}"
QUIET=false

if [[ "${1:-}" == "--quiet" ]]; then
    QUIET=true
fi

log() {
    if [[ "$QUIET" == false ]]; then
        printf '%s\n' "$*"
    fi
}

disk_percent() {
    df -P / | awk 'NR==2 {gsub("%", "", $5); print $5}'
}

before="$(disk_percent)"
log "safe docker cleanup: disk ${before}% used"

# Safe: removes only dangling image layers, not tagged images used as cache or
# running service images.
docker image prune -f >/dev/null

after_dangling="$(disk_percent)"
if (( after_dangling >= THRESHOLD_PERCENT )); then
    # Keep a bounded build cache. This avoids the heavy-handed `docker system
    # prune -a`, which would remove useful base images and make the next deploy
    # painfully slow on a small disk.
    docker builder prune -f --keep-storage "$KEEP_STORAGE" >/dev/null || true
fi

after="$(disk_percent)"
log "safe docker cleanup: disk ${after}% used"
