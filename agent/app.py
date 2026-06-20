from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

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
- **서버 상태**: `서버 상태를 확인해줘`
- **프로젝트 목록**: `프로젝트와 서비스 목록 보여줘`
- **서비스 상태**: `demoa의 demo-a 상태를 확인해줘`
- **최근 로그**: `demoa의 demo-a 로그 40줄 보여줘`
- **서비스 제어**: `demoa의 demo-a를 시작해줘`, `중지해줘`, `재시작해줘`
- **새 서비스 배포**: `demoa 프로젝트에 https://github.com/crccheck/docker-hello-world 저장소를 hello 서비스로 배포해줘. 컨테이너 포트는 8000`
- **포트 추천**: `사용 가능한 포트를 추천해줘`
- **포트 변경**: `demoa의 demo-a 호스트 포트를 9002로 바꿔줘`
- **QA 점검**: `전체 QA 점검해줘`

서비스 시작·중지·재시작과 포트 변경은 실행 전에 계획을 보여주고 승인을 요청합니다.
`도움말`을 입력하면 이 안내를 다시 볼 수 있습니다."""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ExecuteRequest(BaseModel):
    skill: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


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


@app.get("/help")
def help_guide():
    return {"message": HELP_MESSAGE}


@app.post("/chat")
def chat(request: ChatRequest):
    if request.message.strip().lower() in HELP_COMMANDS:
        return {
            "mode": "local",
            "kind": "help",
            "message": HELP_MESSAGE,
            "requires_approval": False,
        }
    documents = skill_documents()
    try:
        plan = call_llm(request.message, documents) or fallback_plan(request.message)
        skill = plan["skill"]
        arguments = plan.get("arguments", {})
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
        preview = execute_skill(skill, arguments, dry_run=True)
        return {
            "mode": "llm" if os.getenv("LLM_API_KEY") else "fallback",
            "message": plan.get("explanation", "Approval is required."),
            "skill": skill,
            "model": plan.get("model"),
            "arguments": arguments,
            "preview": preview,
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
