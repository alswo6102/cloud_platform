from __future__ import annotations

import os
import json
import hashlib
import hmac
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import FastAPI, Header, HTTPException, Request, Response
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
# A deploy clones, builds an image, and waits for the container to settle. The
# runtime allows 900s for the build alone, so the read timeout has to outlast it
# or the console gives up on work the server is still doing.
MUTATION_REQUEST_TIMEOUT = float(os.getenv("WEB_MUTATION_TIMEOUT", "960"))
MUTATION_SKILLS = {
    "project.create",
    "project.ensure_agent",
    "service.deploy",
    "service.redeploy",
    "service.control",
    "service.delete",
    "port.manage",
}
PROJECT_AGENT_ENSURE_TTL = float(os.getenv("PROJECT_AGENT_ENSURE_TTL", "300"))
SESSION_TOKEN_TTL = float(os.getenv("SESSION_TOKEN_TTL", str(60 * 60 * 12)))
PROJECT_SUMMARY_CACHE_TTL = float(os.getenv("WEB_PROJECT_SUMMARY_CACHE_TTL", "10"))
CATALOG_CACHE_TTL = float(os.getenv("WEB_CATALOG_CACHE_TTL", "10"))
SYSTEM_SUMMARY_CACHE_TTL = float(os.getenv("WEB_SYSTEM_SUMMARY_CACHE_TTL", "5"))
SERVICE_STATUS_CACHE_TTL = float(os.getenv("WEB_SERVICE_STATUS_CACHE_TTL", "3"))
AUTH_LOCK = threading.Lock()
PROJECT_AGENT_ENSURE_LOCK = threading.Lock()
PROJECT_AGENT_ENSURED_AT: dict[str, float] = {}
READ_CACHE_LOCK = threading.Lock()
READ_CACHE: dict[str, dict[str, Any]] = {}
READ_INFLIGHT: dict[str, threading.Event] = {}

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


def request_bypasses_cache(request: Request) -> bool:
    cache_control = request.headers.get("cache-control", "").lower()
    pragma = request.headers.get("pragma", "").lower()
    refresh = request.query_params.get("refresh", "").lower()
    return (
        "no-cache" in cache_control
        or "max-age=0" in cache_control
        or "no-cache" in pragma
        or refresh in {"1", "true", "yes"}
    )


def cached_read(
    key: str,
    ttl: float,
    producer: Any,
    *,
    bypass: bool = False,
) -> tuple[dict[str, Any], str, float, float]:
    if ttl <= 0:
        return producer(), "MISS", 0, time.time()

    now = time.monotonic()
    stale_entry: dict[str, Any] | None = None
    with READ_CACHE_LOCK:
        entry = READ_CACHE.get(key)
        if entry:
            if entry["expires_at"] > now and not bypass:
                return (
                    entry["value"],
                    "HIT",
                    max(0.0, entry["expires_at"] - now),
                    entry["generated_at"],
                )
            stale_entry = entry
        if bypass:
            event = threading.Event()
            owner = True
        else:
            event = READ_INFLIGHT.get(key)
            owner = event is None
            if owner:
                event = threading.Event()
                READ_INFLIGHT[key] = event

    if not owner:
        assert event is not None
        event.wait(timeout=REQUEST_TIMEOUT)
        with READ_CACHE_LOCK:
            entry = READ_CACHE.get(key)
            if entry:
                current = time.monotonic()
                state = "HIT" if entry["expires_at"] > current else "STALE"
                return (
                    entry["value"],
                    state,
                    max(0.0, entry["expires_at"] - current),
                    entry["generated_at"],
                )
        if stale_entry:
            return stale_entry["value"], "STALE", 0, stale_entry["generated_at"]

    try:
        value = producer()
    except Exception:
        if owner and not bypass:
            with READ_CACHE_LOCK:
                READ_INFLIGHT.pop(key, None)
                assert event is not None
                event.set()
        if stale_entry and not bypass:
            return stale_entry["value"], "STALE", 0, stale_entry["generated_at"]
        raise
    generated_at = time.time()
    expires_at = time.monotonic() + ttl
    with READ_CACHE_LOCK:
        READ_CACHE[key] = {
            "value": value,
            "generated_at": generated_at,
            "expires_at": expires_at,
        }
        if owner and not bypass:
            READ_INFLIGHT.pop(key, None)
            assert event is not None
            event.set()
    return value, "MISS", ttl, generated_at


def invalidate_read_cache(*prefixes: str) -> None:
    with READ_CACHE_LOCK:
        if not prefixes:
            READ_CACHE.clear()
            return
        for key in list(READ_CACHE):
            if any(key.startswith(prefix) for prefix in prefixes):
                READ_CACHE.pop(key, None)


def apply_api_cache_headers(
    response: Response,
    *,
    state: str,
    ttl: float,
    generated_at: float,
) -> None:
    max_age = max(0, int(ttl))
    response.headers["Cache-Control"] = f"private, max-age={max_age}"
    response.headers["Vary"] = "Authorization"
    response.headers["X-Cloud-Cache"] = state
    response.headers["X-Cloud-Cache-Ttl"] = str(max_age)
    response.headers["X-Cloud-Generated-At"] = str(round(generated_at, 3))


def frontend_cache_headers(full_path: str) -> dict[str, str]:
    normalized = full_path.lstrip("/")
    if normalized.startswith("assets/"):
        return {
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        }
    return {
        "Cache-Control": "no-cache, max-age=0, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }


def default_auth_store() -> dict[str, Any]:
    """Start with no usable account unless one was configured on purpose.

    Accounts and their project memberships live in this file and are added by
    editing it -- there is no sign-up flow. A built-in admin/admin was never a
    bootstrap step, only a password everybody already knows. Set
    PLATFORM_ADMIN_PASSWORD to get an admin account on a fresh install.
    """
    users: dict[str, Any] = {
        "local-user": {"password": "", "role": "user", "name": "Local User"},
    }
    admin_password = os.getenv("PLATFORM_ADMIN_PASSWORD", "").strip()
    if admin_password:
        users["admin"] = {
            "password": admin_password,
            "role": "admin",
            "name": "Admin",
        }
    return {"users": users, "memberships": {}, "tokens": {}}


def load_auth_store() -> dict[str, Any]:
    with AUTH_LOCK:
        try:
            data = json.loads(AUTH_STORE.read_text())
            if isinstance(data, dict):
                data.setdefault("users", {})
                data.setdefault("memberships", {})
                data.setdefault("tokens", {})
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


def issue_session_token(user_id: str) -> str:
    """Record a session server-side and hand back only its opaque key.

    Roles used to arrive in a request header, so anyone could claim to be an
    admin. Now the caller presents a token it cannot forge and the role is read
    from this store, never from the request.
    """
    token = secrets.token_urlsafe(32)
    now = time.time()
    store = load_auth_store()
    tokens = store.setdefault("tokens", {})
    for existing, entry in list(tokens.items()):
        if float(entry.get("expires_at", 0)) <= now:
            tokens.pop(existing, None)
    tokens[token] = {
        "user_id": user_id,
        "issued_at": now,
        "expires_at": now + SESSION_TOKEN_TTL,
    }
    save_auth_store(store)
    return token


def revoke_session_token(token: str) -> None:
    store = load_auth_store()
    if store.setdefault("tokens", {}).pop(token, None) is not None:
        save_auth_store(store)


def authenticated_user(authorization: str | None) -> tuple[str, Role]:
    if not authorization or not authorization.startswith("Bearer "):
        return "", "visitor"
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return "", "visitor"
    store = load_auth_store()
    entry = store.get("tokens", {}).get(token)
    if not isinstance(entry, dict):
        return "", "visitor"
    if float(entry.get("expires_at", 0)) <= time.time():
        return "", "visitor"
    user_id = str(entry.get("user_id") or "")
    user = store.get("users", {}).get(user_id)
    if not user:
        return "", "visitor"
    # Read the role from the account, so a change takes effect immediately
    # rather than being frozen into the token.
    role: Role = "admin" if str(user.get("role", "")).lower() == "admin" else "user"
    return user_id, role


def conversation_session_id(user_id: str, scope: str) -> str:
    """Derive the agent conversation id from the caller, not from the client.

    The client used to generate this value, so the agent had no idea who was
    talking and no way to tell whose conversation it was handing back. Deriving
    it here keeps each user's conversation separate, makes it survive a closed
    drawer or a page reload, and leaves nothing for a caller to forge.
    """
    digest = hashlib.sha256(f"{user_id}\x00{scope}".encode("utf-8")).hexdigest()
    return f"s-{digest[:32]}"


def control_plane_headers() -> dict[str, str]:
    token = os.getenv("PLATFORM_ROOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(
            status_code=500,
            detail="PLATFORM_ROOT_TOKEN is not configured on the web layer",
        )
    return {"Authorization": f"Bearer {token}"}


def project_agent_headers(project: str) -> dict[str, str]:
    """Derive the inbound token the given project agent will accept.

    Only the web layer and the control plane hold AGENT_INBOUND_SECRET, so one
    project agent cannot compute another project agent's token.
    """
    secret = os.getenv("AGENT_INBOUND_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=500,
            detail="AGENT_INBOUND_SECRET is not configured on the web layer",
        )
    token = hmac.new(
        secret.encode("utf-8"),
        project.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"Authorization": f"Bearer {token}"}


def agent_request(
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    try:
        response = requests.request(
            method,
            f"{SKILL_AGENT_URL}{path}",
            json=json_body,
            headers=control_plane_headers(),
            timeout=timeout or REQUEST_TIMEOUT,
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
    timeout: float | None = None,
) -> dict[str, Any]:
    url = f"{project_agent_url(project).rstrip('/')}{path}"
    headers = project_agent_headers(project)
    read_timeout = timeout or REQUEST_TIMEOUT
    if AUTO_ENSURE_PROJECT_AGENT:
        ensure_project_agent(project)
    try:
        response = requests.request(
            method,
            url,
            json=json_body,
            headers=headers,
            timeout=read_timeout,
        )
    except requests.Timeout as exc:
        # A build outlives this timeout routinely. Retrying here recreated the
        # agent mid-redeploy and sent the same mutation again, which failed on
        # the half-finished workspace and reported a deploy that had actually
        # succeeded as an error. A slow answer is not an unreachable agent.
        raise HTTPException(
            status_code=504,
            detail={
                "message": f"{project} 작업이 아직 끝나지 않았습니다.",
                "hint": "서버에서 계속 진행 중일 수 있습니다. 목록을 새로고침해 결과를 확인하세요.",
            },
        ) from exc
    except requests.RequestException as first_exc:
        # Connection-level failures mean the request never landed, so resending
        # it cannot duplicate work.
        ensure_project_agent(project, force=True)
        wait_project_agent_ready(project)
        try:
            response = requests.request(
                method,
                url,
                json=json_body,
                headers=headers,
                timeout=read_timeout,
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
    if AUTO_ENSURE_PROJECT_AGENT and not force:
        with PROJECT_AGENT_ENSURE_LOCK:
            last = PROJECT_AGENT_ENSURED_AT.get(project, 0)
            if now - last < PROJECT_AGENT_ENSURE_TTL:
                return
    # Reachable is not the same as current. Skipping the ensure whenever the
    # agent answered left project agents running whatever image they started
    # with, so a deployed change never reached them. The ensure itself compares
    # the desired service definition and only recreates when it differs.
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
    data, _, _, _ = cached_read(
        "project-summaries",
        PROJECT_SUMMARY_CACHE_TTL,
        project_summary_catalog,
    )
    projects = data.get("projects", [])
    return {str(item.get("name")) for item in projects if item.get("name")}


def project_summary_catalog() -> dict[str, Any]:
    return agent_request("GET", "/project-summaries")


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


def project_owners(projects: list[dict[str, Any]]) -> dict[str, str]:
    # The console lists other people's projects for admins, so a row has to say
    # whose it is. Membership lives here, not in the agent, so the name is
    # attached on the way out instead of asking the agent for something it
    # cannot know.
    store = load_auth_store()
    memberships = store.get("memberships", {})
    users = store.get("users", {})
    owners: dict[str, str] = {}
    for project in projects:
        name = str(project.get("name") or "")
        members = memberships.get(name, {})
        owner_id = next(
            (member for member, role in members.items() if role == "owner"),
            next(iter(members), ""),
        )
        if owner_id:
            owners[name] = str(users.get(owner_id, {}).get("name") or owner_id)
    return owners


@app.get("/api/health")
def health() -> dict[str, Any]:
    agent = agent_request("GET", "/health")
    return {"status": "ok", "skill_agent": agent}


@app.post("/api/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    store = load_auth_store()
    user = store.get("users", {}).get(payload.user_id)
    stored_password = str(user.get("password", "")) if user else ""
    # Accounts without a password were created implicitly by the old
    # header-trusting code. They are not sign-in credentials: allowing an empty
    # password would let anyone assume those identities.
    if not user or not stored_password:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not secrets.compare_digest(stored_password, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "id": payload.user_id,
        "role": user.get("role", "user"),
        "name": user.get("name", payload.user_id),
        "token": issue_session_token(payload.user_id),
        "expires_in": int(SESSION_TOKEN_TTL),
        "auth_mode": "bearer-token",
    }


@app.post("/api/logout")
def logout(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if authorization and authorization.startswith("Bearer "):
        revoke_session_token(authorization.removeprefix("Bearer ").strip())
    return {"status": "ok"}


@app.get("/api/me")
def me(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
    return {
        "id": user_id if role != "visitor" else None,
        "role": role,
        "auth_mode": "bearer-token",
    }


@app.get("/api/projects")
def list_projects(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
    require_login(role)
    data, cache_state, cache_ttl, generated_at = cached_read(
        "project-summaries",
        PROJECT_SUMMARY_CACHE_TTL,
        project_summary_catalog,
        bypass=request_bypasses_cache(request),
    )
    apply_api_cache_headers(
        response,
        state=cache_state,
        ttl=cache_ttl,
        generated_at=generated_at,
    )
    all_projects = data.get("projects", [])
    projects = visible_projects(role, user_id, all_projects)
    owners = project_owners(all_projects)
    # Membership, not visibility. An admin sees every project but is a member of
    # only their own, and the console's "내 프로젝트" filter means the latter.
    memberships = load_auth_store().get("memberships", {})
    member_of = [
        str(item.get("name"))
        for item in projects
        if user_id in memberships.get(str(item.get("name")), {})
    ]
    return {
        "user": {"id": user_id, "role": role},
        "projects": [{**item, "owner": owners.get(str(item.get("name")))} for item in projects],
        "member_of": member_of,
        "owners": owners,
        "incomplete_projects": data.get("incomplete_projects", []),
        "membership_mode": "json-table",
    }


# The catalog is deliberately public, so it carries only what the console
# renders. Repository URLs and raw runtime errors are not part of that.
PUBLIC_PROJECT_FIELDS = (
    "name",
    "services",
    "frameworks",
    "public_urls",
    "service_count",
    "running_count",
    "attention_count",
    "memory_total_mb",
    "last_deployed_at",
)
PUBLIC_SERVICE_FIELDS = (
    "service",
    "name",
    "framework",
    "framework_label",
    "frontend",
    "host_port",
    "status",
    "last_deployed_at",
)


def public_project_view(project: dict[str, Any]) -> dict[str, Any]:
    view = {key: project.get(key) for key in PUBLIC_PROJECT_FIELDS}
    view["service_summaries"] = [
        {key: service.get(key) for key in PUBLIC_SERVICE_FIELDS}
        for service in project.get("service_summaries") or []
    ]
    # Say that something needs attention without saying what failed.
    view["runtime_error"] = bool(project.get("runtime_error"))
    return view


@app.get("/api/catalog")
def service_catalog(request: Request, response: Response) -> dict[str, Any]:
    data, cache_state, cache_ttl, generated_at = cached_read(
        "project-summaries",
        CATALOG_CACHE_TTL,
        project_summary_catalog,
        bypass=request_bypasses_cache(request),
    )
    apply_api_cache_headers(
        response,
        state=cache_state,
        ttl=cache_ttl,
        generated_at=generated_at,
    )
    projects = [public_project_view(item) for item in data.get("projects", [])]
    services = []
    for project in projects:
        project_name = str(project.get("name") or "")
        summaries = project.get("service_summaries") or []
        if not summaries:
            summaries = [{"service": service} for service in project.get("services", []) or []]
        for service in summaries:
            service_name = str(service.get("service") or service.get("name") or "")
            if not service_name:
                continue
            services.append({
                "project": project_name,
                "service": service_name,
                "framework": service.get("framework"),
                "framework_label": service.get("framework_label"),
                "frontend": service.get("frontend"),
                "host_port": service.get("host_port"),
                "status": service.get("status"),
                "last_deployed_at": service.get("last_deployed_at"),
            })
    return {
        "projects": projects,
        "services": services,
        "visibility": "operational-summary",
    }


@app.get("/api/system/summary")
def system_summary(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _, role = authenticated_user(authorization)
    require_login(role)
    data, cache_state, cache_ttl, generated_at = cached_read(
        "system-summary",
        SYSTEM_SUMMARY_CACHE_TTL,
        lambda: agent_request("POST", "/execute", json_body={
            "skill": "server.health",
            "arguments": {},
            "approved": True,
        }),
        bypass=request_bypasses_cache(request),
    )
    apply_api_cache_headers(
        response,
        state=cache_state,
        ttl=cache_ttl,
        generated_at=generated_at,
    )
    return data


# The signed-out home shows the same server strip as the signed-in one, so the
# two capacity numbers on it have to be readable without a session. Everything
# else server.health returns — free bytes, swap, container names, warnings —
# stays behind the login.
@app.get("/api/system/public")
def public_system_summary(request: Request, response: Response) -> dict[str, Any]:
    data, cache_state, cache_ttl, generated_at = cached_read(
        "system-summary",
        SYSTEM_SUMMARY_CACHE_TTL,
        lambda: agent_request("POST", "/execute", json_body={
            "skill": "server.health",
            "arguments": {},
            "approved": True,
        }),
        bypass=request_bypasses_cache(request),
    )
    apply_api_cache_headers(
        response,
        state=cache_state,
        ttl=cache_ttl,
        generated_at=generated_at,
    )
    result = data.get("result") if isinstance(data, dict) else None
    result = result if isinstance(result, dict) else {}
    return {
        "result": {
            "memory_percent": result.get("memory_percent"),
            "disk_percent": result.get("disk_percent"),
        },
        "visibility": "capacity-only",
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
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
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
    invalidate_read_cache()
    add_project_membership(name, user_id or "local-user", "owner")
    return result


@app.post("/api/projects/{project}/chat")
def project_chat(
    project: str,
    payload: ChatRequest,
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
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
        "session_id": conversation_session_id(user_id, project),
        "context": context,
    })


@app.post("/api/admin/chat")
def admin_chat(
    payload: ChatRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
    require_admin(role)
    body = payload.model_dump()
    body["session_id"] = conversation_session_id(user_id, "admin")
    return agent_request("POST", "/chat", json_body=body)


@app.post("/api/admin/execute")
def admin_execute(
    payload: ExecuteRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
    require_admin(role)
    mutating = payload.approved and payload.skill in MUTATION_SKILLS
    result = agent_request(
        "POST",
        "/execute",
        json_body={
            "skill": payload.skill,
            "arguments": payload.arguments,
            "approved": payload.approved,
            "session_id": conversation_session_id(user_id, "admin"),
            "resume": payload.resume,
        },
        timeout=MUTATION_REQUEST_TIMEOUT if mutating else None,
    )
    if mutating:
        invalidate_read_cache()
    return result


# Approval cards and the deploy summary have to show a real dry run, not a
# guess assembled in the browser. The agent already refuses /execute without
# approval, so the plan has to come from /preview.
@app.post("/api/projects/{project}/preview")
def project_preview(
    project: str,
    payload: ExecuteRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
    ensure_project_access(role, user_id, project)
    arguments = dict(payload.arguments)
    arguments["project"] = project
    return project_agent_request(project, "POST", "/preview", json_body={
        "skill": payload.skill,
        "arguments": arguments,
    })


@app.post("/api/admin/preview")
def admin_preview(
    payload: ExecuteRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _, role = authenticated_user(authorization)
    require_admin(role)
    return agent_request("POST", "/preview", json_body={
        "skill": payload.skill,
        "arguments": payload.arguments,
    })


@app.post("/api/projects/{project}/execute")
def project_execute(
    project: str,
    payload: ExecuteRequest,
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    user_id, role = authenticated_user(authorization)
    ensure_project_access(role, user_id, project)
    arguments = dict(payload.arguments)
    arguments["project"] = project
    body = {
        "skill": payload.skill,
        "arguments": arguments,
        "approved": payload.approved,
        "session_id": conversation_session_id(user_id, project),
        "resume": payload.resume,
    }
    if payload.skill == "service.status" and payload.approved:
        service = str(arguments.get("service") or "")
        data, cache_state, cache_ttl, generated_at = cached_read(
            f"service-status:{project}:{service}",
            SERVICE_STATUS_CACHE_TTL,
            lambda: project_agent_request(project, "POST", "/execute", json_body=body),
            bypass=request_bypasses_cache(request),
        )
        apply_api_cache_headers(
            response,
            state=cache_state,
            ttl=cache_ttl,
            generated_at=generated_at,
        )
        return data
    mutating = payload.approved and payload.skill in MUTATION_SKILLS
    result = project_agent_request(
        project,
        "POST",
        "/execute",
        json_body=body,
        timeout=MUTATION_REQUEST_TIMEOUT if mutating else None,
    )
    if mutating:
        invalidate_read_cache()
    return result


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
        return FileResponse(requested, headers=frontend_cache_headers(full_path))
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index, headers=frontend_cache_headers(""))
    raise HTTPException(status_code=404, detail="Frontend index.html not found.")
