#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
load_env

ssh_base "docker exec -i '$REMOTE_SERVICE_NAME' python -" <<'PYTHON'
import requests

base = "http://cloud-platform-skill-agent:8080"

health = requests.get(f"{base}/health", timeout=10)
health.raise_for_status()

skills = requests.get(f"{base}/skills", timeout=10)
skills.raise_for_status()
names = {skill["name"] for skill in skills.json()["skills"]}
expected = {
    "help.search",
    "server.health",
    "project.list",
    "service.deploy",
    "service.status",
    "service.logs",
    "service.control",
    "port.suggest",
    "port.manage",
    "qa.run",
}
assert expected <= names, (expected - names)

help_guide = requests.post(
    f"{base}/chat",
    json={"message": "도움말"},
    timeout=10,
)
help_guide.raise_for_status()
help_data = help_guide.json()
assert help_data["mode"] == "local", help_data
assert help_data["kind"] == "help", help_data
assert "서비스 제어" in help_data["message"], help_data

projects = requests.post(
    f"{base}/execute",
    json={"skill": "project.list", "arguments": {}, "approved": False},
    timeout=10,
)
projects.raise_for_status()
project_items = projects.json()["result"]["projects"]

health_check = requests.post(
    f"{base}/execute",
    json={"skill": "server.health", "arguments": {}, "approved": False},
    timeout=20,
)
health_check.raise_for_status()
assert health_check.json()["result"]["docker"] is True

qa = requests.post(
    f"{base}/execute",
    json={"skill": "qa.run", "arguments": {}, "approved": False},
    timeout=20,
)
qa.raise_for_status()
assert qa.json()["result"]["passed"], qa.json()

rejected = requests.post(
    f"{base}/execute",
    json={
        "skill": "service.control",
        "arguments": {"project": "demoa", "service": "demo-a", "action": "restart"},
        "approved": False,
    },
    timeout=10,
)
assert rejected.status_code == 409, rejected.text

suggested = requests.post(
    f"{base}/execute",
    json={"skill": "port.suggest", "arguments": {}, "approved": False},
    timeout=10,
)
suggested.raise_for_status()
port = suggested.json()["result"]["suggested_host_port"]
assert 9000 <= port <= 9100, port

if project_items:
    project = project_items[0]
    status = requests.post(
        f"{base}/execute",
        json={
            "skill": "service.status",
            "arguments": {"project": project["name"]},
            "approved": False,
        },
        timeout=20,
    )
    status.raise_for_status()

chat = requests.post(
    f"{base}/chat",
    json={"message": "demoa demo-a 서비스를 재시작해줘"},
    timeout=20,
)
chat.raise_for_status()
assert chat.json()["requires_approval"] is True, chat.text

print("OK skill_catalog")
print("OK skill_help_guide")
print("OK skill_read_only")
print("OK skill_service_status")
print("OK skill_qa_verifier")
print("OK skill_approval_guard")
print("OK skill_chat_dry_run")
print("OK skill_port_suggest")
PYTHON

ok "remote_skill_test"
