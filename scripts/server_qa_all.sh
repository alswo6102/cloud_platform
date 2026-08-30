#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAST=false
if [[ "${1:-}" == "--fast" ]]; then
    FAST=true
fi

PASS=0
FAIL=0
LOG_DIR="$(mktemp -d)"
trap 'rm -rf "$LOG_DIR"' EXIT

run_check() {
    local id="$1"
    local label="$2"
    shift 2
    local log="$LOG_DIR/$id.log"
    if "$@" >"$log" 2>&1; then
        printf '[O] %s\n' "$label"
        PASS=$((PASS + 1))
    else
        printf '[X] %s\n' "$label"
        sed 's/^/    /' "$log"
        FAIL=$((FAIL + 1))
    fi
}

check_python() {
    cd "$ROOT_DIR"
    PYTHONDONTWRITEBYTECODE=1 python3 -c \
        'from pathlib import Path; [compile(Path(f).read_text(), f, "exec") for f in ["agent/app.py", "agent/authz.py", "agent/planner.py", "agent/runtime.py", "agent/skill_registry.py", "web/app.py", "deployment_presets.py"]]'
}

check_schemas() {
    cd "$ROOT_DIR"
    local file
    while IFS= read -r file; do
        python3 -m json.tool "$file" >/dev/null
    done < <(find agent/skills -name schema.json -type f | sort)
}

check_secrets() {
    cd "$ROOT_DIR"
    git status --ignored --short .agent.env | grep -q '^!! .agent.env$'
    ! git grep -nE '(AIza[0-9A-Za-z_-]{20,}|github_pat_|ghp_)' -- . \
        ':!scripts/server_qa_all.sh'
}

check_llm_fallback() {
    docker run --rm \
        -v "$ROOT_DIR:/workspace" \
        -w /workspace \
        cloud-platform-skill-agent:latest \
        python scripts/server_llm_fallback_test.py
}

check_console() {
    curl -fsS http://127.0.0.1:8000/api/health | grep -q '"status":"ok"'
}

# Asked from the web API rather than the agent itself: it is the agent's real
# caller, so this also proves the control network still resolves.
check_agent() {
    docker exec cloud-platform-web-api python -c '
import requests
b="http://cloud-platform-skill-agent:8080"
h=requests.get(b+"/health",timeout=5).json()
s=requests.get(b+"/skills",timeout=5).json()
f=requests.get(b+"/frameworks",timeout=5).json()
assert h["status"]=="ok"
assert len(s["skills"])==19, len(s["skills"])
assert len(f["frameworks"])>=10, len(f["frameworks"])
'
}

# The agent authenticates every caller, so the checks below have to present
# the control-plane token the way the web layer does.
root_token() {
    docker exec cloud-platform-skill-agent printenv PLATFORM_ROOT_TOKEN 2>/dev/null
}

check_runtime_qa() {
    local token
    token="$(root_token)"
    [[ -n "$token" ]] || { echo "PLATFORM_ROOT_TOKEN is not set on the agent"; return 1; }
    docker exec -e QA_ROOT_TOKEN="$token" cloud-platform-web-api python -c '
import os
import requests
r=requests.post(
    "http://cloud-platform-skill-agent:8080/execute",
    json={"skill":"qa.run","arguments":{},"approved":False},
    headers={"Authorization": "Bearer " + os.environ["QA_ROOT_TOKEN"]},
    timeout=20,
)
r.raise_for_status()
assert r.json()["result"]["passed"], r.text
'
}

check_review_regressions() {
    docker run --rm \
        -v "$ROOT_DIR:/workspace" \
        -w /workspace \
        cloud-platform-skill-agent:latest \
        python scripts/server_review_regression_test.py
}

# A deploy that leaves an agent behind is invisible until someone opens that
# project and waits out the rebuild, behind a table that claims to be reading
# Docker stats. Cheap to ask, so ask.
check_project_agents_current() {
    docker exec -i cloud-platform-skill-agent python - <<'PY'
import sys

sys.path.insert(0, "/app")

import docker

import runtime

current = runtime.project_agent_template_version()
client = docker.from_env()
stale = []
for container in client.containers.list(filters={"label": "cloud.platform.role=agent"}):
    running = ""
    for entry in container.attrs["Config"]["Env"]:
        name, _, value = entry.partition("=")
        if name == "PROJECT_AGENT_TEMPLATE_VERSION":
            running = value
    if running != current:
        stale.append(f"{container.name}={running or '(none)'}")
assert not stale, f"현재 {current}인데 뒤처진 에이전트: {sorted(stale)}"
PY
}

check_cli() {
    docker exec cloud-platform-skill-agent cloud-platform skills | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert len(data["skills"]) == 19
'
    docker exec cloud-platform-skill-agent cloud-platform projects >/dev/null
    docker exec cloud-platform-skill-agent cloud-platform frameworks | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert len(data["frameworks"]) >= 10
'
    docker exec cloud-platform-skill-agent cloud-platform schema service.deploy | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert data["skill"] == "service.deploy"
assert data["requires_approval"] is True
assert data["role"]
assert "service.redeploy" in data["ambiguous_with"]
assert data["clarification_question"]
fields={item["name"]: item for item in data["fields"]}
assert fields["project"]["question"]
assert fields["repo_url"]["rules"]
'
    docker exec cloud-platform-skill-agent cloud-platform help | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert data["task_guide"]
redeploy=next(item for item in data["task_guide"] if item["skill"] == "service.redeploy")
assert redeploy["role"]
assert redeploy["use_when"]
assert redeploy["not_for"]
assert redeploy["clarification_question"]
'
    docker exec cloud-platform-skill-agent cloud-platform commands | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert data["planner_rule"]
assert any(item["skill"] == "project.create" for item in data["commands"])
'
    docker exec cloud-platform-skill-agent cloud-platform preview project.create \
        --arguments '{}' | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert data["status"] == "needs_input", data
assert data["missing"][0]["name"] == "project", data
assert data["next_question"], data
'
    if docker exec cloud-platform-skill-agent cloud-platform execute project.create \
        --arguments '{"project":"must-not-run"}' >/dev/null 2>&1; then
        return 1
    fi
}

check_cleanup() {
    test ! -e /srv/projects/skill-qa
}

printf 'Cloud Platform QA\n'
printf '%s\n' '────────────────────────────────────'
run_check syntax "Python syntax" check_python
run_check schemas "Skill schemas" check_schemas
run_check secrets "Secret exclusion" check_secrets
run_check fallback "LLM rate-limit fallback" check_llm_fallback
run_check regressions "Reviewed defects stay fixed" check_review_regressions
run_check console "Console API health" check_console
run_check agent "Agent, skill catalog, and presets" check_agent
run_check runtime "Runtime deterministic QA" check_runtime_qa
run_check agents "Project agents run the deployed template" check_project_agents_current
run_check cli "Strict CLI adapter and approval guard" check_cli
run_check namespace "Namespace agent, control network, and ownership guard" \
    "$ROOT_DIR/scripts/server_namespace_network_qa.sh"

if [[ "$FAST" == false ]]; then
    run_check framework_build "Generated framework Dockerfile build and runtime" \
        "$ROOT_DIR/scripts/server_framework_build_test.sh"
    run_check mutation "Project, deploy, redeploy, control, and port mutations" \
        "$ROOT_DIR/scripts/server_skill_mutation_test.sh"
fi

run_check cleanup "Temporary resource cleanup" check_cleanup
printf '%s\n' '────────────────────────────────────'
if (( FAIL == 0 )); then
    printf 'RESULT: PASS %d / %d\n' "$PASS" "$((PASS + FAIL))"
    exit 0
fi
printf 'RESULT: FAIL %d passed / %d failed\n' "$PASS" "$FAIL"
exit 1
