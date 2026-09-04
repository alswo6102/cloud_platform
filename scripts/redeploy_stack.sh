#!/usr/bin/env bash
# Rebuild the control-plane images and restart the running containers on new
# code, keeping the configuration they already carry.
#
# The stack serving users is three containers -- the skill agent, a platform
# API, and the React console API -- assembled by hand with environment
# variables no script in this repository sets, and joined to one control
# network per project. Recreating them from a fixed command line would silently
# drop that configuration, so this reads each container's own environment and
# network membership and puts them back.
#
# Runs on the server, from REMOTE_DIR.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$(mktemp -d)"
trap 'rm -rf "$STATE_DIR"' EXIT

# Image-provided values. Carrying these over would pin the container to the
# base image it was built from the last time.
IMAGE_ENV='^(PATH|LANG|GPG_KEY|PYTHON_VERSION|PYTHON_SHA256|PYTHONDONTWRITEBYTECODE|PYTHONUNBUFFERED)='

capture() {
    local name="$1"
    docker inspect "$name" --format '{{range .Config.Env}}{{println .}}{{end}}' \
        | grep -Ev "$IMAGE_ENV" | grep -v '^$' >"$STATE_DIR/$name.env"
    docker inspect "$name" \
        --format '{{range $network, $config := .NetworkSettings.Networks}}{{$network}}{{range $config.Aliases}} {{.}}{{end}}{{println}}{{end}}' \
        | grep -v '^$' >"$STATE_DIR/$name.networks"
}

restore_networks() {
    local name="$1"
    local first=1
    while read -r network aliases; do
        [[ -z "$network" ]] && continue
        if (( first )); then
            first=0
            # The run below already joined this one.
            continue
        fi
        local alias_args=()
        for alias in $aliases; do
            alias_args+=(--alias "$alias")
        done
        docker network connect "${alias_args[@]}" "$network" "$name"
    done <"$STATE_DIR/$name.networks"
}

primary_network_args() {
    local name="$1"
    read -r network aliases <"$STATE_DIR/$name.networks"
    printf -- '--network\n%s\n' "$network"
    for alias in $aliases; do
        printf -- '--network-alias\n%s\n' "$alias"
    done
}

recreate() {
    local name="$1"
    local image="$2"
    shift 2
    if ! docker inspect "$name" >/dev/null 2>&1; then
        echo "SKIP $name (not running)"
        return 0
    fi
    capture "$name"
    local -a network_args=()
    while IFS= read -r argument; do
        network_args+=("$argument")
    done < <(primary_network_args "$name")

    docker rm -f "$name" >/dev/null
    docker run -d \
        --name "$name" \
        --restart unless-stopped \
        "${network_args[@]}" \
        --env-file "$STATE_DIR/$name.env" \
        "$@" \
        "$image" >/dev/null
    restore_networks "$name"
    echo "OK $name"
}

docker build -f "$ROOT_DIR/agent/Dockerfile" -t cloud-platform-skill-agent:latest "$ROOT_DIR" \
    >/tmp/cloud_platform_skill_agent_build.log 2>&1
echo "OK skill_agent_build"

docker build -f "$ROOT_DIR/web/Dockerfile" -t cloud-platform-web-api:dev "$ROOT_DIR" \
    >/tmp/cloud_platform_web_api_build.log 2>&1
echo "OK web_api_build"

recreate cloud-platform-platform-api cloud-platform-skill-agent:latest \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /srv/projects:/srv/projects \
    -v cloud-platform-skill-agent-audit:/var/log/skill-agent

recreate cloud-platform-skill-agent cloud-platform-skill-agent:latest \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /srv/projects:/srv/projects \
    -v cloud-platform-skill-agent-audit:/var/log/skill-agent

recreate cloud-platform-web-api cloud-platform-web-api:dev \
    -p 8000:8000 \
    -v "$ROOT_DIR/data:/var/lib/cloud-platform" \
    -v "$ROOT_DIR/frontend/dist:/var/www/cloud-platform-console:ro"

# Any change under agent/ -- a prompt, a SKILL.md, one line of Python -- moves
# the template hash, and a project agent is rebuilt on the first request that
# finds it stale. That rebuild measured 16s on this disk, and it was landing on
# whoever opened the project first, behind a table that says it is reading
# Docker stats. The deploy already knows the sources changed, so it pays here.
#
# Set WARM_PROJECT_AGENTS=0 to skip: the agents are still correct either way,
# the cost just moves back to the first person through the door.
warm_project_agents() {
    if [[ "${WARM_PROJECT_AGENTS:-1}" == "0" ]]; then
        echo "SKIP project_agents (WARM_PROJECT_AGENTS=0)"
        return 0
    fi
    docker exec -i cloud-platform-skill-agent python - <<'PY'
import sys
import time

sys.path.insert(0, "/app")

import runtime

try:
    projects = [item["name"] for item in runtime.project_list()["projects"]]
except Exception as exc:  # noqa: BLE001 - nothing was warmed; say so and fail
    print(f"FAIL project_agents ({type(exc).__name__}: {exc})")
    raise SystemExit(1)

current = runtime.project_agent_template_version()
failed = []
for project in projects:
    started = time.monotonic()
    try:
        result = runtime.ensure_project_agent(project, dry_run=False)
    except Exception as exc:  # noqa: BLE001 - one bad project is not the rest
        print(f"WARN project_agent_{project} ({type(exc).__name__}: {exc})")
        failed.append(project)
        continue
    elapsed = time.monotonic() - started
    state = "rebuilt" if result.get("changed") else "current"
    print(f"OK project_agent_{project} ({state}, {elapsed:.0f}s)")

# This warm is the only thing that puts new agent code on a project. Nothing
# else checks afterwards, on a request or on a timer, so a project missed here
# stays on the previous release until the next deploy. One WARN in a wall of
# OK lines is not enough to carry that -- 1 vCPU means an agent recreate can
# lose a race for the box and fail on a deploy that is otherwise fine.
if failed:
    print(f"FAIL project_agents ({len(failed)}/{len(projects)}: {', '.join(failed)})")
    print("     control plane is deployed; rerun ensure for the projects above")
    raise SystemExit(1)
print(f"OK project_agents_at_{current}")
PY
}

warm_project_agents
