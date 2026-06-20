#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

from deployment_presets import FRAMEWORK_PRESETS, render_dockerfile

PROJECTS = Path("/tmp/cloud-platform-router-projects")
shutil.rmtree(PROJECTS, ignore_errors=True)
PROJECTS.mkdir(parents=True)
os.environ["PROJECTS_ROOT"] = str(PROJECTS)

import app
import runtime

(PROJECTS / "demoa").mkdir()
(PROJECTS / "demoa" / "docker-compose.yml").write_text(
    "version: '3.8'\nservices: {}\n"
)
(PROJECTS / "rea").mkdir()


assert app.preferred_skill_for("신규 프로젝트를 만들고 싶어", None) == "project.create"
assert app.preferred_skill_for("서비스를 새로 배포하고 싶어", None) == "service.deploy"
assert app.preferred_skill_for("서비스를 최신 코드로 재배포해줘", None) == "service.redeploy"
print("OK intent_funnel")

ambiguous = app.ambiguity_for("서비스 다시 해줘", None)
assert ambiguous and len(ambiguous["choices"]) == 2, ambiguous
print("OK ambiguous_request_clarification")

guide = app.chat(app.ChatRequest(message="배포 절차 알려줘"))
assert guide["kind"] == "guide" and "프레임워크 프리셋" in guide["message"], guide
print("OK local_deployment_guide")

missing = runtime.service_deploy(
    None, None, None, None, None, True, None, None, True
)
assert missing["needs_input"], missing
assert "현재 프로젝트: demoa" in missing["project_guidance"], missing
print("OK deployment_prerequisite")

for framework in FRAMEWORK_PRESETS:
    if framework == "existing":
        continue
    dockerfile = render_dockerfile(framework)
    assert "EXPOSE 3000" in dockerfile, framework
    assert dockerfile.strip(), framework
print("OK framework_templates")

deploy_context = {
    "original_request": "서비스를 새로 배포하고 싶어",
    "skill": "service.deploy",
    "arguments": {},
    "missing": [
        {"field": "project"},
        {"field": "service"},
        {"field": "repo_url"},
        {"field": "framework"},
    ],
}
transition = app.no_project_transition("기존 프로젝트 없어", deploy_context)
assert transition and transition["skill"] == "project.create", transition
print("OK no_project_transition")

project_args = app.strict_arguments(
    "rea",
    "project.create",
    transition["context"],
    {"project": "invented-project"},
)
assert project_args == {"project": "rea"}, project_args
print("OK explicit_slot_only")

inferred = app.strict_arguments(
    "rea",
    "service.deploy",
    deploy_context,
    {"project": "rea", "framework": "react"},
)
assert inferred == {}, inferred
print("OK reject_inferred_arguments")

problem = app.project_problem_response(
    "service.deploy",
    {"project": "rea", "service": "reafront"},
    app.ChatRequest(message="기존 프로젝트 이름은 rea"),
)
assert problem and "docker-compose.yml" in problem["message"], problem
print("OK incomplete_project_diagnosis")

repair_preview = runtime.project_create("rea", dry_run=True)
assert repair_preview["operation"] == "repair", repair_preview
runtime.project_create("rea", dry_run=False)
assert (PROJECTS / "rea" / "docker-compose.yml").is_file()
print("OK incomplete_project_repair")
