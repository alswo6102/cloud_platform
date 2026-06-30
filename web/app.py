from __future__ import annotations

import os
from typing import Any, Literal

import requests
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


SKILL_AGENT_URL = os.getenv("SKILL_AGENT_URL", "http://localhost:8080").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("WEB_REQUEST_TIMEOUT", "120"))

Role = Literal["visitor", "user", "admin"]

app = FastAPI(title="Cloud Platform Web API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str | None = None
    context: dict[str, Any] | None = None
    project: str | None = None


class ExecuteRequest(BaseModel):
    skill: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    session_id: str | None = None
    resume: dict[str, Any] | None = None
    project: str | None = None


def current_role(x_user_role: str | None) -> Role:
    role = (x_user_role or "visitor").strip().lower()
    if role not in {"visitor", "user", "admin"}:
        return "visitor"
    return role  # type: ignore[return-value]


def current_user(x_user_id: str | None) -> str:
    return (x_user_id or "local-user").strip() or "local-user"


def agent_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = requests.request(
            method,
            f"{SKILL_AGENT_URL}{path}",
            json=json_body,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Skill agent is unavailable: {exc}",
        ) from exc
    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        raise HTTPException(status_code=response.status_code, detail=detail)
    return data if isinstance(data, dict) else {"result": data}


def require_login(role: Role) -> None:
    if role == "visitor":
        raise HTTPException(status_code=401, detail="Login is required.")


def require_admin(role: Role) -> None:
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin role is required.")


def project_names() -> set[str]:
    data = agent_request("POST", "/execute", json_body={
        "skill": "project.list",
        "arguments": {},
        "approved": True,
    })
    projects = data.get("result", {}).get("projects", [])
    return {str(item.get("name")) for item in projects if item.get("name")}


def ensure_project_access(role: Role, user_id: str, project: str) -> None:
    # Placeholder policy until real login/membership is added.
    # - admin can access every project.
    # - user can access existing projects in development mode.
    # Later this becomes: memberships(user_id, project).role in [...]
    if role == "admin":
        return
    require_login(role)
    if project not in project_names():
        raise HTTPException(status_code=404, detail=f"Project not found: {project}")


@app.get("/api/health")
def health() -> dict[str, Any]:
    agent = agent_request("GET", "/health")
    return {"status": "ok", "skill_agent": agent}


@app.get("/api/me")
def me(
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    role = current_role(x_user_role)
    user_id = current_user(x_user_id)
    return {
        "id": user_id if role != "visitor" else None,
        "role": role,
        "auth_mode": "development-header",
    }


@app.get("/api/projects")
def list_projects(
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    role = current_role(x_user_role)
    user_id = current_user(x_user_id)
    require_login(role)
    data = agent_request("POST", "/execute", json_body={
        "skill": "project.list",
        "arguments": {},
        "approved": True,
    })
    projects = data.get("result", {}).get("projects", [])
    # Development policy: users see every existing project until membership is implemented.
    return {
        "user": {"id": user_id, "role": role},
        "projects": projects,
        "membership_mode": "stub-all-projects-visible",
    }


@app.get("/api/frameworks")
def frameworks() -> dict[str, Any]:
    return agent_request("GET", "/frameworks")


@app.get("/api/commands")
def commands() -> dict[str, Any]:
    return agent_request("GET", "/commands")


@app.post("/api/projects")
def create_project(
    payload: dict[str, Any],
    x_user_role: str | None = Header(default=None),
) -> dict[str, Any]:
    role = current_role(x_user_role)
    require_login(role)
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required.")
    preview = agent_request("POST", "/preview", json_body={
        "skill": "project.create",
        "arguments": {"project": name},
    })
    if not payload.get("approved"):
        return {
            "status": "preview",
            "requires_approval": True,
            "preview": preview.get("preview", preview),
        }
    return agent_request("POST", "/execute", json_body={
        "skill": "project.create",
        "arguments": {"project": name},
        "approved": True,
    })


@app.post("/api/projects/{project}/chat")
def project_chat(
    project: str,
    payload: ChatRequest,
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    role = current_role(x_user_role)
    user_id = current_user(x_user_id)
    ensure_project_access(role, user_id, project)
    context = dict(payload.context or {})
    context.setdefault("arguments", {})
    context["arguments"]["project"] = project
    context["project_scope"] = project
    scoped_message = payload.message
    if project not in scoped_message:
        scoped_message = f"{project} 프로젝트에서: {scoped_message}"
    return agent_request("POST", "/chat", json_body={
        "message": scoped_message,
        "session_id": payload.session_id,
        "context": context,
    })


@app.post("/api/admin/chat")
def admin_chat(
    payload: ChatRequest,
    x_user_role: str | None = Header(default=None),
) -> dict[str, Any]:
    role = current_role(x_user_role)
    require_admin(role)
    return agent_request("POST", "/chat", json_body=payload.model_dump())


@app.post("/api/projects/{project}/execute")
def project_execute(
    project: str,
    payload: ExecuteRequest,
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    role = current_role(x_user_role)
    user_id = current_user(x_user_id)
    ensure_project_access(role, user_id, project)
    arguments = dict(payload.arguments)
    arguments["project"] = project
    return agent_request("POST", "/execute", json_body={
        "skill": payload.skill,
        "arguments": arguments,
        "approved": payload.approved,
        "session_id": payload.session_id,
        "resume": payload.resume,
    })
