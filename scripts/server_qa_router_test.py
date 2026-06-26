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
    "version: '3.8'\nservices:\n  demo-a:\n    image: example/demo\n"
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
project_args_with_josa = app.strict_arguments(
    "horse_race로 할래",
    "project.create",
    transition["context"],
    {"project": "invented-project"},
)
assert project_args_with_josa == {"project": "horse_race"}, project_args_with_josa
project_args_with_command = app.strict_arguments(
    "horse_race로 만들어줘",
    "project.create",
    transition["context"],
    {},
)
assert project_args_with_command == {"project": "horse_race"}, project_args_with_command
project_chat = app.chat(
    app.ChatRequest(
        message="horse_race로 할래",
        context=transition["context"],
    )
)
assert project_chat["skill"] == "project.create", project_chat
assert project_chat["arguments"] == {"project": "horse_race"}, project_chat
assert project_chat["requires_approval"] is True, project_chat
assert project_chat["preview"]["project"] == "horse_race", project_chat
project_chat_with_session = app.chat(
    app.ChatRequest(
        session_id="router-session-001",
        message="horse_race로 만들어줘",
        context=transition["context"],
    )
)
assert project_chat_with_session["arguments"] == {"project": "horse_race"}, project_chat_with_session
assert project_chat_with_session["requires_approval"] is True, project_chat_with_session
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

exact_project = runtime.entity_resolve("project", "demoa")
assert exact_project["status"] == "exact", exact_project
similar_project = runtime.entity_resolve("project", "demo-a")
assert similar_project["status"] == "single", similar_project
assert similar_project["match"] == "demoa", similar_project
missing_project = runtime.entity_resolve("project", "totally-new-project")
assert missing_project["status"] == "none", missing_project
print("OK cli_entity_resolution")

similar_context = {
    "skill": "service.deploy",
    "arguments": {},
    "missing": [{"field": "project"}],
}
similar_response = app.cli_proposal_for_input(
    "demo-a 프로젝트에 서비스를 배포할래",
    "service.deploy",
    similar_context,
)
assert similar_response and similar_response["context"]["proposed"], similar_response
assert "demoa" in similar_response["message"], similar_response
assert "project" not in similar_response["arguments"], similar_response
confirmed_context, confirmation_response = app.handle_proposed_input(
    "맞아, 그걸로 진행해줘",
    similar_response["context"],
)
assert confirmation_response is None, confirmation_response
assert confirmed_context["arguments"]["project"] == "demoa", confirmed_context
assert "proposed" not in confirmed_context, confirmed_context
print("OK proposed_requires_confirmation")

preserved_response = app.cli_proposal_for_input(
    "demo-a 프로젝트에 frontend 서비스 만들래",
    "service.deploy",
    similar_context,
)
assert preserved_response["arguments"]["service"] == "frontend", preserved_response
preserved_context, response = app.handle_proposed_input(
    "맞아",
    preserved_response["context"],
)
assert response is None, response
assert preserved_context["arguments"] == {
    "project": "demoa",
    "service": "frontend",
    "is_web": True,
}, preserved_context
assert preserved_context.get("missing") == [], preserved_context
print("OK proposal_preserves_other_slots")

port_arguments = app.strict_arguments(
    "demoa 프로젝트의 demo-a 서비스 호스트 포트를 9003번으로 바꿔줘",
    "port.manage",
    None,
    {"project": "invented", "service": "wrong", "operation": "change_host"},
)
assert port_arguments == {
    "project": "demoa",
    "service": "demo-a",
    "operation": "change_host",
    "host_port": 9003,
}, port_arguments
print("OK cli_verified_port_arguments")

assert app.deterministic_read_request("서버 상태 확인해줘") == (
    "server.health",
    {},
)
assert app.deterministic_read_request("demoa의 demo-a 상태 확인해줘") == (
    "service.status",
    {"project": "demoa", "service": "demo-a"},
)
assert app.deterministic_read_request("demoa의 demo-a 로그 20줄 보여줘") == (
    "service.logs",
    {"project": "demoa", "service": "demo-a", "lines": 20},
)
print("OK deterministic_cli_read_routing")

health_message = app.render_server_health(
    {
        "docker": True,
        "containers": 2,
        "running": 2,
        "restarting": [],
        "unhealthy": [],
        "container_details": [
            {
                "name": "demo",
                "status": "running",
                "health": "healthy",
                "ports": [{"host": "9000", "container": "3000/tcp"}],
            }
        ],
        "projects": {
            "projects": [{"name": "demoa", "services": ["demo-a"]}]
        },
        "disk_percent": 50.0,
        "memory_percent": 40.0,
    }
)
assert "Docker 컨테이너" in health_message
assert "demo-a" in health_message
print("OK cli_result_rendering")

problem = app.project_problem_response(
    "service.deploy",
    {"project": "rea", "service": "reafront"},
    app.ChatRequest(message="기존 프로젝트 이름은 rea"),
)
assert problem and "docker-compose.yml" in problem["message"], problem
print("OK incomplete_project_diagnosis")

repair_preview = runtime.project_create("rea", dry_run=True)
assert repair_preview["operation"] == "repair", repair_preview
runtime.ensure_project_networks = lambda project, attach_platform_api: {
    "app_network": f"cp_{project}_app_net",
    "control_network": f"cp_{project}_control_net",
}
runtime.register_namespace_token = lambda project: True
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

framework_proposal = app.proposal_context(
    framework_context,
    {
        "field": "framework",
        "entity": "framework",
        "query": "저장소 구조",
        "candidate": "static",
        "candidates": [{"value": "static", "score": 1.0}],
        "source": "repository.inspect CLI",
    },
)
confirmed_recommendation, response = app.handle_proposed_input(
    "그걸로 진행해줘",
    framework_proposal,
)
assert response is None, response
assert confirmed_recommendation["arguments"]["framework"] == "static"
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
