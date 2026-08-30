#!/usr/bin/env bash
set -euo pipefail

ROOT=/srv/projects/skill-qa
PROJECT=skill-qa
SERVICE=hello
AGENT=http://cloud-platform-skill-agent:8080

cleanup() {
    if [[ -f "$ROOT/docker-compose.yml" ]]; then
        docker-compose -p "$PROJECT" -f "$ROOT/docker-compose.yml" down --remove-orphans >/dev/null 2>&1 || true
    fi
    rm -rf "$ROOT"
}
trap cleanup EXIT

cleanup

ROOT_TOKEN="$(docker exec cloud-platform-skill-agent printenv PLATFORM_ROOT_TOKEN 2>/dev/null || true)"
if [[ -z "$ROOT_TOKEN" ]]; then
    echo "FAIL PLATFORM_ROOT_TOKEN is not set on the agent"
    exit 1
fi

docker exec -i cloud-platform-skill-agent python - "$AGENT" "$ROOT_TOKEN" <<'PYTHON'
import sys

import requests

base = sys.argv[1]
# The agent authenticates every caller; QA speaks as the control plane.
AUTH = {"Authorization": f"Bearer {sys.argv[2]}"}


def chat(message):
    response = requests.post(
        f"{base}/chat", json={"message": message}, headers=AUTH, timeout=60
    )
    response.raise_for_status()
    return response.json()


def preview(skill, arguments):
    response = requests.post(
        f"{base}/preview",
        json={"skill": skill, "arguments": arguments},
        headers=AUTH,
        timeout=300,
    )
    if response.status_code >= 400:
        print(response.text)
    response.raise_for_status()
    return response.json()["preview"]


def execute(plan):
    response = requests.post(
        f"{base}/execute",
        json={
            "skill": plan["skill"],
            "arguments": plan["arguments"],
            "approved": True,
        },
        headers=AUTH,
        timeout=600,
    )
    if response.status_code >= 400:
        print(response.text)
    response.raise_for_status()
    return response.json()["result"]


project_intent = chat("신규 프로젝트를 추가하고 싶어")
assert project_intent["skill"] == "project.create", project_intent
assert project_intent["kind"] == "clarification", project_intent
assert any(item["field"] == "project" for item in project_intent["missing"])

project = requests.post(
    f"{base}/chat",
    json={
        "message": "프로젝트 이름은 skill-qa야",
        "context": project_intent["context"],
    },
    headers=AUTH,
    timeout=60,
)
project.raise_for_status()
project = project.json()
assert project["skill"] == "project.create", project
assert project["requires_approval"] is True, project
created = execute(project)
assert created["verified"] is True, created
print("OK natural_language_project_create")

deploy_intent = chat("서비스를 새로 배포하고 싶어")
assert deploy_intent["skill"] == "service.deploy", deploy_intent
assert deploy_intent["kind"] == "clarification", deploy_intent
assert any(item["field"] == "project" for item in deploy_intent["missing"])

deploy_response = requests.post(
    f"{base}/chat",
    json={
        "message": (
            "skill-qa 프로젝트에 https://github.com/crccheck/docker-hello-world 저장소를 "
            "hello 서비스로 배포할게. 기존 Dockerfile을 사용하고 컨테이너 포트는 "
            "8000이고 웹 서비스야"
        ),
        "context": deploy_intent["context"],
    },
    headers=AUTH,
    timeout=60,
)
deploy_response.raise_for_status()
deploy = deploy_response.json()
assert deploy["skill"] == "service.deploy", deploy
assert deploy["requires_approval"] is True, deploy
deployed = execute(deploy)
assert deployed["verified"]["status"] == "running", deployed
original_port = deployed["host_port"]
print("OK natural_language_deploy")

redeploy = chat(
    "skill-qa 프로젝트의 hello 서비스를 GitHub 최신 코드로 재배포해줘"
)
assert redeploy["skill"] == "service.redeploy", redeploy
assert redeploy["requires_approval"] is True, redeploy
redeployed = execute(redeploy)
assert redeployed["verified"]["status"] == "running", redeployed
print("OK natural_language_redeploy")

stop = chat("skill-qa 프로젝트의 hello 서비스를 중지해줘")
assert stop["skill"] == "service.control", stop
assert stop["arguments"]["action"] == "stop", stop
stopped = execute(stop)
container = stopped["services"][0]["container"]
assert container is None or container["status"] != "running", stopped
print("OK natural_language_stop")

start = chat("skill-qa 프로젝트의 hello 서비스를 시작해줘")
assert start["skill"] == "service.control", start
assert start["arguments"]["action"] == "start", start
started = execute(start)
assert started["verified"]["status"] == "running", started
print("OK natural_language_start")

suggest = requests.post(
    f"{base}/execute",
    json={"skill": "port.suggest", "arguments": {}, "approved": False},
    headers=AUTH,
    timeout=20,
)
suggest.raise_for_status()
new_port = suggest.json()["result"]["suggested_host_port"]
assert new_port != original_port, (original_port, new_port)

port = chat(
    f"skill-qa 프로젝트의 hello 서비스 호스트 포트를 {new_port}번으로 바꿔줘"
)
assert port["skill"] == "port.manage", port
assert port["arguments"]["operation"] == "change_host", port
changed = execute(port)
assert changed["verified"]["status"] == "running", changed
assert {"host": new_port, "container": 8000} in changed["verified"]["ports"], changed
print("OK natural_language_port_change")

# A preset deploy writes the Dockerfile into the server-side clone only, so a
# repository never carries it. Redeploy has to regenerate it, or a service
# deployed with any preset can never be updated again.
preset_arguments = {
    "project": "skill-qa",
    "service": "preset",
    "repo_url": "https://github.com/crccheck/docker-hello-world",
    "framework": "static",
    "is_web": True,
    "environment_names": ["FEATURE_FLAG", "API_BASE_URL"],
}
preset_plan = preview("service.deploy", preset_arguments)
assert preset_plan["environment_names"] == ["API_BASE_URL", "FEATURE_FLAG"], preset_plan
assert preset_plan["framework"] == "static", preset_plan

preset_deployed = execute({"skill": "service.deploy", "arguments": preset_arguments})
assert preset_deployed["verified"]["status"] == "running", preset_deployed
# The names the caller asked for have to survive into the plan and the result.
assert preset_deployed["environment_names"] == ["API_BASE_URL", "FEATURE_FLAG"], preset_deployed
print("OK preset_deploy_keeps_environment_names")

preset_service = {"project": "skill-qa", "service": "preset"}
redeploy_plan = preview("service.redeploy", preset_service)
assert redeploy_plan["framework"] == "static", redeploy_plan
assert "regenerate" in redeploy_plan["dockerfile"], redeploy_plan
preset_redeployed = execute({"skill": "service.redeploy", "arguments": preset_service})
assert preset_redeployed["verified"]["status"] == "running", preset_redeployed
print("OK preset_redeploy_regenerates_dockerfile")

qa = requests.post(
    f"{base}/execute",
    json={"skill": "qa.run", "arguments": {}, "approved": False},
    headers=AUTH,
    timeout=30,
)
qa.raise_for_status()
assert qa.json()["result"]["passed"], qa.text
print("OK post_mutation_qa")
PYTHON
