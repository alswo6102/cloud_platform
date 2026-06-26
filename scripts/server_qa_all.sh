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
        'from pathlib import Path; [compile(Path(f).read_text(), f, "exec") for f in ["admin.py", "agent/app.py", "agent/runtime.py", "deployment_presets.py"]]'
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

check_router() {
    docker run --rm \
        -v "$ROOT_DIR:/workspace" \
        -w /workspace \
        cloud-platform-skill-agent:latest \
        python scripts/server_qa_router_test.py
}

check_llm_fallback() {
    docker run --rm \
        -v "$ROOT_DIR:/workspace" \
        -w /workspace \
        cloud-platform-skill-agent:latest \
        python scripts/server_llm_fallback_test.py
}

check_dashboard() {
    curl -fsS http://127.0.0.1:8501/_stcore/health | grep -q '^ok$'
}

check_agent() {
    docker exec cloud-platform-dashboard python -c '
import requests
b="http://cloud-platform-skill-agent:8080"
h=requests.get(b+"/health",timeout=5).json()
s=requests.get(b+"/skills",timeout=5).json()
f=requests.get(b+"/frameworks",timeout=5).json()
assert h["status"]=="ok"
assert len(s["skills"])==16, len(s["skills"])
assert len(f["frameworks"])>=10, len(f["frameworks"])
'
}

check_runtime_qa() {
    docker exec cloud-platform-dashboard python -c '
import requests
r=requests.post(
    "http://cloud-platform-skill-agent:8080/execute",
    json={"skill":"qa.run","arguments":{},"approved":False},
    timeout=20,
)
r.raise_for_status()
assert r.json()["result"]["passed"], r.text
'
}

check_cli() {
    docker exec cloud-platform-skill-agent cloud-platform skills | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert len(data["skills"]) == 16
'
    docker exec cloud-platform-skill-agent cloud-platform projects >/dev/null
    docker exec cloud-platform-skill-agent cloud-platform frameworks | python3 -c '
import json, sys
data=json.load(sys.stdin)
assert len(data["frameworks"]) >= 10
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
run_check router "Intent, clarification, and framework funnel" check_router
run_check fallback "LLM rate-limit fallback" check_llm_fallback
run_check dashboard "Dashboard health" check_dashboard
run_check agent "Agent, skill catalog, and presets" check_agent
run_check runtime "Runtime deterministic QA" check_runtime_qa
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
