from __future__ import annotations

import os
import re
import json
import threading
import time
from typing import Any
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from deployment_presets import preset_catalog

from runtime import (
    READ_ONLY_SKILLS,
    SkillError,
    attach_platform_api_to_existing_control_networks,
    call_llm,
    command_catalog,
    command_contract,
    command_contracts,
    execute_skill,
    execute_cli_skill,
    fallback_plan,
    llm_status,
    skill_documents,
)

app = FastAPI(title="Cloud Platform Skill Agent", version="0.1.0")
PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", "/srv/projects"))
SESSION_TTL_SECONDS = 60 * 60 * 12
SESSION_HISTORY_LIMIT = 24
SESSION_LOCK = threading.Lock()
SESSION_STORE = Path(
    os.getenv("SESSION_STORE", "/var/log/skill-agent/sessions.json")
)


def namespace_tokens() -> dict[str, str]:
    tokens: dict[str, str] = {}
    store = Path(
        os.getenv("NAMESPACE_TOKEN_STORE", "/var/log/skill-agent/namespace_tokens.json")
    )
    try:
        data = json.loads(store.read_text())
        if isinstance(data, dict):
            tokens.update({str(token): str(namespace) for token, namespace in data.items()})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    raw = os.getenv("PLATFORM_NAMESPACE_TOKENS", "").strip()
    if not raw:
        return tokens
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid PLATFORM_NAMESPACE_TOKENS JSON",
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="PLATFORM_NAMESPACE_TOKENS must be a JSON object",
        )
    tokens.update({str(token): str(namespace) for token, namespace in data.items()})
    return tokens


def authenticated_namespace(http_request: Request) -> str | None:
    # A process with PLATFORM_API configured is an agent/client plane. It
    # receives dashboard or project-agent requests and then calls platform-api
    # with its own token through the CLI. Inbound namespace enforcement belongs
    # to the platform-api process only.
    if os.getenv("PLATFORM_API"):
        return None
    tokens = namespace_tokens()
    root_token = os.getenv("PLATFORM_ROOT_TOKEN", "").strip()
    if not tokens and not root_token:
        return None
    header = http_request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token is required")
    token = header.removeprefix("Bearer ").strip()
    if root_token and token == root_token:
        return None
    namespace = tokens.get(token)
    if not namespace:
        raise HTTPException(status_code=403, detail="Invalid namespace token")
    return namespace


def namespace_scoped_arguments(
    skill: str,
    arguments: dict[str, Any],
    namespace: str | None,
) -> dict[str, Any]:
    if not namespace:
        return arguments
    scoped = dict(arguments)
    if skill in {
        "service.deploy",
        "service.redeploy",
        "service.status",
        "service.logs",
        "service.control",
        "port.manage",
    }:
        requested = scoped.get("project")
        if requested and str(requested) != namespace:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Namespace token can only access project {namespace!r}; "
                    f"requested {requested!r}"
                ),
            )
        scoped["project"] = namespace
    if skill == "entity.resolve" and scoped.get("entity") == "service":
        requested = scoped.get("project")
        if requested and str(requested) != namespace:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Namespace token can only resolve services in {namespace!r}; "
                    f"requested {requested!r}"
                ),
            )
        scoped["project"] = namespace
    if skill in {"project.create", "project.ensure_agent", "server.health", "qa.run"}:
        raise HTTPException(
            status_code=403,
            detail=f"{skill} is only available to the root/admin plane",
        )
    return scoped


def namespace_scoped_result(
    skill: str,
    result: dict[str, Any],
    namespace: str | None,
) -> dict[str, Any]:
    if not namespace or skill != "project.list":
        return result
    projects = [
        item
        for item in result.get("projects", [])
        if str(item.get("name")) == namespace
    ]
    incomplete = [
        item
        for item in result.get("incomplete_projects", [])
        if str(item.get("name")) == namespace
    ]
    return {"projects": projects, "incomplete_projects": incomplete}


def load_persisted_sessions() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(SESSION_STORE.read_text())
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


SESSIONS: dict[str, dict[str, Any]] = load_persisted_sessions()
GITHUB_URL_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?"
)
FRAMEWORK_ALIASES = {
    "기존 dockerfile": "existing",
    "기존 도커파일": "existing",
    "existing": "existing",
    "static": "static",
    "정적": "static",
    "바닐라 javascript": "static",
    "바닐라 자바스크립트": "static",
    "vite": "vite",
    "react": "react",
    "리액트": "react",
    "next.js": "nextjs",
    "nextjs": "nextjs",
    "express": "express",
    "nest": "express",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "spring maven": "spring-maven",
    "spring gradle": "spring-gradle",
    "go": "go",
    "golang": "go",
}


@app.on_event("startup")
def connect_existing_control_networks() -> None:
    if os.getenv("PLATFORM_API"):
        return
    try:
        attach_platform_api_to_existing_control_networks()
    except Exception:
        # Startup should not fail only because Docker is temporarily slow.
        pass

HELP_COMMANDS = {
    "도움말",
    "도움",
    "help",
    "명령어",
    "기능",
    "뭐 할 수 있어",
    "뭘 할 수 있어",
    "무엇을 할 수 있어",
}

HELP_MESSAGE = """다음과 같이 요청할 수 있습니다.

- **도움말·문의**: `포트 변경 방법 알려줘`, `배포 절차를 찾아줘`
- **신규 프로젝트**: `새 프로젝트를 만들고 싶어`, `sample 프로젝트 만들어줘`
- **서버 상태**: `서버 상태를 확인해줘`
- **프로젝트 목록**: `프로젝트와 서비스 목록 보여줘`
- **서비스 상태**: `demoa의 demo-a 상태를 확인해줘`
- **최근 로그**: `demoa의 demo-a 로그 40줄 보여줘`
- **서비스 제어**: `demoa의 demo-a를 시작해줘`, `중지해줘`, `재시작해줘`
- **새 서비스 배포**: `demoa 프로젝트에 https://github.com/example/app 저장소를 frontend 서비스로 Vite 프리셋으로 배포해줘`
- **기존 서비스 재배포**: `demoa의 demo-a를 최신 Git 코드로 재배포해줘`
- **포트 추천**: `사용 가능한 포트를 추천해줘`
- **포트 변경**: `demoa의 demo-a 호스트 포트를 9002로 바꿔줘`
- **QA 점검**: `전체 QA 점검해줘`

프로젝트 생성, 서비스 배포·재배포, 시작·중지·재시작과 포트 변경은 실행 전에 계획을 보여주고 승인을 요청합니다.
`도움말`을 입력하면 이 안내를 다시 볼 수 있습니다."""

DEPLOYMENT_GUIDE = """### 배포 절차 핵심 요약

1. **프로젝트 준비**
   - 서비스는 반드시 프로젝트 안에 들어갑니다.
   - 기존 프로젝트가 없다면 먼저 `신규 프로젝트를 만들고 싶어`라고 요청하세요.
2. **Git 저장소 준비**
   - 공개 GitHub HTTPS URL이 필요합니다.
   - 저장소 최상위에 `Dockerfile`이 있어야 합니다.
3. **애플리케이션 설정**
   - 프레임워크 프리셋을 선택하면 Dockerfile과 컨테이너 포트 `3000`을 자동 적용합니다.
   - 고급 설정이 필요한 경우에만 `기존 Dockerfile 사용`을 선택합니다.
4. **새 서비스 배포에 필요한 정보**
   - 기존 프로젝트 이름
   - 새 서비스 이름
   - 공개 GitHub 저장소 URL
   - 프레임워크 프리셋
   - 선택사항: 호스트 포트, 웹 서비스 여부, 환경변수 이름
5. **배포 실행**
   - Agent가 빈 호스트 포트를 선택하고, Git clone → 이미지 build → Compose 등록 → 실행 검증을 수행합니다.
   - 실제 변경 전에는 반드시 미리보기와 승인 단계가 표시됩니다.
6. **기존 서비스 업데이트**
   - GitHub에 새 코드를 push한 뒤 `프로젝트의 서비스를 최신 코드로 재배포해줘`라고 요청하세요.
   - 기존 폴더에서 `git pull`하지 않고 새 소스를 별도로 clone·build한 뒤 성공할 때만 교체합니다.

환경변수 실제 값은 LLM에 입력하지 말고 배포 후 대시보드의 ⚙️ 버튼에서 입력하세요.

예시: `demoa 프로젝트에 https://github.com/example/app 저장소를 frontend 서비스로 Vite 프리셋으로 배포해줘.`"""

DEPLOYMENT_GUIDE_PHRASES = {
    "배포 절차",
    "배포절차",
    "배포 방법",
    "배포방법",
    "빌드 매뉴얼",
    "build manual",
    "서비스 배포 방법",
}


def preferred_skill_for(message: str, context: dict[str, Any] | None) -> str | None:
    text = message.lower()
    if GITHUB_URL_RE.search(message) and any(
        word in text for word in ("배포", "등록", "추가", "서비스", "저장소", "github")
    ):
        return "service.deploy"
    if any(
        phrase in text
        for phrase in (
            "신규 프로젝트",
            "새 프로젝트",
            "프로젝트를 새로",
            "프로젝트 생성해",
            "프로젝트 만들어",
            "프로젝트를 만들어",
            "프로젝트 복구",
            "프로젝트를 복구",
        )
    ):
        return "project.create"
    if "서비스" in text and any(word in text for word in ("재배포", "최신 코드", "다시 배포", "새 이미지")):
        return "service.redeploy"
    if "서비스" in text and any(word in text for word in ("새로", "신규", "추가", "새 서비스", "등록")):
        return "service.deploy"
    if "서비스" in text and "배포" in text:
        return "service.deploy"
    if context and context.get("skill"):
        return str(context["skill"])
    return None


def ambiguity_for(message: str, context: dict[str, Any] | None) -> dict[str, Any] | None:
    if context:
        return None
    text = message.lower()
    if "서비스" in text and "다시" in text and not any(
        word in text for word in ("재시작", "restart", "최신", "git", "깃", "새 이미지", "재배포")
    ):
        return {
            "mode": "local",
            "kind": "clarification",
            "message": (
                "`다시`가 어떤 작업인지 확인해주세요.\n\n"
                "1. **컨테이너 재시작** — 현재 이미지를 그대로 다시 실행\n"
                "2. **최신 코드 재배포** — GitHub를 새로 clone하고 이미지를 다시 build\n\n"
                "예: `demoa의 frontend를 재시작해줘` 또는 "
                "`demoa의 frontend를 최신 코드로 재배포해줘`"
            ),
            "skill": None,
            "arguments": {},
            "missing": [{"field": "intent", "label": "재시작 또는 최신 코드 재배포"}],
            "choices": [
                {"skill": "service.control", "label": "컨테이너 재시작"},
                {"skill": "service.redeploy", "label": "최신 코드 재배포"},
            ],
            "context": {
                "original_request": message,
                "skill": None,
                "arguments": {},
                "missing": [{"field": "intent", "label": "재시작 또는 최신 코드 재배포"}],
            },
            "requires_approval": False,
        }
    if "배포" in text and "서비스" not in text and not any(
        word in text for word in ("절차", "방법", "매뉴얼")
    ):
        return {
            "mode": "local",
            "kind": "clarification",
            "message": (
                "어떤 배포 작업인지 확인해주세요.\n\n"
                "1. 새 서비스를 GitHub에서 처음 배포\n"
                "2. 기존 서비스를 최신 Git 코드로 재배포\n\n"
                "원하는 작업과 프로젝트·서비스 이름을 함께 알려주세요."
            ),
            "skill": None,
            "arguments": {},
            "missing": [{"field": "intent", "label": "신규 배포 또는 기존 서비스 재배포"}],
            "choices": [
                {"skill": "service.deploy", "label": "새 서비스 배포"},
                {"skill": "service.redeploy", "label": "기존 서비스 재배포"},
            ],
            "context": {
                "original_request": message,
                "skill": None,
                "arguments": {},
                "missing": [{"field": "intent", "label": "신규 배포 또는 기존 서비스 재배포"}],
            },
            "requires_approval": False,
        }
    return None


def explicit_name(message: str, label: str) -> str | None:
    patterns = {
        "project": [
            r"(?:기존\s*)?프로젝트\s*(?:이름)?\s*(?:은|는|:|=)?\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})",
            r"([A-Za-z0-9][A-Za-z0-9_.-]{0,63})\s*프로젝트",
        ],
        "service": [
            r"(?:새\s*)?서비스\s*(?:이름)?\s*(?:은|는|:|=)?\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})",
            r"([A-Za-z0-9][A-Za-z0-9_.-]{0,63})\s*서비스",
            r"([A-Za-z0-9][A-Za-z0-9_.-]{0,63})\s*(?:를|을)?\s*(?:재배포|다시\s*배포|상태|로그|시작|중지|정지|재시작|restart|stop|start)",
        ],
    }
    for pattern in patterns[label]:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def slot_value_from_reply(message: str) -> str | None:
    text = GITHUB_URL_RE.sub("", message).strip()
    text = re.split(r"[,，\n]", text, maxsplit=1)[0].strip()
    patterns = [
        r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})\s*(?:로|으로)\s*(?:할래|해줘|만들어줘|생성해줘|진행해줘)?\s*$",
        r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})\s*(?:라고|이라|이라고|라니까)?\s*(?:할래|해줘|만들어줘|생성해줘|진행해줘)?\s*$",
        r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})\s*$",
    ]
    for pattern in patterns:
        match = re.fullmatch(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def explicit_arguments(message: str, skill: str) -> dict[str, Any]:
    lowered = message.lower()
    arguments: dict[str, Any] = {}
    if skill in {"project.create", "service.deploy", "service.redeploy"}:
        project = explicit_name(message, "project")
        if project:
            arguments["project"] = project
    if skill in {"service.deploy", "service.redeploy"}:
        service = explicit_name(message, "service")
        if service:
            arguments["service"] = service
    if skill == "service.deploy":
        url = GITHUB_URL_RE.search(message)
        if url:
            arguments["repo_url"] = url.group(0)
        for alias, framework in FRAMEWORK_ALIASES.items():
            if alias in lowered:
                arguments["framework"] = framework
                break
        container_port = re.search(
            r"컨테이너\s*포트(?:는|은|:|=)?\s*(\d{1,5})",
            message,
            re.IGNORECASE,
        )
        if container_port:
            arguments["container_port"] = int(container_port.group(1))
        host_port = re.search(
            r"호스트\s*포트(?:는|은|:|=)?\s*(9\d{3})",
            message,
            re.IGNORECASE,
        )
        if host_port:
            arguments["host_port"] = int(host_port.group(1))
        if any(
            phrase in lowered
            for phrase in (
                "백엔드",
                "backend",
                "api 서버",
                "api서비스",
                "api 서비스",
                "내부통신",
                "내부 통신",
                "외부 공개하지",
                "url 없",
                "포트 열지",
            )
        ):
            arguments["is_web"] = False
        if any(phrase in lowered for phrase in ("웹 서비스", "프론트", "frontend", "외부 공개")):
            arguments["is_web"] = True
        env_match = re.search(
            r"환경변수\s*(?:이름)?(?:은|는|:|=)?\s*([A-Za-z_][A-Za-z0-9_,\s]*)",
            message,
            re.IGNORECASE,
        )
        if env_match:
            arguments["environment_names"] = [
                item.strip()
                for item in env_match.group(1).split(",")
                if item.strip()
            ]
    return arguments


def strict_arguments(
    message: str,
    skill: str,
    context: dict[str, Any] | None,
    planner_arguments: dict[str, Any],
) -> dict[str, Any]:
    cli_verified_skills = {
        "service.status",
        "service.logs",
        "service.control",
        "port.manage",
    }
    if skill in cli_verified_skills:
        verified: dict[str, Any] = {}
        project = explicit_name(message, "project")
        service = explicit_name(message, "service")
        if project:
            resolution = execute_cli_skill(
                "entity.resolve",
                {"entity": "project", "query": project},
                dry_run=False,
            )
            if resolution["status"] == "exact":
                verified["project"] = resolution["match"]
        if service and verified.get("project"):
            resolution = execute_cli_skill(
                "entity.resolve",
                {
                    "entity": "service",
                    "query": service,
                    "project": verified["project"],
                },
                dry_run=False,
            )
            if resolution["status"] == "exact":
                verified["service"] = resolution["match"]
        lowered = message.lower()
        if skill == "service.control":
            if any(word in lowered for word in ("재시작", "restart")):
                verified["action"] = "restart"
            elif any(word in lowered for word in ("중지", "정지", "stop")):
                verified["action"] = "stop"
            elif any(word in lowered for word in ("시작", "start")):
                verified["action"] = "start"
        elif skill == "service.logs":
            lines = re.search(r"(\d{1,3})\s*줄", message)
            verified["lines"] = int(lines.group(1)) if lines else 40
        elif skill == "port.manage":
            host_port = re.search(
                r"호스트\s*포트(?:를|을|는|은|:|=)?\s*(\d{1,5})",
                message,
                re.IGNORECASE,
            )
            container_port = re.search(
                r"컨테이너\s*포트(?:를|을|는|은|:|=)?\s*(\d{1,5})",
                message,
                re.IGNORECASE,
            )
            if host_port:
                verified["operation"] = "change_host"
                verified["host_port"] = int(host_port.group(1))
            elif container_port:
                verified["operation"] = "change_container"
                verified["container_port"] = int(container_port.group(1))
        return verified
    if skill not in {"project.create", "service.deploy", "service.redeploy"}:
        return planner_arguments
    verified = {}
    if context and context.get("skill") == skill:
        verified.update(context.get("arguments") or {})
    explicit = explicit_arguments(message, skill)
    if skill in {"service.deploy", "service.redeploy"} and explicit.get("project"):
        resolution = execute_cli_skill(
            "entity.resolve",
            {"entity": "project", "query": explicit["project"]},
            dry_run=False,
        )
        if resolution["status"] == "exact":
            verified["project"] = resolution["match"]
        explicit.pop("project", None)
    if skill == "service.redeploy" and explicit.get("service"):
        project = verified.get("project")
        if project:
            resolution = execute_cli_skill(
                "entity.resolve",
                {
                    "entity": "service",
                    "query": explicit["service"],
                    "project": project,
                },
                dry_run=False,
            )
            if resolution["status"] == "exact":
                verified["service"] = resolution["match"]
            explicit.pop("service", None)
    if skill == "service.deploy" and explicit.get("framework"):
        resolution = execute_cli_skill(
            "entity.resolve",
            {"entity": "framework", "query": explicit["framework"]},
            dry_run=False,
        )
        if resolution["status"] == "exact":
            verified["framework"] = resolution["match"]
        explicit.pop("framework", None)
    verified.update(explicit)
    if skill in {"service.deploy", "service.redeploy"} and "project" not in verified:
        try:
            projects = execute_cli_skill("project.list", {}, dry_run=False).get(
                "projects",
                [],
            )
            mentioned = [
                str(item["name"])
                for item in projects
                if re.search(
                    rf"(?<![A-Za-z0-9_.-]){re.escape(str(item['name']))}"
                    rf"(?![A-Za-z0-9_.-])",
                    message,
                    re.IGNORECASE,
                )
            ]
            if len(mentioned) == 1:
                verified["project"] = mentioned[0]
        except (SkillError, KeyError, TypeError):
            pass
    missing_fields = {
        item.get("field")
        for item in (context or {}).get("missing", [])
    }
    bare = slot_value_from_reply(message)
    if len(missing_fields) == 1:
        field = next(iter(missing_fields))
        if field in {"project", "service"} and bare:
            if field == "project" and skill in {"service.deploy", "service.redeploy"}:
                resolution = execute_cli_skill(
                    "entity.resolve",
                    {"entity": "project", "query": bare},
                    dry_run=False,
                )
                if resolution["status"] == "exact":
                    verified[field] = resolution["match"]
            elif field == "service" and skill == "service.redeploy":
                project = verified.get("project")
                if project:
                    resolution = execute_cli_skill(
                        "entity.resolve",
                        {
                            "entity": "service",
                            "query": bare,
                            "project": project,
                        },
                        dry_run=False,
                    )
                    if resolution["status"] == "exact":
                        verified[field] = resolution["match"]
            elif field == "project" and skill == "project.create":
                verified[field] = bare
            else:
                verified[field] = bare
        elif field == "repo_url" and GITHUB_URL_RE.fullmatch(message.strip()):
            verified[field] = message.strip()
        elif field == "framework":
            framework_name = bare or message.strip()
            framework = FRAMEWORK_ALIASES.get(framework_name.lower())
            if framework:
                resolution = execute_cli_skill(
                    "entity.resolve",
                    {"entity": "framework", "query": framework},
                    dry_run=False,
                )
                if resolution["status"] == "exact":
                    verified[field] = resolution["match"]
    return verified


def affirmative(message: str) -> bool:
    normalized = re.sub(r"[\s.!?]+", "", message.lower())
    return any(
        phrase in normalized
        for phrase in (
            "맞아",
            "응",
            "어어",
            "그래",
            "그거야",
            "그걸로",
            "진행해",
            "맞습니다",
        )
    )


def negative(message: str) -> bool:
    normalized = re.sub(r"[\s.!?]+", "", message.lower())
    return any(
        phrase in normalized
        for phrase in ("아니", "아님", "틀려", "그거말고", "새로생성", "새로만들")
    )


def proposal_context(
    context: dict[str, Any] | None,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(context or {})
    updated.setdefault("arguments", {})
    updated["confirmed"] = dict(updated["arguments"])
    updated["proposed"] = proposal
    return updated


def proposal_response(
    context: dict[str, Any] | None,
    resolution: dict[str, Any],
    *,
    field: str,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    entity_labels = {
        "project": "프로젝트",
        "service": "서비스",
        "framework": "프레임워크",
    }
    label = entity_labels[resolution["entity"]]
    proposal = {
        "field": field,
        "entity": resolution["entity"],
        "query": resolution["query"],
        "candidate": resolution.get("match"),
        "candidates": resolution.get("candidates", []),
        "source": resolution.get("source"),
        "evidence": evidence or [],
    }
    updated = proposal_context(context, proposal)
    if resolution["status"] == "single":
        candidate = resolution["match"]
        reason = resolution["candidates"][0]["reason"]
        if resolution.get("source") == "repository.inspect CLI":
            message = (
                f"CLI가 저장소 파일과 의존성을 읽기 전용으로 확인한 결과, "
                f"**`{candidate}`** 프리셋 후보가 하나 발견됐습니다.\n\n"
                f"이 프리셋으로 진행할까요?\n\n"
                f"- 맞으면: `맞아` 또는 `그걸로 진행해줘`\n"
                f"- 아니면: 실제 {label} 이름을 알려주세요."
            )
        else:
            message = (
                f"CLI에서 `{resolution['query']}`와 정확히 일치하는 {label}를 찾지 못했습니다.\n\n"
                f"실제 목록에서 가장 가까운 값은 **`{candidate}`**입니다 "
                f"({reason}). 이 값을 말씀하신 게 맞나요?\n\n"
                f"- 맞으면: `맞아` 또는 `그걸로 진행해줘`\n"
                f"- 아니면: 정확한 {label} 이름을 알려주세요."
            )
        if resolution["entity"] == "project":
            message += (
                f"\n- 새 프로젝트라면: **`{resolution['query']}`를 새로 생성해줘**"
            )
    elif resolution["status"] == "multiple":
        choices = "\n".join(
            f"{index}. `{item['value']}`"
            for index, item in enumerate(resolution["candidates"], 1)
        )
        message = (
            f"CLI 실제 목록에서 `{resolution['query']}`와 비슷한 {label}가 여러 개 발견됐습니다.\n\n"
            f"{choices}\n\n번호나 정확한 이름으로 선택해주세요."
        )
    else:
        message = (
            f"CLI 실제 목록에는 `{resolution['query']}`와 일치하거나 충분히 비슷한 "
            f"{label}가 없습니다.\n\n정확한 이름을 다시 알려주세요."
        )
        if resolution["entity"] == "project":
            message += (
                f"\n새 프로젝트라면 **`{resolution['query']}`를 새로 생성해줘**라고 요청할 수 있습니다."
            )
    if evidence:
        message += "\n\nCLI 확인 근거: " + ", ".join(evidence)
    return {
        "mode": "local",
        "kind": "clarification",
        "message": message,
        "skill": updated.get("skill"),
        "arguments": updated.get("arguments", {}),
        "missing": updated.get("missing", []),
        "context": updated,
        "requires_approval": False,
    }


def handle_proposed_input(
    message: str,
    context: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    proposal = (context or {}).get("proposed")
    if not proposal:
        return context, None
    candidates = proposal.get("candidates") or []
    selected = proposal.get("candidate")
    number = re.fullmatch(r"\s*(\d+)\s*(?:번)?\s*", message)
    if number and candidates:
        index = int(number.group(1)) - 1
        if 0 <= index < len(candidates):
            selected = candidates[index]["value"]
    elif not affirmative(message):
        selected = None

    if selected and (affirmative(message) or number):
        updated = dict(context or {})
        arguments = dict(updated.get("arguments") or {})
        arguments[proposal["field"]] = selected
        updated["arguments"] = arguments
        updated["confirmed"] = dict(arguments)
        updated["missing"] = [
            item
            for item in updated.get("missing", [])
            if item.get("field") not in arguments
        ]
        updated.pop("proposed", None)
        return updated, None

    if negative(message):
        if (
            proposal["entity"] == "project"
            and any(word in re.sub(r"\s+", "", message.lower()) for word in ("새로", "생성", "만들"))
        ):
            project = proposal["query"]
            preview = execute_cli_skill(
                "project.create",
                {"project": project},
                dry_run=True,
            )
            resume = dict(context or {})
            resume.pop("proposed", None)
            return context, {
                "mode": "local",
                "message": (
                    f"`{project}`는 기존 프로젝트가 아닌 새 프로젝트로 생성하겠습니다. "
                    "아래 계획을 확인하고 승인해주세요."
                ),
                "skill": "project.create",
                "arguments": {"project": project},
                "preview": preview,
                "resume": resume,
                "requires_approval": True,
            }
        updated = dict(context or {})
        updated.pop("proposed", None)
        return updated, {
            "mode": "local",
            "kind": "clarification",
            "message": (
                "알겠습니다. 제안한 후보는 사용하지 않겠습니다. "
                "CLI에서 확인할 정확한 이름을 다시 알려주세요."
            ),
            "skill": updated.get("skill"),
            "arguments": updated.get("arguments", {}),
            "missing": updated.get("missing", []),
            "context": updated,
            "requires_approval": False,
        }
    if re.search(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,63}", message):
        updated = dict(context or {})
        updated.pop("proposed", None)
        return updated, None
    return context, {
        "mode": "local",
        "kind": "clarification",
        "message": "제안한 후보가 맞는지 `맞아` 또는 `아니야`로 확인해주세요.",
        "skill": context.get("skill") if context else None,
        "arguments": (context or {}).get("arguments", {}),
        "missing": (context or {}).get("missing", []),
        "context": context,
        "requires_approval": False,
    }


def cli_proposal_for_input(
    message: str,
    skill: str | None,
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if skill not in {"service.deploy", "service.redeploy"}:
        return None
    working_context = dict(context or {})
    arguments = dict(working_context.get("arguments") or {})
    explicit = explicit_arguments(message, skill)
    for field, value in explicit.items():
        if field != "project":
            arguments[field] = value
    working_context["arguments"] = arguments
    working_context["confirmed"] = dict(arguments)
    working_context["missing"] = [
        item
        for item in working_context.get("missing", [])
        if item.get("field") not in arguments
    ]
    project_query = explicit.get("project")
    if not project_query:
        leading_project = re.match(
            r"\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,63})(?:에|의)\s",
            message,
        )
        if leading_project:
            project_query = leading_project.group(1)
    if not project_query and "project" not in arguments:
        bare = message.strip()
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", bare):
            project_query = bare
    if project_query and "project" not in arguments:
        resolution = execute_cli_skill(
            "entity.resolve",
            {"entity": "project", "query": project_query},
            dry_run=False,
        )
        if resolution["status"] != "exact":
            return proposal_response(working_context, resolution, field="project")
    if skill == "service.redeploy":
        project = arguments.get("project")
        service_query = explicit.get("service")
        if project and service_query and "service" not in arguments:
            resolution = execute_cli_skill(
                "entity.resolve",
                {
                    "entity": "service",
                    "query": service_query,
                    "project": project,
                },
                dry_run=False,
            )
            if resolution["status"] != "exact":
                return proposal_response(working_context, resolution, field="service")
    missing = {item.get("field") for item in (context or {}).get("missing", [])}
    if skill == "service.deploy" and "framework" in missing:
        bare = message.strip().lower()
        if (
            re.fullmatch(r"[A-Za-z0-9_. -]{2,40}", bare)
            and bare not in FRAMEWORK_ALIASES
        ):
            resolution = execute_cli_skill(
                "entity.resolve",
                {"entity": "framework", "query": bare},
                dry_run=False,
            )
            if resolution["status"] != "none":
                return proposal_response(working_context, resolution, field="framework")
    return None


def project_state(name: str) -> str:
    path = PROJECTS_ROOT / name
    if not path.exists():
        return "missing"
    if not (path / "docker-compose.yml").is_file():
        return "incomplete"
    return "valid"


def project_problem_response(
    skill: str,
    arguments: dict[str, Any],
    request: "ChatRequest",
) -> dict[str, Any] | None:
    if skill not in {"service.deploy", "service.redeploy"}:
        return None
    project = arguments.get("project")
    if not project:
        return None
    state = project_state(str(project))
    if state == "valid":
        return None

    if state == "incomplete":
        message = (
            f"`{project}` 디렉터리는 존재하지만 `docker-compose.yml`이 없어 "
            "완전한 관리 프로젝트가 아닙니다.\n\n"
            "이 프로젝트를 복구하면 빈 Compose 파일을 만든 뒤 서비스 배포를 계속할 수 있습니다. "
            f"`{project} 프로젝트를 복구해줘`라고 요청해주세요."
        )
    else:
        message = (
            f"`{project}` 프로젝트는 서버의 관리 프로젝트 목록에 없습니다.\n\n"
            f"새 프로젝트라면 `{project} 프로젝트를 만들어줘`라고 요청한 뒤 "
            "서비스 배포를 다시 진행해주세요."
        )
    return {
        "mode": "local",
        "kind": "clarification",
        "message": message,
        "skill": skill,
        "arguments": {
            key: value for key, value in arguments.items() if key != "project"
        },
        "missing": [{"field": "project", "label": "유효한 기존 프로젝트"}],
        "choices": [
            {
                "skill": "project.create",
                "label": (
                    f"{project} 프로젝트 복구"
                    if state == "incomplete"
                    else f"{project} 프로젝트 생성"
                ),
                "arguments": {"project": project},
            }
        ],
        "context": {
            "original_request": (
                request.context.get("original_request")
                if request.context
                else request.message
            ),
            "skill": skill,
            "arguments": {
                key: value for key, value in arguments.items() if key != "project"
            },
            "missing": [{"field": "project", "label": "유효한 기존 프로젝트"}],
        },
        "requires_approval": False,
    }


def no_project_transition(
    message: str,
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not context or context.get("skill") != "service.deploy":
        return None
    normalized = re.sub(r"\s+", "", message.lower())
    if not any(
        phrase in normalized
        for phrase in ("프로젝트없어", "기존프로젝트없어", "프로젝트없다", "없다니까")
    ):
        return None
    return {
        "mode": "local",
        "kind": "clarification",
        "message": (
            "기존 프로젝트가 없다면 먼저 새 프로젝트를 만들어야 합니다.\n\n"
            "생성할 프로젝트 이름을 알려주세요. 예: `rea 프로젝트를 만들어줘`"
        ),
        "skill": "project.create",
        "arguments": {},
        "missing": [{"field": "project", "label": "새 프로젝트 이름"}],
        "context": {
            "original_request": context.get("original_request"),
            "skill": "project.create",
            "arguments": {},
            "missing": [{"field": "project", "label": "새 프로젝트 이름"}],
            "resume": context,
        },
        "requires_approval": False,
    }


def confirmed_information(arguments: dict[str, Any]) -> str:
    labels = {
        "project": "프로젝트",
        "service": "서비스",
        "repo_url": "GitHub 저장소",
        "framework": "프레임워크",
        "container_port": "컨테이너 포트",
        "host_port": "호스트 포트",
        "environment_names": "환경변수 이름",
    }
    lines = []
    for key, label in labels.items():
        value = arguments.get(key)
        if value not in (None, "", []):
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value)
            lines.append(f"- **{label}:** `{value}`")
    if not lines:
        return ""
    return "### 지금까지 확인된 정보\n\n" + "\n".join(lines)


def optional_settings_message(optional: list[str] | None) -> str:
    if not optional:
        return ""
    return (
        "선택 설정은 지금 생략해도 됩니다. "
        "생략하면 기본값으로 진행하고, 나중에 변경할 수 있습니다.\n"
        + "\n".join(f"- {item}" for item in optional)
        + "\n\n정하고 싶은 항목만 알려주세요. 모두 생략하려면 필수 정보만 알려주면 됩니다."
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
        if client_context and not session.get("context"):
            session["context"] = client_context
        session["updated_at"] = now
        context = session.get("context")
        history = list(session.get("history") or [])
    return context, history


def persist_sessions_locked() -> None:
    SESSION_STORE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SESSION_STORE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(SESSIONS, ensure_ascii=False, default=str)
    )
    temporary.replace(SESSION_STORE)


def remember_response(
    session_id: str | None,
    user_message: str,
    response: dict[str, Any],
) -> dict[str, Any]:
    if not session_id:
        return response
    assistant_message = str(response.get("message", "")).strip()
    with SESSION_LOCK:
        session = SESSIONS.setdefault(
            session_id,
            {"context": None, "history": [], "updated_at": time.time()},
        )
        history = session.setdefault("history", [])
        history.append({"role": "user", "content": user_message})
        if assistant_message:
            history.append({"role": "assistant", "content": assistant_message})
        session["history"] = history[-SESSION_HISTORY_LIMIT:]
        if "context" in response:
            session["context"] = response.get("context")
        elif response.get("requires_approval"):
            session["context"] = {
                "original_request": user_message,
                "skill": response.get("skill"),
                "arguments": response.get("arguments", {}),
                "missing": [],
            }
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
        history = session.setdefault("history", [])
        history.append(
            {
                "role": "assistant",
                "content": f"{skill} 작업이 승인되어 실행과 검증을 완료했습니다.",
            }
        )
        session["history"] = history[-SESSION_HISTORY_LIMIT:]
        session["updated_at"] = time.time()
        persist_sessions_locked()


def render_server_health(result: dict[str, Any]) -> str:
    docker_state = "정상" if result.get("docker") else "오류"
    lines = [
        "### 서버 상태",
        "",
        f"- Docker 연결: **{docker_state}**",
        f"- 컨테이너: **{result.get('running', 0)}/{result.get('containers', 0)} 실행 중**",
        f"- 메모리 사용률: **{result.get('memory_percent', 0)}%**",
        f"- 디스크 사용률: **{result.get('disk_percent', 0)}%**",
    ]
    restarting = result.get("restarting") or []
    unhealthy = result.get("unhealthy") or []
    lines.append(
        f"- 재시작 중: **{', '.join(restarting) if restarting else '없음'}**"
    )
    lines.append(
        f"- 비정상 헬스체크: **{', '.join(unhealthy) if unhealthy else '없음'}**"
    )
    details = result.get("container_details") or []
    if details:
        lines.extend(["", "### Docker 컨테이너"])
        for item in details:
            health = f", health={item['health']}" if item.get("health") else ""
            ports = ", ".join(
                f"{port.get('host')}→{port.get('container')}"
                for port in item.get("ports", [])
                if port.get("host")
            )
            port_text = f", ports={ports}" if ports else ""
            lines.append(
                f"- `{item['name']}`: **{item['status']}**{health}{port_text}"
            )
    projects = (result.get("projects") or {}).get("projects") or []
    if projects:
        lines.extend(["", "### 프로젝트와 서비스"])
        for project in projects:
            services = ", ".join(project.get("services") or []) or "서비스 없음"
            lines.append(f"- `{project['name']}`: {services}")
    return "\n".join(lines)


def render_read_only_result(skill: str, result: dict[str, Any]) -> str:
    if skill == "server.health":
        return render_server_health(result)
    if skill == "service.status":
        lines = [f"### `{result['project']}` 서비스 상태", ""]
        for item in result.get("services", []):
            container = item.get("container")
            if not container:
                lines.append(
                    f"- `{item['service']}`: **컨테이너 없음** "
                    f"(설정 포트: {', '.join(item.get('configured_ports') or []) or '없음'})"
                )
                continue
            health = (
                f", health={container['health']}"
                if container.get("health")
                else ""
            )
            ports = ", ".join(
                f"{port['host']}→{port['container']}"
                for port in container.get("ports", [])
            ) or "공개 포트 없음"
            lines.append(
                f"- `{item['service']}`: **{container['status']}**{health}, "
                f"재시작 {container.get('restart_count', 0)}회, 포트 {ports}"
            )
        return "\n".join(lines)
    if skill == "service.logs":
        logs = str(result.get("logs", "")).rstrip() or "(로그 없음)"
        return (
            f"### `{result['project']}/{result['service']}` 최근 로그 "
            f"({result['lines']}줄)\n\n```text\n{logs}\n```"
        )
    return f"`{skill}` CLI 조회를 완료했습니다."


def exact_entity_from_text(
    text: str,
    choices: list[str],
) -> str | None:
    matched = [
        choice
        for choice in choices
        if re.search(
            rf"(?<![A-Za-z0-9_.-]){re.escape(choice)}(?![A-Za-z0-9_.-])",
            text,
            re.IGNORECASE,
        )
    ]
    return matched[0] if len(matched) == 1 else None


def deterministic_read_request(
    message: str,
) -> tuple[str, dict[str, Any]] | None:
    lowered = message.lower()
    if "서버" in lowered and any(
        word in lowered for word in ("상태", "확인", "헬스", "health")
    ):
        return "server.health", {}
    wants_logs = any(word in lowered for word in ("로그", "log"))
    wants_status = any(
        word in lowered
        for word in ("상태", "실행중", "실행 중", "살아있", "컨테이너 확인")
    )
    if not wants_logs and not wants_status:
        return None
    catalog = execute_cli_skill("project.list", {}, dry_run=False)
    projects = catalog.get("projects") or []
    project = exact_entity_from_text(
        message,
        [item["name"] for item in projects],
    )
    if not project:
        return None
    project_item = next(item for item in projects if item["name"] == project)
    service = exact_entity_from_text(
        message,
        project_item.get("services") or [],
    )
    if wants_logs:
        if not service:
            return "service.logs", {"project": project}
        lines_match = re.search(r"(\d{1,3})\s*줄", message)
        return "service.logs", {
            "project": project,
            "service": service,
            "lines": int(lines_match.group(1)) if lines_match else 40,
        }
    return "service.status", {
        "project": project,
        **({"service": service} if service else {}),
    }


def framework_choices_text(candidates: list[str] | None = None) -> str:
    items = preset_catalog()
    if candidates:
        candidate_set = set(candidates)
        items = [item for item in items if item["id"] in candidate_set]
    return "\n".join(
        f"- **{item['label']}** (`{item['id']}`): {item['description']}"
        for item in items
    )


def collect_cli_observations(
    skill: str | None,
    arguments: dict[str, Any],
    missing: list[dict[str, Any]],
) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    if skill in {"project.create", "service.deploy", "service.redeploy"}:
        try:
            observations["projects"] = execute_cli_skill(
                "project.list",
                {},
                dry_run=False,
            )
        except SkillError as exc:
            observations["projects"] = {"error": str(exc)}
    missing_fields = {item.get("field") for item in missing}
    if skill == "service.deploy" and "framework" in missing_fields:
        try:
            observations["frameworks"] = execute_cli_skill(
                "framework.list",
                {},
                dry_run=False,
            )
        except SkillError as exc:
            observations["frameworks"] = {"error": str(exc)}
        repo_url = arguments.get("repo_url")
        if repo_url:
            try:
                observations["repository"] = execute_cli_skill(
                    "repository.inspect",
                    {"repo_url": repo_url},
                    dry_run=False,
                )
            except SkillError as exc:
                observations["repository"] = {"error": str(exc)}
    return observations


def framework_context_help(
    message: str,
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not context or context.get("skill") != "service.deploy":
        return None
    missing = {item.get("field") for item in context.get("missing", [])}
    if "framework" not in missing:
        return None

    normalized = re.sub(r"\s+", "", message.lower())
    arguments = dict(context.get("arguments") or {})
    asks_catalog = (
        "프리셋" in normalized
        and any(word in normalized for word in ("뭐", "무엇", "목록", "어떤", "있"))
    )
    javascript = any(
        word in normalized
        for word in ("javascript", "자바스크립트", "node", "nodejs", "js로")
    )
    if not asks_catalog and not javascript:
        return None

    if javascript:
        candidates = ["static", "vite", "react", "nextjs", "express"]
        analysis = None
        repo_url = arguments.get("repo_url")
        if repo_url:
            try:
                analysis = execute_cli_skill(
                    "repository.inspect",
                    {"repo_url": str(repo_url)},
                    dry_run=False,
                )
                if analysis["candidates"]:
                    candidates = [
                        item
                        for item in analysis["candidates"]
                        if item in {"static", "vite", "react", "nextjs", "express"}
                    ] or candidates
            except SkillError:
                analysis = None
        message_text = (
            "JavaScript만으로는 실행 방식을 하나로 결정할 수 없습니다. "
            "아래 프리셋 중 실제 프로젝트 구조와 맞는 것을 선택해주세요.\n\n"
            + framework_choices_text(candidates)
        )
        if analysis and analysis.get("evidence"):
            message_text += (
                "\n\n저장소 분석 근거: "
                + ", ".join(analysis["evidence"])
            )
        else:
            message_text += (
                "\n\n판별 기준: `vite.config.*` 또는 Vite 의존성은 Vite, "
                "`react-scripts`는 Create React App, `next`는 Next.js, "
                "Express/NestJS 서버는 Express 프리셋입니다."
            )
    else:
        message_text = (
            "사용 가능한 프레임워크 프리셋입니다. 하나를 이름으로 선택해주세요.\n\n"
            + framework_choices_text()
        )

    confirmed = confirmed_information(arguments)
    if confirmed:
        message_text += "\n\n" + confirmed
    return {
        "mode": "local",
        "kind": "clarification",
        "message": message_text,
        "skill": "service.deploy",
        "arguments": arguments,
        "missing": context.get("missing", []),
        "context": context,
        "requires_approval": False,
    }


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


@app.get("/help")
def help_guide():
    return {"message": HELP_MESSAGE}


@app.get("/commands")
def commands():
    return command_contracts()


@app.get("/schema/{skill}")
def schema(skill: str):
    try:
        return command_contract(skill)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/catalog")
def catalog():
    return command_catalog()


@app.post("/chat")
def chat(request: ChatRequest):
    session_context, session_history = load_session(
        request.session_id,
        request.context,
    )
    request.context = session_context

    def respond(payload: dict[str, Any]) -> dict[str, Any]:
        return remember_response(request.session_id, request.message, payload)

    request.context, proposed_response = handle_proposed_input(
        request.message,
        request.context,
    )
    if proposed_response:
        return respond(proposed_response)

    normalized = request.message.strip().lower()
    if normalized in HELP_COMMANDS and not os.getenv("LLM_API_KEY"):
        return respond({
            "mode": "local",
            "kind": "help",
            "message": HELP_MESSAGE,
            "requires_approval": False,
        })
    if (
        any(phrase in normalized for phrase in DEPLOYMENT_GUIDE_PHRASES)
        and not os.getenv("LLM_API_KEY")
    ):
        return respond({
            "mode": "local",
            "kind": "guide",
            "message": DEPLOYMENT_GUIDE,
            "requires_approval": False,
        })
    ambiguous = ambiguity_for(request.message, request.context)
    if ambiguous:
        return respond(ambiguous)
    no_project = no_project_transition(request.message, request.context)
    if no_project:
        return respond(no_project)
    framework_help = framework_context_help(request.message, request.context)
    if framework_help and not os.getenv("LLM_API_KEY"):
        return respond(framework_help)
    documents = skill_documents()
    try:
        deterministic_read = deterministic_read_request(request.message)
        if deterministic_read:
            skill, arguments = deterministic_read
            if skill == "service.logs" and not arguments.get("service"):
                services = execute_cli_skill(
                    "project.list",
                    {},
                    dry_run=False,
                )
                project = next(
                    item
                    for item in services["projects"]
                    if item["name"] == arguments["project"]
                )
                return respond({
                    "mode": "local",
                    "kind": "clarification",
                    "message": (
                        f"`{arguments['project']}`의 어느 서비스 로그를 볼까요?\n\n"
                        + "\n".join(
                            f"- `{name}`" for name in project.get("services", [])
                        )
                    ),
                    "skill": skill,
                    "arguments": arguments,
                    "missing": [{"field": "service", "label": "로그를 볼 서비스"}],
                    "context": {
                        "skill": skill,
                        "arguments": arguments,
                        "missing": [{"field": "service", "label": "로그를 볼 서비스"}],
                    },
                    "requires_approval": False,
                })
            result = execute_cli_skill(skill, arguments, dry_run=False)
            return respond({
                "mode": "cli",
                "message": render_read_only_result(skill, result),
                "skill": skill,
                "result": result,
                "requires_approval": False,
            })
        preferred_skill = preferred_skill_for(request.message, request.context)
        cli_proposal = cli_proposal_for_input(
            request.message,
            preferred_skill,
            request.context,
        )
        if cli_proposal:
            return respond(cli_proposal)
        llm_context = dict(request.context or {})
        if preferred_skill in {
            "project.create",
            "service.deploy",
            "service.redeploy",
        }:
            current_arguments = strict_arguments(
                request.message,
                preferred_skill,
                request.context,
                {},
            )
            current_missing = list(llm_context.get("missing") or [])
            try:
                current_preview = execute_cli_skill(
                    preferred_skill,
                    current_arguments,
                    dry_run=True,
                )
                current_missing = current_preview.get("needs_input", [])
            except SkillError:
                current_preview = {}
            if current_preview and not current_missing:
                return respond({
                    "mode": "cli",
                    "message": (
                        "CLI에서 모든 입력값과 현재 서버 상태를 검증했습니다. "
                        "아래 실행 계획을 확인하고 승인해주세요."
                    ),
                    "skill": preferred_skill,
                    "arguments": current_arguments,
                    "preview": current_preview,
                    "requires_approval": True,
                })
            llm_context.update(
                {
                    "skill": preferred_skill,
                    "arguments": current_arguments,
                    "missing": current_missing,
                    "cli_observations": collect_cli_observations(
                        preferred_skill,
                        current_arguments,
                        current_missing,
                    ),
                }
            )
            repository_observation = (
                llm_context.get("cli_observations", {}).get("repository", {})
            )
            candidates = repository_observation.get("candidates") or []
            explicit_framework = explicit_arguments(
                request.message,
                preferred_skill,
            ).get("framework")
            if (
                preferred_skill == "service.deploy"
                and "framework" in {
                    item.get("field") for item in current_missing
                }
                and not explicit_framework
                and len(candidates) == 1
            ):
                candidate = candidates[0]
                resolution = {
                    "entity": "framework",
                    "query": "저장소 구조",
                    "status": "single",
                    "match": candidate,
                    "candidates": [
                        {
                            "value": candidate,
                            "score": 1.0,
                            "reason": "저장소 파일·의존성 근거가 하나의 프리셋과 일치함",
                        }
                    ],
                    "source": "repository.inspect CLI",
                }
                return respond(
                    proposal_response(
                        llm_context,
                        resolution,
                        field="framework",
                        evidence=repository_observation.get("evidence", []),
                    )
                )
        plan = call_llm(
            request.message,
            documents,
            llm_context or None,
            preferred_skill,
            session_history,
        ) or fallback_plan(request.message)
        if plan.get("kind") == "answer":
            if preferred_skill in {
                "project.create",
                "service.deploy",
                "service.redeploy",
            }:
                verified_arguments = strict_arguments(
                    request.message,
                    preferred_skill,
                    request.context,
                    {},
                )
                try:
                    current_preview = execute_cli_skill(
                        preferred_skill,
                        verified_arguments,
                        dry_run=True,
                    )
                except SkillError:
                    current_preview = {}
                missing = current_preview.get("needs_input", [])
                context = {
                    "original_request": (
                        request.context.get("original_request")
                        if request.context
                        else request.message
                    ),
                    "skill": preferred_skill,
                    "arguments": verified_arguments,
                    "missing": missing,
                }
                message = plan["message"]
                confirmed = confirmed_information(verified_arguments)
                if confirmed and "지금까지 확인된 정보" not in message:
                    message += "\n\n" + confirmed
                optional_message = optional_settings_message(
                    current_preview.get("optional")
                    if isinstance(current_preview, dict)
                    else None
                )
                if optional_message and "선택 설정" not in message:
                    message += "\n\n" + optional_message
                if current_preview and not missing:
                    return respond({
                        "mode": "llm",
                        "message": (
                            "CLI에서 모든 입력값과 현재 서버 상태를 검증했습니다. "
                            "아래 실행 계획을 확인하고 승인해주세요."
                        ),
                        "model": plan.get("model"),
                        "skill": preferred_skill,
                        "arguments": verified_arguments,
                        "preview": current_preview,
                        "requires_approval": True,
                    })
                return respond({
                    "mode": "llm",
                    "kind": "clarification",
                    "message": message,
                    "model": plan.get("model"),
                    "skill": preferred_skill,
                    "arguments": verified_arguments,
                    "missing": missing,
                    "context": context,
                    "requires_approval": False,
                })
            return respond({
                "mode": "llm",
                "kind": "clarification" if request.context else "help",
                "message": plan["message"],
                "model": plan.get("model"),
                "arguments": (
                    request.context.get("arguments", {})
                    if request.context
                    else {}
                ),
                "missing": (
                    request.context.get("missing", [])
                    if request.context
                    else []
                ),
                "context": request.context,
                "requires_approval": False,
            })
        skill = plan["skill"]
        arguments = strict_arguments(
            request.message,
            skill,
            request.context,
            plan.get("arguments", {}),
        )
        project_problem = project_problem_response(
            skill,
            arguments,
            request,
        )
        if project_problem:
            return respond(project_problem)
        if skill in READ_ONLY_SKILLS:
            result = execute_cli_skill(
                skill,
                arguments,
                dry_run=False,
            )
            return respond({
                "mode": "llm" if os.getenv("LLM_API_KEY") else "fallback",
                "message": render_read_only_result(skill, result),
                "skill": skill,
                "model": plan.get("model"),
                "result": result,
                "requires_approval": False,
            })
        try:
            preview = execute_cli_skill(
                skill,
                arguments,
                dry_run=True,
            )
        except SkillError as exc:
            return respond({
                "mode": "local",
                "kind": "clarification",
                "message": (
                    f"요청을 실행 계획으로 만들 수 없습니다: {exc}\n\n"
                    "현재 입력값을 확인하고 잘못된 항목만 다시 알려주세요."
                ),
                "skill": skill,
                "arguments": arguments,
                "missing": [],
                "context": {
                    "original_request": (
                        request.context.get("original_request")
                        if request.context
                        else request.message
                    ),
                    "skill": skill,
                    "arguments": arguments,
                    "missing": [],
                },
                "requires_approval": False,
            })
        if preview.get("needs_input"):
            details = preview.get("project_guidance")
            message = preview["message"]
            if details:
                message += f"\n\n{details}"
            optional = preview.get("optional")
            if optional:
                message += "\n\n" + optional_settings_message(optional)
            confirmed = confirmed_information(arguments)
            if confirmed:
                message = confirmed + "\n\n" + message
            return respond({
                "mode": "llm" if os.getenv("LLM_API_KEY") else "fallback",
                "kind": "clarification",
                "message": message,
                "skill": skill,
                "model": plan.get("model"),
                "arguments": arguments,
                "missing": preview["needs_input"],
                "context": {
                    "original_request": (
                        request.context.get("original_request")
                        if request.context
                        else request.message
                    ),
                    "skill": skill,
                    "arguments": arguments,
                    "missing": preview["needs_input"],
                },
                "requires_approval": False,
            })
        return respond({
            "mode": "llm" if os.getenv("LLM_API_KEY") else "fallback",
            "message": (
                "CLI에서 모든 입력값과 현재 서버 상태를 검증했습니다. "
                "아래 실행 계획을 확인하고 승인해주세요."
            ),
            "skill": skill,
            "model": plan.get("model"),
            "arguments": arguments,
            "preview": preview,
            "resume": (
                request.context.get("resume")
                if request.context
                else None
            ),
            "requires_approval": True,
        })
    except (SkillError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planner failed: {exc}") from exc


@app.post("/execute")
def execute(request: ExecuteRequest, http_request: Request):
    if request.skill not in READ_ONLY_SKILLS and not request.approved:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/preview")
def preview(request: PreviewRequest, http_request: Request):
    if request.skill in READ_ONLY_SKILLS:
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
