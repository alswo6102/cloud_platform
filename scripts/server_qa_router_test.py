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
assert (
    app.preferred_skill_for(
        "생성되어있는 프로젝트에 만들래",
        {"skill": "service.deploy"},
    )
    == "service.deploy"
)
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

known_project = app.strict_arguments(
    "demoa에 horseracefront 서비스 만들래",
    "service.deploy",
    deploy_context,
    {},
)
assert known_project["project"] == "demoa", known_project
assert known_project["service"] == "horseracefront", known_project
print("OK cli_verified_project_mention")

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

framework_context = {
    "original_request": "서비스를 새로 배포하고 싶어",
    "skill": "service.deploy",
    "arguments": {
        "project": "demoa",
        "service": "frontend",
        "repo_url": "https://github.com/example/frontend",
    },
    "missing": [{"field": "framework", "label": "프레임워크 프리셋"}],
}
catalog_help = app.framework_context_help(
    "프레임워크 프리셋 뭐 있는데",
    framework_context,
)
assert catalog_help and "Vite" in catalog_help["message"], catalog_help
assert catalog_help["context"] == framework_context
print("OK contextual_framework_catalog")

javascript_help = app.framework_context_help(
    "javascript로 개발했어",
    {
        **framework_context,
        "arguments": {
            "project": "demoa",
            "service": "frontend",
        },
    },
)
assert javascript_help and "하나로 결정할 수 없습니다" in javascript_help["message"]
assert "Next.js" in javascript_help["message"]
print("OK javascript_framework_clarification")

confirmed_recommendation = app.strict_arguments(
    "그걸로 진행해줘",
    "service.deploy",
    {
        "skill": "service.deploy",
        "arguments": {
            "project": "demoa",
            "service": "frontend",
            "repo_url": "https://github.com/example/frontend",
        },
        "missing": [{"field": "framework"}],
        "suggestions": {"framework": "static"},
    },
    {"framework": "vite"},
)
assert confirmed_recommendation["framework"] == "static", confirmed_recommendation
print("OK confirmed_cli_recommendation")

session_id = "qa-session-1234"
context = {
    "skill": "service.deploy",
    "arguments": {"project": "demoa", "service": "frontend"},
    "missing": [{"field": "repo_url"}],
}
app.remember_response(
    session_id,
    "demoa에 frontend 서비스 만들래",
    {
        "message": "저장소 URL이 필요합니다.",
        "context": context,
        "requires_approval": False,
    },
)
loaded_context, loaded_history = app.load_session(session_id, None)
assert loaded_context == context, loaded_context
assert loaded_history[-2]["role"] == "user", loaded_history
assert loaded_history[-1]["role"] == "assistant", loaded_history
app.remember_execution(session_id, "service.deploy", None)
loaded_context, loaded_history = app.load_session(session_id, None)
assert loaded_context is None, loaded_context
assert "실행과 검증을 완료" in loaded_history[-1]["content"], loaded_history
print("OK agent_owned_session")
