from __future__ import annotations

import os
import json
import threading
import time
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


SKILL_AGENT_URL = os.getenv("SKILL_AGENT_URL", "http://localhost:8080").rstrip("/")
PROJECT_AGENT_URL_TEMPLATE = os.getenv(
    "PROJECT_AGENT_URL_TEMPLATE",
    "http://project-agent-{project}:8080",
)
AUTO_ENSURE_PROJECT_AGENT = os.getenv("AUTO_ENSURE_PROJECT_AGENT", "1").lower() not in {
    "0",
    "false",
    "no",
}
AUTH_STORE = Path(os.getenv("AUTH_STORE", "/var/lib/cloud-platform/auth.json"))
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", "/var/www/cloud-platform-console"))
REQUEST_TIMEOUT = float(os.getenv("WEB_REQUEST_TIMEOUT", "120"))
PROJECT_AGENT_ENSURE_TTL = float(os.getenv("PROJECT_AGENT_ENSURE_TTL", "300"))
AUTH_LOCK = threading.Lock()
PROJECT_AGENT_ENSURE_LOCK = threading.Lock()
PROJECT_AGENT_ENSURED_AT: dict[str, float] = {}

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


class LoginRequest(BaseModel):
    user_id: str
    password: str = ""


def default_auth_store() -> dict[str, Any]:
    return {
        "users": {
            "local-user": {"password": "", "role": "user", "name": "Local User"},
            "admin": {"password": "admin", "role": "admin", "name": "Admin"},
        },
        "memberships": {},
    }


def load_auth_store() -> dict[str, Any]:
    with AUTH_LOCK:
        try:
            data = json.loads(AUTH_STORE.read_text())
            if isinstance(data, dict):
                data.setdefault("users", {})
                data.setdefault("memberships", {})
                return data
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        data = default_auth_store()
        save_auth_store_unlocked(data)
        return data


def save_auth_store(data: dict[str, Any]) -> None:
    with AUTH_LOCK:
        save_auth_store_unlocked(data)


def save_auth_store_unlocked(data: dict[str, Any]) -> None:
    AUTH_STORE.parent.mkdir(parents=True, exist_ok=True)
    temporary = AUTH_STORE.with_name(
        f"{AUTH_STORE.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    temporary.replace(AUTH_STORE)


def current_role(x_user_role: str | None) -> Role:
    role = (x_user_role or "visitor").strip().lower()
    if role not in {"visitor", "user", "admin"}:
        return "visitor"
    return role  # type: ignore[return-value]


def current_user(x_user_id: str | None) -> str:
    return (x_user_id or "local-user").strip() or "local-user"


def authenticated_user(
    x_user_role: str | None,
    x_user_id: str | None,
) -> tuple[str, Role]:
    role = current_role(x_user_role)
    if role == "visitor":
        return "", role
    user_id = current_user(x_user_id)
    if role == "admin":
        store = load_auth_store()
        store.setdefault("users", {}).setdefault(user_id, {
            "password": "",
            "role": "admin",
            "name": user_id,
        })
        store["users"][user_id]["role"] = "admin"
        save_auth_store(store)
        return user_id, "admin"
    store = load_auth_store()
    user = store.get("users", {}).get(user_id)
    if not user:
        store.setdefault("users", {})[user_id] = {
            "password": "",
            "role": role,
            "name": user_id,
        }
        save_auth_store(store)
        return user_id, role
    stored_role = str(user.get("role", role)).lower()
    if stored_role == "admin":
        return user_id, "admin"
    return user_id, "user"


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


def project_agent_url(project: str) -> str:
    return PROJECT_AGENT_URL_TEMPLATE.format(project=project)


def wait_project_agent_ready(project: str, *, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    url = f"{project_agent_url(project).rstrip('/')}/health"
    while time.monotonic() < deadline:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code < 500:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return False


def project_agent_request(
    project: str,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{project_agent_url(project).rstrip('/')}{path}"
    if AUTO_ENSURE_PROJECT_AGENT:
        ensure_project_agent(project)
    try:
        response = requests.request(
            method,
            url,
            json=json_body,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as first_exc:
        ensure_project_agent(project, force=True)
        wait_project_agent_ready(project)
        try:
            response = requests.request(
                method,
                url,
                json=json_body,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Project agent is unavailable for {project}: {exc}",
            ) from first_exc
    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        raise HTTPException(status_code=response.status_code, detail=detail)
    return data if isinstance(data, dict) else {"result": data}


def ensure_project_agent(project: str, *, force: bool = False) -> None:
    now = time.monotonic()
    if not force and wait_project_agent_ready(project, timeout=2.0):
        with PROJECT_AGENT_ENSURE_LOCK:
            PROJECT_AGENT_ENSURED_AT[project] = time.monotonic()
        return
    if AUTO_ENSURE_PROJECT_AGENT and not force:
        with PROJECT_AGENT_ENSURE_LOCK:
            last = PROJECT_AGENT_ENSURED_AT.get(project, 0)
            if now - last < PROJECT_AGENT_ENSURE_TTL:
                return
    agent_request("POST", "/execute", json_body={
        "skill": "project.ensure_agent",
        "arguments": {"project": project},
        "approved": True,
    })
    wait_project_agent_ready(project)
    with PROJECT_AGENT_ENSURE_LOCK:
        PROJECT_AGENT_ENSURED_AT[project] = time.monotonic()


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
    if role == "admin":
        return
    require_login(role)
    if project not in project_names():
        raise HTTPException(status_code=404, detail=f"Project not found: {project}")
    store = load_auth_store()
    members = store.setdefault("memberships", {}).setdefault(project, {})
    if not members and user_id == "local-user":
        members[user_id] = "owner"
        save_auth_store(store)
        return
    if user_id not in members:
        raise HTTPException(status_code=403, detail=f"No project membership: {project}")


def visible_projects(role: Role, user_id: str, projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if role == "admin":
        return projects
    store = load_auth_store()
    memberships = store.setdefault("memberships", {})
    if not memberships and user_id == "local-user":
        for project in projects:
            memberships.setdefault(str(project["name"]), {})[user_id] = "owner"
        save_auth_store(store)
    return [
        project
        for project in projects
        if user_id in memberships.get(str(project.get("name")), {})
    ]


def add_project_membership(project: str, user_id: str, role: str = "owner") -> None:
    store = load_auth_store()
    store.setdefault("memberships", {}).setdefault(project, {})[user_id] = role
    save_auth_store(store)


@app.get("/api/health")
def health() -> dict[str, Any]:
    agent = agent_request("GET", "/health")
    return {"status": "ok", "skill_agent": agent}


@app.post("/api/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    store = load_auth_store()
    user = store.get("users", {}).get(payload.user_id)
    if not user or str(user.get("password", "")) != payload.password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "id": payload.user_id,
        "role": user.get("role", "user"),
        "name": user.get("name", payload.user_id),
        "auth_mode": "json-table",
    }


@app.get("/api/me")
def me(
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(x_user_role, x_user_id)
    return {
        "id": user_id if role != "visitor" else None,
        "role": role,
        "auth_mode": "json-table-development-header",
    }


@app.get("/api/projects")
def list_projects(
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(x_user_role, x_user_id)
    require_login(role)
    data = agent_request("POST", "/execute", json_body={
        "skill": "project.list",
        "arguments": {},
        "approved": True,
    })
    projects = visible_projects(role, user_id, data.get("result", {}).get("projects", []))
    return {
        "user": {"id": user_id, "role": role},
        "projects": projects,
        "membership_mode": "json-table",
    }


@app.get("/api/catalog")
def service_catalog() -> dict[str, Any]:
    data = agent_request("POST", "/execute", json_body={
        "skill": "project.list",
        "arguments": {},
        "approved": True,
    })
    projects = data.get("result", {}).get("projects", [])
    services = []
    for project in projects:
        project_name = str(project.get("name") or "")
        for service in project.get("services", []) or []:
            services.append({
                "project": project_name,
                "service": str(service),
            })
    return {
        "projects": projects,
        "services": services,
        "visibility": "names-only",
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
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(x_user_role, x_user_id)
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
    result = agent_request("POST", "/execute", json_body={
        "skill": "project.create",
        "arguments": {"project": name},
        "approved": True,
    })
    add_project_membership(name, user_id or "local-user", "owner")
    return result


@app.post("/api/projects/{project}/chat")
def project_chat(
    project: str,
    payload: ChatRequest,
    request: Request,
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(x_user_role, x_user_id)
    ensure_project_access(role, user_id, project)
    context = dict(payload.context or {})
    context.setdefault("arguments", {})
    context["arguments"]["project"] = project
    context["project_scope"] = project
    context.setdefault(
        "public_base_url",
        os.getenv("PUBLIC_BASE_URL", str(request.base_url).rstrip("/")),
    )
    scoped_message = payload.message
    if project not in scoped_message:
        scoped_message = f"{project} 프로젝트에서: {scoped_message}"
    return project_agent_request(project, "POST", "/chat", json_body={
        "message": scoped_message,
        "session_id": payload.session_id,
        "context": context,
    })


@app.post("/api/admin/chat")
def admin_chat(
    payload: ChatRequest,
    x_user_role: str | None = Header(default=None),
) -> dict[str, Any]:
    _, role = authenticated_user(x_user_role, None)
    require_admin(role)
    return agent_request("POST", "/chat", json_body=payload.model_dump())


@app.post("/api/projects/{project}/execute")
def project_execute(
    project: str,
    payload: ExecuteRequest,
    x_user_role: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(x_user_role, x_user_id)
    ensure_project_access(role, user_id, project)
    arguments = dict(payload.arguments)
    arguments["project"] = project
    return project_agent_request(project, "POST", "/execute", json_body={
        "skill": payload.skill,
        "arguments": arguments,
        "approved": payload.approved,
        "session_id": payload.session_id,
        "resume": payload.resume,
    })


@app.get("/{full_path:path}", include_in_schema=False)
def serve_frontend(full_path: str) -> FileResponse:
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found.")
    if not FRONTEND_DIST.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "Frontend dist is not deployed yet. Build locally with "
                "`npm run build`, then rsync frontend/dist/ to the server dist directory."
            ),
        )
    requested = (FRONTEND_DIST / full_path).resolve()
    dist_root = FRONTEND_DIST.resolve()
    if requested.is_file() and dist_root in requested.parents:
        return FileResponse(requested)
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail="Frontend index.html not found.")
