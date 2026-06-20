from __future__ import annotations

import os
import re
from typing import Any
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from deployment_presets import preset_catalog

from runtime import (
    READ_ONLY_SKILLS,
    SkillError,
    call_llm,
    execute_skill,
    fallback_plan,
    llm_status,
    skill_documents,
)

app = FastAPI(title="Cloud Platform Skill Agent", version="0.1.0")
PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", "/srv/projects"))
GITHUB_URL_RE = re.compile(
    r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?"
)
FRAMEWORK_ALIASES = {
    "기존 dockerfile": "existing",
    "기존 도커파일": "existing",
    "existing": "existing",
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
    if "프로젝트" in text and any(word in text for word in ("신규", "새 ", "새로", "추가", "생성", "만들", "복구")):
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
        ],
    }
    for pattern in patterns[label]:
        match = re.search(pattern, message, re.IGNORECASE)
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
        if "웹 서비스" in lowered:
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
    if skill not in {"project.create", "service.deploy", "service.redeploy"}:
        return planner_arguments
    verified = {}
    if context and context.get("skill") == skill:
        verified.update(context.get("arguments") or {})
    verified.update(explicit_arguments(message, skill))
    missing_fields = {
        item.get("field")
        for item in (context or {}).get("missing", [])
    }
    bare = message.strip()
    if len(missing_fields) == 1:
        field = next(iter(missing_fields))
        if field in {"project", "service"} and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}",
            bare,
        ):
            verified[field] = bare
        elif field == "repo_url" and GITHUB_URL_RE.fullmatch(bare):
            verified[field] = bare
        elif field == "framework":
            framework = FRAMEWORK_ALIASES.get(bare.lower())
            if framework:
                verified[field] = framework
    return verified


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


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context: dict[str, Any] | None = None


class ExecuteRequest(BaseModel):
    skill: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


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


@app.post("/chat")
def chat(request: ChatRequest):
    normalized = request.message.strip().lower()
    if normalized in HELP_COMMANDS:
        return {
            "mode": "local",
            "kind": "help",
            "message": HELP_MESSAGE,
            "requires_approval": False,
        }
    if any(phrase in normalized for phrase in DEPLOYMENT_GUIDE_PHRASES):
        return {
            "mode": "local",
            "kind": "guide",
            "message": DEPLOYMENT_GUIDE,
            "requires_approval": False,
        }
    ambiguous = ambiguity_for(request.message, request.context)
    if ambiguous:
        return ambiguous
    no_project = no_project_transition(request.message, request.context)
    if no_project:
        return no_project
    documents = skill_documents()
    try:
        preferred_skill = preferred_skill_for(request.message, request.context)
        plan = call_llm(
            request.message,
            documents,
            request.context,
            preferred_skill,
        ) or fallback_plan(request.message)
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
            return project_problem
        if skill in READ_ONLY_SKILLS:
            result = execute_skill(skill, arguments, dry_run=False)
            return {
                "mode": "llm" if os.getenv("LLM_API_KEY") else "fallback",
                "message": plan.get("explanation", "Completed."),
                "skill": skill,
                "model": plan.get("model"),
                "result": result,
                "requires_approval": False,
            }
        try:
            preview = execute_skill(skill, arguments, dry_run=True)
        except SkillError as exc:
            return {
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
            }
        if preview.get("needs_input"):
            details = preview.get("project_guidance")
            message = preview["message"]
            if details:
                message += f"\n\n{details}"
            optional = preview.get("optional")
            if optional:
                message += "\n\n선택 정보: " + ", ".join(optional)
            return {
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
            }
        return {
            "mode": "llm" if os.getenv("LLM_API_KEY") else "fallback",
            "message": plan.get("explanation", "Approval is required."),
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
        }
    except (SkillError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Planner failed: {exc}") from exc


@app.post("/execute")
def execute(request: ExecuteRequest):
    if request.skill not in READ_ONLY_SKILLS and not request.approved:
        raise HTTPException(status_code=409, detail="Explicit approval is required.")
    try:
        return {
            "skill": request.skill,
            "result": execute_skill(request.skill, request.arguments, dry_run=False),
        }
    except (SkillError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/preview")
def preview(request: PreviewRequest):
    if request.skill in READ_ONLY_SKILLS:
        raise HTTPException(status_code=400, detail="Preview is only for mutation skills.")
    try:
        return {
            "skill": request.skill,
            "preview": execute_skill(request.skill, request.arguments, dry_run=True),
        }
    except (SkillError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
