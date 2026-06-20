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

docker exec -i cloud-platform-dashboard python - "$AGENT" <<'PYTHON'
import sys

import requests

base = sys.argv[1]


def chat(message):
    response = requests.post(f"{base}/chat", json={"message": message}, timeout=60)
    response.raise_for_status()
    return response.json()


def execute(plan):
    response = requests.post(
        f"{base}/execute",
        json={
            "skill": plan["skill"],
            "arguments": plan["arguments"],
            "approved": True,
        },
        timeout=600,
    )
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
assert "서비스는 기존 프로젝트 안에 배포됩니다" in deploy_intent["message"]

deploy_response = requests.post(
    f"{base}/chat",
    json={
        "message": (
            "skill-qa 프로젝트에 https://github.com/crccheck/docker-hello-world 저장소를 "
            "hello 서비스로 배포할게. 컨테이너 포트는 8000이고 웹 서비스야"
        ),
        "context": deploy_intent["context"],
    },
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

qa = requests.post(
    f"{base}/execute",
    json={"skill": "qa.run", "arguments": {}, "approved": False},
    timeout=30,
)
qa.raise_for_status()
assert qa.json()["result"]["passed"], qa.text
print("OK post_mutation_qa")
PYTHON
