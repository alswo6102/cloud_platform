from __future__ import annotations

import os
import re
import json
import psutil
import threading
import time
from copy import deepcopy
from typing import Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from deployment_presets import preset_catalog

from authz import (
    authenticated_namespace,
    namespace_scoped_arguments,
    namespace_scoped_result,
)
from skill_registry import read_only_skills, root_only_skills, skill_documents
from planner import (
    call_llm,
    call_llm_text,
    llm_status,
    load_prompt,
)
from runtime import (
    SkillError,
    attach_platform_api_to_existing_control_networks,
    command_catalog,
    command_contract,
    command_contracts,
    execute_skill,
    execute_cli_skill,
    project_summaries,
)

app = FastAPI(title="Cloud Platform Skill Agent", version="0.1.0")
PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", "/srv/projects"))
# Conversation memory is working state for one sitting, not a record to keep.
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", str(60 * 60 * 3)))
# A half-finished task expires long before the conversation does. Left to live
# as long as the session, an abandoned deploy kept handing its repository URL
# and service name to whatever the user asked next.
ACTIVE_TASK_TTL_SECONDS = int(os.getenv("ACTIVE_TASK_TTL_SECONDS", str(15 * 60)))
# A turn is now several messages -- the question, the tool calls, their
# results, the reply -- not two.
SESSION_HISTORY_LIMIT = int(os.getenv("SESSION_HISTORY_LIMIT", "60"))
SESSION_LOCK = threading.Lock()
SESSION_STORE = Path(
    os.getenv("SESSION_STORE", "/var/log/skill-agent/sessions.json")
)


def error_detail(exc: Exception) -> Any:
    if isinstance(exc, SkillError):
        return exc.to_dict()
    return str(exc)














def project_scoped_contract(contract: dict[str, Any], namespace: str) -> dict[str, Any]:
    scoped = deepcopy(contract)
    skill = scoped.get("skill")
    for key in ("required_fields", "optional_fields"):
        scoped[key] = [field for field in scoped.get(key, []) if field != "project"]
    scoped["fields"] = [
        field for field in scoped.get("fields", []) if field.get("field") != "project"
    ]
    schema = scoped.get("schema")
    if isinstance(schema, dict):
        schema = deepcopy(schema)
        if isinstance(schema.get("properties"), dict):
            schema["properties"].pop("project", None)
        if isinstance(schema.get("required"), list):
            schema["required"] = [field for field in schema["required"] if field != "project"]
        scoped["schema"] = schema
    if skill in {
        "service.deploy",
        "service.redeploy",
        "service.status",
        "service.logs",
        "service.control",
        "port.manage",
        "entity.resolve",
    }:
        scoped["project_scope"] = namespace
        scoped["scope_rule"] = (
            f"This CLI is running inside project namespace {namespace!r}. "
            "Do not ask for a project name. Treat the project as already fixed. "
            "If the user mentions another project, do not switch scope; explain that this "
            "workspace can only operate on the current project."
        )
    if skill == "project.list":
        scoped["role"] = (
            f"현재 project-agent namespace({namespace})에서 접근 가능한 프로젝트와 서비스만 조회합니다."
        )
        scoped["examples"] = ["서비스 목록 보여줘", "이 프로젝트에 어떤 서비스가 있어?"]
        scoped["scope_rule"] = "Returns only the current project in project-agent mode."
    if skill == "service.deploy":
        scoped["role"] = (
            f"{namespace} 프로젝트 안에 공개 GitHub 저장소를 새 서비스로 처음 등록하고 배포합니다."
        )
        scoped["use_when"] = [
            "이 프로젝트에 새 GitHub 저장소를 서비스로 올릴 때",
            "프로젝트는 이미 화면/agent namespace로 확정되어 있고 서비스만 추가할 때",
            "처음 배포, 신규 서비스 등록, add new service 요청일 때",
        ]
        scoped["not_for"] = [
            "새 프로젝트를 만드는 작업",
            "다른 프로젝트에 서비스를 추가하는 작업",
            "이미 존재하는 서비스를 최신 Git 코드로 다시 빌드하는 작업",
        ]
        scoped["examples"] = [
            "새 프론트 서비스를 배포하고 싶어",
            "frontend, https://github.com/owner/app, vite",
            "백엔드 API 서비스를 내부 통신 전용으로 추가하고 싶어",
        ]
        scoped["flow"] = [
            "project는 현재 namespace로 이미 확정되어 있으므로 사용자에게 묻지 않습니다.",
            "필수 입력은 service, repo_url, framework입니다.",
            "service는 보통 frontend, backend, api 같은 짧은 컨테이너/Compose 서비스 이름입니다.",
            "repo_url은 https://github.com/<owner>/<repo> 형태입니다.",
            "framework는 framework.list/schema enum 중 하나입니다. 애매하면 후보를 설명하고 선택을 요청합니다.",
            "host_port, is_web, environment_names는 선택값이며 생략 가능하다고 안내합니다.",
        ]
        scoped["clarification_question"] = (
            "이 프로젝트에 추가할 서비스 이름, GitHub URL, 프레임워크 프리셋을 알려주세요."
        )
    if skill == "service.redeploy":
        scoped["examples"] = ["frontend 최신 코드로 재배포해줘", "git push 했으니 api 다시 빌드해줘"]
    return scoped


def scoped_command_contract(skill: str, namespace: str | None) -> dict[str, Any]:
    contract = command_contract(skill)
    if namespace:
        if skill in root_only_skills():
            raise KeyError(f"{skill} is not available in project-scoped CLI")
        return project_scoped_contract(contract, namespace)
    return contract


def scoped_command_contracts(namespace: str | None) -> dict[str, Any]:
    contracts = []
    for item in skill_documents():
        skill = item["name"]
        if namespace and skill in root_only_skills():
            continue
        contracts.append(scoped_command_contract(skill, namespace))
    return {
        **command_contracts(),
        "scope": {"type": "project", "project": namespace} if namespace else {"type": "root"},
        "commands": sorted(contracts, key=lambda item: item["skill"]),
    }


def scoped_command_catalog(namespace: str | None) -> dict[str, Any]:
    base = command_catalog()
    contracts = scoped_command_contracts(namespace)["commands"]
    skills = [item["skill"] for item in contracts]
    catalog = {
        **base,
        "scope": {"type": "project", "project": namespace} if namespace else {"type": "root"},
        "task_guide": [
            {
                "skill": item["skill"],
                "title": item["title"],
                "role": item["role"],
                "use_when": item["use_when"],
                "not_for": item["not_for"],
                "ambiguous_with": [
                    skill for skill in item.get("ambiguous_with", []) if skill in skills
                ],
                "clarification_question": item["clarification_question"],
                "required_fields": item["required_fields"],
                "optional_fields": item["optional_fields"],
                "examples": item["examples"],
                "requires_approval": item["requires_approval"],
                **({"project_scope": item["project_scope"]} if "project_scope" in item else {}),
                **({"scope_rule": item["scope_rule"]} if "scope_rule" in item else {}),
            }
            for item in contracts
        ],
        "skills": sorted(skills),
    }
    if namespace:
        catalog["planner_rule"] = (
            base["planner_rule"]
            + f" This is a project-scoped CLI for {namespace!r}; never ask for project, "
            "never choose project.create, and only operate on the current project."
        )
        catalog["commands"] = {
            **base["commands"],
            "status [service]": "Project-scoped status; project is implicit",
            "logs <service>": "Project-scoped logs; project is implicit",
        }
        catalog["commands"].pop("status <project> [service]", None)
        catalog["commands"].pop("logs <project> <service>", None)
    return catalog


def load_persisted_sessions() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(SESSION_STORE.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


SESSIONS: dict[str, dict[str, Any]] = load_persisted_sessions()
@app.on_event("startup")
def connect_existing_control_networks() -> None:
    if os.getenv("PLATFORM_API"):
        return
    if os.getenv("ATTACH_PLATFORM_API_TO_CONTROL_NETWORKS", "1").lower() in {"0", "false", "no"}:
        return
    try:
        attach_platform_api_to_existing_control_networks()
    except Exception:
        # Startup should not fail only because Docker is temporarily slow.
        pass

def planner_arguments_for_llm(
    skill: str,
    context: dict[str, Any] | None,
    planner_arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    """Use LLM-selected arguments without natural-language reparsing.

    The LLM decides intent and extracts fields. This function only preserves
    already-confirmed active-task arguments and injects the scoped project from
    the project page/namespace. Validation, enum checks, existence checks, and
    permission checks remain in the CLI/platform API.
    """
    arguments: dict[str, Any] = {}
    context_arguments = (context or {}).get("arguments")
    if isinstance(context_arguments, dict) and (context or {}).get("skill") == skill:
        # Only carry the stored task forward while it is still the same task.
        # An abandoned deploy used to leak its repository URL into the next
        # one: the user named a new service and the old repo came along with
        # it, ready to be approved. A different subject means a different task.
        planner = planner_arguments if isinstance(planner_arguments, dict) else {}
        same_task = all(
            not (planner.get(field) and context_arguments.get(field))
            or str(planner[field]) == str(context_arguments[field])
            for field in ("service", "project")
        )
        if same_task:
            arguments.update(context_arguments)
    if isinstance(planner_arguments, dict):
        for key, value in planner_arguments.items():
            if value is not None:
                arguments[key] = value
    if skill in {
        "service.deploy",
        "service.redeploy",
        "service.status",
        "service.logs",
        "service.control",
        "port.manage",
    }:
        scoped_project = (
            ((context or {}).get("arguments") or {}).get("project")
            or (context or {}).get("project_scope")
            or os.getenv("PLATFORM_NAMESPACE")
        )
        if scoped_project:
            arguments["project"] = str(scoped_project)
    return arguments


PLACEHOLDER_ARGUMENT_VALUES = {
    "https://github.com/example/repo",
    "https://github.com/owner/repository",
    "https://github.com/owner/repo",
    "owner/repository",
    "owner/repo",
}


def remove_placeholder_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(arguments)
    for key, value in list(cleaned.items()):
        if isinstance(value, str) and value.strip().lower() in PLACEHOLDER_ARGUMENT_VALUES:
            cleaned.pop(key, None)
    return cleaned


def skill_error_payload(exc: SkillError) -> dict[str, Any]:
    return exc.to_dict()


def field_errors_from_error(error: dict[str, Any]) -> dict[str, str]:
    field = error.get("field")
    if not field:
        return {}
    message = str(error.get("message") or "입력값을 확인해주세요.")
    hint = str(error.get("hint") or "").strip()
    return {str(field): f"{message} {hint}".strip()}


def missing_from_field_errors(field_errors: dict[str, str]) -> list[dict[str, Any]]:
    labels = {
        "repo_url": "공개 GitHub HTTPS 저장소 URL",
        "service": "서비스 이름",
        "framework": "프레임워크 프리셋",
        "project": "프로젝트 이름",
    }
    return [
        {
            "field": field,
            "name": field,
            "label": labels.get(field, field),
            "required": True,
            "error": message,
        }
        for field, message in field_errors.items()
    ]


def arguments_for_plan(
    skill: str,
    context: dict[str, Any] | None,
    planner_arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    """Take the planner's arguments as the answer.

    The planner decides intent and extracts fields. Nothing here re-reads the
    user's words: safety is the namespace token, the JSON schema, and the
    approval gate, none of which depend on reparsing.
    """
    return remove_placeholder_arguments(
        planner_arguments_for_llm(skill, context, planner_arguments)
    )


def load_session(
    session_id: str | None,
    client_context: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    if not session_id:
        return client_context, []
    now = time.time()
    with SESSION_LOCK:
        expired = [
            key
            for key, value in SESSIONS.items()
            if now - float(value.get("updated_at", now)) > SESSION_TTL_SECONDS
        ]
        for key in expired:
            SESSIONS.pop(key, None)
        session = SESSIONS.setdefault(
            session_id,
            {"context": None, "history": [], "updated_at": now},
        )
        if client_context:
            stored_context = session.get("context")
            if stored_context:
                # The web layer sends request-scoped facts on every call
                # (project_scope, public_base_url, authenticated role context).
                # Keep the active task stored in the agent session, but refresh
                # these factual request-scoped values so read-only answers such
                # as frontend URLs do not become stale or disappear after a
                # deploy form context is stored.
                merged_context = deepcopy(stored_context)
                for key in ("project_scope", "public_base_url"):
                    if client_context.get(key):
                        merged_context[key] = client_context[key]
                client_args = client_context.get("arguments")
                if isinstance(client_args, dict) and client_args.get("project"):
                    merged_args = dict(merged_context.get("arguments") or {})
                    merged_args["project"] = client_args["project"]
                    merged_context["arguments"] = merged_args
                session["context"] = merged_context
            else:
                session["context"] = client_context
            # A brand-new session has no context_at, so the context stored one
            # line above was immediately read as expired and thrown away. Record
            # when it arrived; an existing session keeps the active task's age.
            session.setdefault("context_at", now)
        session["updated_at"] = now
        context = session.get("context")
        if context and now - float(session.get("context_at", 0)) > ACTIVE_TASK_TTL_SECONDS:
            session["context"] = None
            session.pop("context_at", None)
            context = None
        history = list(session.get("history") or [])
    return context, history


def persist_sessions_locked() -> None:
    SESSION_STORE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SESSION_STORE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(SESSIONS, ensure_ascii=False, default=str)
    )
    temporary.replace(SESSION_STORE)


def trim_transcript(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop whole exchanges from the front, never half of one.

    A tool result whose call is no longer in the list is rejected by the API,
    so the kept window has to start on a user message.
    """
    if len(messages) <= SESSION_HISTORY_LIMIT:
        return list(messages)
    start = len(messages) - SESSION_HISTORY_LIMIT
    while start < len(messages) and messages[start].get("role") != "user":
        start += 1
    return list(messages[start:])


def remember_response(
    session_id: str | None,
    user_message: str,
    response: dict[str, Any],
    transcript: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not session_id:
        return response
    assistant_message = str(response.get("message", "")).strip()
    with SESSION_LOCK:
        session = SESSIONS.setdefault(
            session_id,
            {"context": None, "history": [], "updated_at": time.time()},
        )
        if transcript is not None:
            # What the planner actually did this turn, tool calls and results
            # included, plus what the user was finally told.
            history = list(transcript)
            already_said = (
                history
                and history[-1].get("role") == "assistant"
                and str(history[-1].get("content") or "").strip() == assistant_message
            )
            if assistant_message and not already_said:
                history.append({"role": "assistant", "content": assistant_message})
        else:
            history = list(session.get("history") or [])
            history.append({"role": "user", "content": user_message})
            if assistant_message:
                history.append({"role": "assistant", "content": assistant_message})
        session["history"] = trim_transcript(history)
        if "context" in response:
            session["context"] = response.get("context")
        elif response.get("requires_approval"):
            session["context"] = {
                "original_request": user_message,
                "skill": response.get("skill"),
                "arguments": response.get("arguments", {}),
                "missing": [],
            }
        elif response.get("skill") in {"service.deploy", "service.redeploy", "project.create"} and response.get("missing"):
            session["context"] = {
                "original_request": user_message,
                "skill": response.get("skill"),
                "arguments": response.get("arguments", {}),
                "missing": response.get("missing", []),
            }
        # A read-only question asked in the middle of a task is a detour, not an
        # abandonment: looking up the service list while filling in a deploy
        # used to discard everything already collected. Keep the active task and
        # let the next turn continue it.
        session["context_at"] = time.time()
        session["updated_at"] = time.time()
        persist_sessions_locked()
    response["session_id"] = session_id
    return response


def remember_execution(
    session_id: str | None,
    skill: str,
    resume: dict[str, Any] | None,
) -> None:
    if not session_id:
        return
    with SESSION_LOCK:
        session = SESSIONS.setdefault(
            session_id,
            {"context": None, "history": [], "updated_at": time.time()},
        )
        session["context"] = resume
        session["context_at"] = time.time()
        history = session.setdefault("history", [])
        history.append(
            {
                "role": "assistant",
                "content": f"{skill} 작업이 승인되어 실행과 검증을 완료했습니다.",
            }
        )
        session["history"] = trim_transcript(history)
        session["updated_at"] = time.time()
        persist_sessions_locked()


def public_base_url_from_context(context: dict[str, Any] | None = None) -> str:
    if context:
        value = str(context.get("public_base_url") or "").strip()
        if value:
            return value.rstrip("/")
    value = (
        os.getenv("PUBLIC_BASE_URL", "")
        or os.getenv("EXTERNAL_BASE_URL", "")
        or os.getenv("NCP_BASE_URL", "")
    ).strip()
    return value.rstrip("/")


def url_for_host_port(host_port: Any, context: dict[str, Any] | None = None) -> str | None:
    try:
        port = int(host_port)
    except (TypeError, ValueError):
        return None
    base = public_base_url_from_context(context)
    if base:
        match = re.match(r"^(https?://[^/:]+)(?::\d+)?", base)
        if match:
            return f"{match.group(1)}:{port}"
    host = (
        os.getenv("PUBLIC_HOST", "")
        or os.getenv("EXTERNAL_HOST", "")
        or os.getenv("NCP_HOST", "")
    ).strip()
    if not host:
        return None
    return f"http://{host}:{port}"


def enrich_read_only_result(
    skill: str,
    result: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    enriched = deepcopy(result)
    if skill != "service.status":
        return enriched
    for item in enriched.get("services", []) or []:
        container = item.get("container") or {}
        ports = container.get("ports") or []
        public_urls = []
        for port in ports:
            url = url_for_host_port(port.get("host"), context)
            if url:
                public_urls.append(
                    {
                        "url": url,
                        "host": port.get("host"),
                        "container": port.get("container"),
                    }
                )
        item["public_urls"] = public_urls if item.get("frontend") else []
    return enriched


def naturalize_read_only_result(
    skill: str,
    result: dict[str, Any],
    user_message: str,
    context: dict[str, Any] | None = None,
    model_hint: str | None = None,
) -> dict[str, Any]:
    enriched = enrich_read_only_result(skill, result, context)
    try:
        llm = call_llm_text(
            system=load_prompt("read_only_reply"),
            user=json.dumps(
                {
                    "user_message": user_message,
                    "skill": skill,
                    "cli_result": enriched,
                },
                ensure_ascii=False,
                default=str,
            ),
        )
        if llm and llm.get("message"):
            return {
                "message": llm["message"],
                "result": enriched,
                "model": llm.get("model") or model_hint,
            }
    except Exception:
        pass
    # The lookup itself succeeded, so hand the result back and say plainly that
    # the wording could not be produced.
    return {
        "message": "조회는 완료했지만 설명을 만들지 못했습니다. 아래 결과를 확인해주세요.",
        "result": enriched,
        "model": model_hint,
    }


def naturalize_mutation_message(
    *,
    purpose: str,
    skill: str,
    arguments: dict[str, Any],
    user_message: str,
    preview: dict[str, Any] | None = None,
    missing: list[dict[str, Any]] | None = None,
    error: Any | None = None,
    model_hint: str | None = None,
) -> dict[str, Any]:
    if purpose == "missing":
        labels = [str(item.get("label") or item.get("field")) for item in (missing or [])]
        fallback = "진행하려면 추가 정보가 필요합니다: " + ", ".join(labels)
    elif purpose == "error":
        detail = error.get("message") if isinstance(error, dict) else str(error)
        fallback = f"검증 중 문제가 확인됐습니다: {detail}"
    else:
        fallback = "실행 계획을 준비했습니다. 아래 내용을 확인하고 승인해주세요."
    try:
        llm = call_llm_text(
            system=load_prompt("mutation_reply"),
            user=json.dumps(
                {
                    "purpose": purpose,
                    "user_message": user_message,
                    "skill": skill,
                    "arguments": arguments,
                    "preview": preview or {},
                    "missing": missing or [],
                    "error": error,
                },
                ensure_ascii=False,
                default=str,
            ),
        )
        if llm and llm.get("message"):
            return {"message": llm["message"], "model": llm.get("model") or model_hint}
    except Exception:
        pass
    return {"message": fallback, "model": model_hint}


# Presets that compile the repository on this host rather than serving files
# it already contains.
SOURCE_BUILD_FRAMEWORKS = {
    "vite",
    "react",
    "nextjs",
    "spring-maven",
    "spring-gradle",
    "go",
}
# Roughly what a frontend toolchain needs before it starts swapping.
SOURCE_BUILD_MEMORY_MB = int(os.getenv("SOURCE_BUILD_MEMORY_MB", "2048"))


def source_build_is_affordable() -> bool:
    # Read the host's memory directly. server.health would answer this too, but
    # it is root-plane only: a project agent asking gets a 403, which this would
    # read as "capacity unknown" and never warn anyone.
    try:
        return psutil.virtual_memory().total / 1024 / 1024 >= SOURCE_BUILD_MEMORY_MB
    except Exception:
        # Unknown capacity is not a reason to warn.
        return True


def deploy_confirmations(
    message: str,
    skill: str,
    arguments: dict[str, Any],
) -> list[dict[str, Any]]:
    """Choices the planner made for the user that the user should make.

    This is not a second guess at what the user meant -- the planner's reading
    stands. It only checks whether a value in a deploy plan was ever the user's
    to begin with, and turns the ones that were not into questions.
    """
    if skill != "service.deploy":
        return []
    items: list[dict[str, Any]] = []
    lowered = message.lower()

    service = str(arguments.get("service") or "").strip()
    # Match on a word boundary. A substring test counted "blog" as confirmed
    # because the repository URL happened to contain "blogapp", which is the
    # planner naming the service, not the user.
    named = bool(
        service
        and re.search(
            r"(?<![A-Za-z0-9_.-])" + re.escape(service.lower()) + r"(?![A-Za-z0-9_-])",
            lowered,
        )
    )
    if service and not named:
        items.append({
            "field": "service",
            "label": "서비스 이름",
            "question": f"서비스 이름을 `{service}`로 할까요? 다른 이름을 원하시면 알려주세요.",
            "examples": [service],
        })

    framework = str(arguments.get("framework") or "").strip()
    repo_url = str(arguments.get("repo_url") or "").strip()

    # Compiling from source on this host does not finish. A frontend build wants
    # gigabytes of RAM; the box has under one, so it swaps until the fifteen
    # minute build timeout kills it -- fifteen minutes the user spent waiting
    # for a failure that was certain from the start. Say so before the wait.
    # Both checks below are about the same decision, so they become one
    # question. Two entries for the same field drew the field twice in the form.
    reasons: list[str] = []
    options: list[str] = []

    if framework in SOURCE_BUILD_FRAMEWORKS and not source_build_is_affordable():
        reasons.append(
            f"`{framework}`는 서버에서 소스를 직접 빌드합니다. 이 서버는 메모리가 "
            "부족해 프론트엔드 빌드가 시간 초과로 실패할 가능성이 높습니다. "
            "로컬에서 빌드한 결과물을 저장소에 올린 뒤 `static`으로 배포하시는 "
            "편을 권합니다."
        )
        options.append("static")

    if repo_url and framework and framework != "existing":
        try:
            repository = execute_cli_skill(
                "repository.inspect",
                {"repo_url": repo_url},
                dry_run=False,
            )
        except Exception:
            repository = {}
        if repository.get("has_dockerfile"):
            reasons.append(
                "저장소에 이미 Dockerfile이 있습니다. 그대로 사용하려면 "
                "`existing`을 고르세요. 프리셋을 고르면 저장소의 Dockerfile은 "
                "사용되지 않습니다."
            )
            options.append("existing")

    if reasons:
        options.append(framework)
        items.append({
            "field": "framework",
            "label": "빌드 방식",
            "question": "\n".join(reasons) + "\n어떻게 할까요?",
            "examples": list(dict.fromkeys(options)),
        })
    return items


def deploy_form_hint(
    arguments: dict[str, Any] | None,
    missing: list[dict[str, Any]] | None,
    field_errors: dict[str, str] | None,
) -> dict[str, Any]:
    return {
        "type": "form",
        "form": "service.deploy",
        "title": "새 서비스 배포",
        "required": ["service", "repo_url", "framework"],
        "optional": ["is_web", "host_port", "environment_names"],
        "arguments": arguments or {},
        "missing": missing or [],
        "field_errors": field_errors or {},
        "choices": {
            # Read the presets instead of restating them. The two hand-written
            # copies this replaces had already drifted and lost spring-gradle.
            "framework": [item["id"] for item in preset_catalog()],
            "is_web": [True, False],
            "optional_mode": ["defaults", "custom"],
        },
    }


def ui_hint_for_response(
    *,
    skill: str | None,
    arguments: dict[str, Any] | None = None,
    missing: list[dict[str, Any]] | None = None,
    requires_approval: bool = False,
    preview: dict[str, Any] | None = None,
    field_errors: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    if not skill:
        return None
    if requires_approval:
        return {
            "type": "approval",
            "skill": skill,
            "title": "실행 전 승인",
        }
    if skill == "service.deploy" and (missing or field_errors):
        return deploy_form_hint(arguments, missing, field_errors)
    return None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=8, max_length=128)
    context: dict[str, Any] | None = None


class ExecuteRequest(BaseModel):
    skill: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    session_id: str | None = Field(default=None, min_length=8, max_length=128)
    resume: dict[str, Any] | None = None


class PreviewRequest(BaseModel):
    skill: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health():
    llm = llm_status()
    return {
        "status": "ok",
        "llm_configured": llm["configured"],
        "llm_models": llm["models"],
        "llm_cooldowns": llm["cooldowns"],
    }


@app.get("/skills")
def skills():
    return {"skills": skill_documents()}


@app.get("/frameworks")
def frameworks():
    return {"frameworks": preset_catalog()}


@app.get("/commands")
def commands(http_request: Request):
    namespace = authenticated_namespace(http_request)
    return scoped_command_contracts(namespace)


@app.get("/schema/{skill}")
def schema(skill: str, http_request: Request):
    try:
        namespace = authenticated_namespace(http_request)
        return scoped_command_contract(skill, namespace)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/catalog")
def catalog(http_request: Request):
    namespace = authenticated_namespace(http_request)
    return scoped_command_catalog(namespace)


@app.get("/project-summaries")
def project_summary_catalog(http_request: Request):
    namespace = authenticated_namespace(http_request)
    return project_summaries(namespace)


@app.post("/chat")
def chat(request: ChatRequest, http_request: Request):
    namespace = authenticated_namespace(http_request)
    session_context, session_history = load_session(
        request.session_id,
        request.context,
    )
    request.context = session_context

    def respond(
        payload: dict[str, Any],
        transcript: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return remember_response(
            request.session_id, request.message, payload, transcript
        )

    def scoped_execute(
        skill: str,
        arguments: dict[str, Any],
        *,
        dry_run: bool,
    ) -> dict[str, Any]:
        # /execute and /preview scope every call to the caller's namespace.
        # This path did not, so a namespace token could read another project's
        # logs, status, and project list just by asking for them in chat.
        scoped = namespace_scoped_arguments(skill, arguments, namespace)
        result = execute_cli_skill(skill, scoped, dry_run=dry_run)
        if dry_run:
            return result
        return namespace_scoped_result(skill, result, namespace)

    def original_request() -> str:
        if request.context:
            return str(request.context.get("original_request") or request.message)
        return request.message

    try:
        try:
            plan = call_llm(
                request.message,
                skill_documents(),
                request.context or None,
                session_history,
            )
        except Exception as exc:
            # There is no keyword router behind this any more. Guessing produced
            # confident answers to questions nobody asked; say what happened.
            return respond({
                "mode": "degraded",
                "kind": "clarification",
                "message": (
                    "지금은 요청을 처리하지 못했습니다. 잠시 후 다시 말씀해 주세요.\n\n"
                    f"(원인: {exc})"
                ),
                "requires_approval": False,
            })

        if plan.get("kind") == "answer":
            return respond({
                "mode": "llm",
                "kind": "clarification" if request.context else "help",
                "message": plan["message"],
                "model": plan.get("model"),
                # The stored task stays on the server for the next turn, but it
                # is not what this reply is about. Echoing its arguments handed
                # the console values from an older request.
                "context": request.context,
                "requires_approval": False,
            }, plan.get("transcript"))

        skill = plan["skill"]
        arguments = arguments_for_plan(
            skill,
            request.context,
            plan.get("arguments", {}),
        )

        if skill in read_only_skills():
            result = scoped_execute(skill, arguments, dry_run=False)
            final = naturalize_read_only_result(
                skill,
                result,
                request.message,
                request.context,
                plan.get("model"),
            )
            return respond({
                "mode": "llm",
                "message": final["message"],
                "skill": skill,
                "model": final.get("model"),
                "result": final["result"],
                "requires_approval": False,
            }, plan.get("transcript"))

        try:
            preview = scoped_execute(skill, arguments, dry_run=True)
        except SkillError as exc:
            error_payload = skill_error_payload(exc)
            field_errors = field_errors_from_error(error_payload)
            missing_from_error = missing_from_field_errors(field_errors)
            final = naturalize_mutation_message(
                purpose="error",
                skill=skill,
                arguments=arguments,
                user_message=request.message,
                error=error_payload,
                model_hint=plan.get("model"),
            )
            return respond({
                "mode": "llm",
                "kind": "clarification",
                "message": final["message"],
                "skill": skill,
                "model": final.get("model"),
                "arguments": arguments,
                "missing": missing_from_error,
                "context": {
                    "original_request": original_request(),
                    "skill": skill,
                    "arguments": arguments,
                    "missing": missing_from_error,
                    "last_error": error_payload,
                },
                "error": error_payload,
                "field_errors": field_errors,
                "ui": ui_hint_for_response(
                    skill=skill,
                    arguments=arguments,
                    missing=missing_from_error,
                    field_errors=field_errors,
                ),
                "requires_approval": False,
            }, plan.get("transcript"))

        if not preview.get("needs_input"):
            # A choice the user never made becomes a question rather than
            # something waiting behind an approve button.
            unconfirmed = deploy_confirmations(request.message, skill, arguments)
            if unconfirmed:
                preview = dict(preview)
                preview["needs_input"] = unconfirmed
                preview.setdefault(
                    "message",
                    "\n".join(str(item["question"]) for item in unconfirmed),
                )

        if preview.get("needs_input"):
            final = naturalize_mutation_message(
                purpose="missing",
                skill=skill,
                arguments=arguments,
                user_message=request.message,
                preview=preview,
                missing=preview["needs_input"],
                model_hint=plan.get("model"),
            )
            return respond({
                "mode": "llm",
                "kind": "clarification",
                "message": final["message"] or preview["message"],
                "skill": skill,
                "model": final.get("model") or plan.get("model"),
                "arguments": arguments,
                "missing": preview["needs_input"],
                "context": {
                    "original_request": original_request(),
                    "skill": skill,
                    "arguments": arguments,
                    "missing": preview["needs_input"],
                },
                "ui": ui_hint_for_response(
                    skill=skill,
                    arguments=arguments,
                    missing=preview["needs_input"],
                    preview=preview,
                ),
                "requires_approval": False,
            }, plan.get("transcript"))

        final = naturalize_mutation_message(
            purpose="approval",
            skill=skill,
            arguments=arguments,
            user_message=request.message,
            preview=preview,
            model_hint=plan.get("model"),
        )
        return respond({
            "mode": "llm",
            "message": final["message"],
            "skill": skill,
            "model": final.get("model") or plan.get("model"),
            "arguments": arguments,
            "preview": preview,
            "ui": ui_hint_for_response(
                skill=skill,
                arguments=arguments,
                requires_approval=True,
                preview=preview,
            ),
            "resume": request.context.get("resume") if request.context else None,
            "requires_approval": True,
        }, plan.get("transcript"))
    except HTTPException:
        # A namespace denial is an answer, not a planner failure.
        raise
    except (SkillError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=error_detail(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planner failed: {exc}") from exc


@app.post("/execute")
def execute(request: ExecuteRequest, http_request: Request):
    if request.skill not in read_only_skills() and not request.approved:
        raise HTTPException(status_code=409, detail="Explicit approval is required.")
    try:
        namespace = authenticated_namespace(http_request)
        arguments = namespace_scoped_arguments(
            request.skill,
            request.arguments,
            namespace,
        )
        if os.getenv("PLATFORM_API"):
            result = execute_cli_skill(
                request.skill,
                arguments,
                dry_run=False,
                approved=request.approved,
            )
        else:
            result = execute_skill(request.skill, arguments, dry_run=False)
        response = {
            "skill": request.skill,
            "namespace": namespace,
            "result": namespace_scoped_result(request.skill, result, namespace),
        }
        remember_execution(request.session_id, request.skill, request.resume)
        return response
    except HTTPException:
        raise
    except (SkillError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=error_detail(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/preview")
def preview(request: PreviewRequest, http_request: Request):
    if request.skill in read_only_skills():
        raise HTTPException(status_code=400, detail="Preview is only for mutation skills.")
    try:
        namespace = authenticated_namespace(http_request)
        arguments = namespace_scoped_arguments(
            request.skill,
            request.arguments,
            namespace,
        )
        return {
            "skill": request.skill,
            "namespace": namespace,
            "preview": (
                execute_cli_skill(
                    request.skill,
                    arguments,
                    dry_run=True,
                )
                if os.getenv("PLATFORM_API")
                else execute_skill(request.skill, arguments, dry_run=True)
            ),
        }
    except HTTPException:
        raise
    except (SkillError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=error_detail(exc)) from exc
