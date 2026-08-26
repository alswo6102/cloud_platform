from __future__ import annotations

import json
import hashlib
import hmac
import os
import re
import secrets
from copy import deepcopy
from difflib import SequenceMatcher
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import docker
import psutil
import requests
import yaml
import cli_contracts
from deployment_presets import (
    DEFAULT_CONTAINER_PORT,
    FRAMEWORK_PRESETS,
    framework_manual,
    preset_catalog,
    render_dockerfile,
    validate_framework,
)

PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", "/srv/projects"))
SKILLS_ROOT = Path(os.getenv("SKILLS_ROOT", "/app/skills"))
DOCS_ROOT = Path(os.getenv("DOCS_ROOT", "/app/docs"))
AUDIT_LOG = Path(os.getenv("AUDIT_LOG", "/var/log/skill-agent/audit.jsonl"))
NAMESPACE_TOKEN_STORE = Path(
    os.getenv("NAMESPACE_TOKEN_STORE", "/var/log/skill-agent/namespace_tokens.json")
)
CONTROL_PLANE_NETWORK = os.getenv("CONTROL_PLANE_NETWORK", "cloud-platform-internal")
# The control plane listens on the same port everywhere in this repo. Project
# agents reach it as http://platform-api:<port> over their own control network.
PLATFORM_API_PORT = int(os.getenv("PLATFORM_API_PORT", "8080"))
# How many planner turns one message may take. Read-only lookups, a correction
# after a validation error, and the final answer all come out of this budget.
LLM_MAX_STEPS = int(os.getenv("LLM_MAX_STEPS", "12"))
SAFE_CLEANUP_SCRIPT = Path(
    os.getenv("SAFE_DOCKER_CLEANUP_SCRIPT", "/app/scripts/server_safe_docker_cleanup.sh")
)
PORT_START = int(os.getenv("PORT_START", "9000"))
PORT_END = int(os.getenv("PORT_END", "9100"))
SERVICE_METADATA_DIR = ".cloud-platform"
SERVICE_METADATA_FILE = "services.json"


def project_agent_template_version() -> str:
    explicit = os.getenv("PROJECT_AGENT_TEMPLATE_VERSION", "").strip()
    if explicit and os.getenv("PLATFORM_NAMESPACE", "").strip():
        return explicit
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for relative in (
        "app.py",
        "cli.py",
        "cli_contracts.py",
        "runtime.py",
        "deployment_presets.py",
    ):
        path = root / relative
        if not path.exists() and relative == "deployment_presets.py":
            path = root.parent / relative
        digest.update(relative.encode())
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"missing")
    return digest.hexdigest()[:16]
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
API_SKILL_NAMES = {
    "entity-resolve": "entity.resolve",
    "framework-list": "framework.list",
    "help-search": "help.search",
    "platform-help": "platform.help",
    "server-health": "server.health",
    "project-create": "project.create",
    "project-list": "project.list",
    "service-deploy": "service.deploy",
    "service-redeploy": "service.redeploy",
    "repository-inspect": "repository.inspect",
    "service-status": "service.status",
    "service-logs": "service.logs",
    "service-control": "service.control",
    "port-suggest": "port.suggest",
    "port-manage": "port.manage",
    "qa-run": "qa.run",
}
SKILL_API_NAMES = {value: key for key, value in API_SKILL_NAMES.items()}
GITHUB_HTTPS_PATTERN = re.compile(
    r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$"
)
MODEL_COOLDOWNS: dict[str, float] = {}
MODEL_COOLDOWN_LOCK = threading.Lock()
REPOSITORY_ACCESS_CACHE: dict[str, float] = {}
REPOSITORY_ACCESS_CACHE_LOCK = threading.Lock()
REPOSITORY_ACCESS_CACHE_TTL = float(os.getenv("REPOSITORY_ACCESS_CACHE_TTL", "300"))


class SkillError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        field: str | None = None,
        hint: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.field = field
        self.hint = hint
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"message": self.message}
        if self.code:
            payload["code"] = self.code
        if self.field:
            payload["field"] = self.field
        if self.hint:
            payload["hint"] = self.hint
        if self.detail:
            payload["detail"] = self.detail
        return payload

    @classmethod
    def from_detail(cls, detail: Any) -> "SkillError":
        if isinstance(detail, dict):
            return cls(
                str(detail.get("message") or detail.get("detail") or "CLI execution failed"),
                code=str(detail["code"]) if detail.get("code") else None,
                field=str(detail["field"]) if detail.get("field") else None,
                hint=str(detail["hint"]) if detail.get("hint") else None,
                detail=str(detail["detail"]) if detail.get("detail") else None,
            )
        return cls(str(detail or "CLI execution failed"))


def invalid_repo_url_error() -> SkillError:
    return SkillError(
        "GitHub 저장소 URL 형식이 올바르지 않습니다.",
        code="repo_url_invalid_format",
        field="repo_url",
        hint="https://github.com/<owner>/<repo> 형태의 공개 저장소 URL을 입력하세요.",
    )


def trigger_safe_docker_cleanup(reason: str) -> None:
    if os.getenv("AUTO_DOCKER_CLEANUP", "1").lower() in {"0", "false", "no"}:
        return
    if not SAFE_CLEANUP_SCRIPT.is_file():
        return

    def run() -> None:
        try:
            subprocess.run(
                [str(SAFE_CLEANUP_SCRIPT), "--quiet"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
                env={**os.environ, "CLEANUP_TRIGGER": reason},
            )
        except Exception:
            pass

    threading.Thread(target=run, name=f"safe-cleanup-{reason}", daemon=True).start()


def validate_name(value: str, label: str) -> str:
    if not NAME_PATTERN.fullmatch(value):
        raise SkillError(f"Invalid {label}: {value!r}")
    return value


def project_path(project: str) -> Path:
    validate_name(project, "project")
    path = (PROJECTS_ROOT / project).resolve()
    if path.parent != PROJECTS_ROOT.resolve() or not path.is_dir():
        raise SkillError(f"Project not found: {project}")
    return path


def compose_path(project: str) -> Path:
    path = project_path(project) / "docker-compose.yml"
    if not path.is_file():
        raise SkillError(f"Compose file not found for project: {project}")
    return path


def load_compose(project: str) -> dict[str, Any]:
    data = yaml.safe_load(compose_path(project).read_text()) or {}
    if not isinstance(data.get("services"), dict):
        raise SkillError(f"No services found in project: {project}")
    return data


def service_config(project: str, service: str) -> dict[str, Any]:
    validate_name(service, "service")
    services = load_compose(project)["services"]
    if service not in services:
        raise SkillError(f"Service not found: {project}/{service}")
    return services[service]


def service_metadata_path(project: str) -> Path:
    return project_path(project) / SERVICE_METADATA_DIR / SERVICE_METADATA_FILE


def load_service_metadata(project: str) -> dict[str, dict[str, Any]]:
    path = service_metadata_path(project)
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    raw_services = data.get("services") if isinstance(data, dict) else {}
    if not isinstance(raw_services, dict):
        return {}
    return {
        str(name): value
        for name, value in raw_services.items()
        if isinstance(value, dict)
    }


def save_service_metadata(project: str, services: dict[str, dict[str, Any]]) -> None:
    path = service_metadata_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "services": services,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    temporary.replace(path)


def labels_as_dict(labels: Any) -> dict[str, str]:
    if isinstance(labels, dict):
        return {str(key): str(value) for key, value in labels.items()}
    result: dict[str, str] = {}
    if isinstance(labels, list):
        for item in labels:
            if not isinstance(item, str):
                continue
            key, separator, value = item.partition("=")
            if separator:
                result[key] = value
            else:
                result[key] = "true"
    return result


def label_truthy(labels: dict[str, str], key: str) -> bool:
    return labels.get(key, "").strip().lower() in {"1", "true", "yes"}


def first_verified_port(verified: dict[str, Any] | None) -> dict[str, int] | None:
    ports = verified.get("ports") if isinstance(verified, dict) else []
    if not isinstance(ports, list):
        return None
    for port in ports:
        if not isinstance(port, dict):
            continue
        host = port.get("host")
        container = port.get("container")
        if host is None or container is None:
            continue
        try:
            return {"host": int(host), "container": int(container)}
        except (TypeError, ValueError):
            continue
    return None


def service_source_path(project: str, service: str, config: dict[str, Any]) -> Path | None:
    build = config.get("build")
    context: Any = None
    if isinstance(build, str):
        context = build
    elif isinstance(build, dict):
        context = build.get("context")
    if context is None:
        candidate = project_path(project) / service
    else:
        candidate = (project_path(project) / str(context)).resolve()
    root = project_path(project).resolve()
    if candidate == root or root not in candidate.parents:
        return None
    return candidate if candidate.is_dir() else None


def dependency_text(source: Path, names: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for name in names:
        path = source / name
        if path.is_file():
            try:
                chunks.append(path.read_text(errors="replace").lower())
            except OSError:
                continue
    return "\n".join(chunks)


def infer_framework_from_source(
    project: str,
    service: str,
    config: dict[str, Any],
) -> str | None:
    source = service_source_path(project, service, config)
    if source is None:
        return None

    package_path = source / "package.json"
    if package_path.is_file():
        try:
            package = json.loads(package_path.read_text())
        except (json.JSONDecodeError, OSError):
            package = {}
        if not isinstance(package, dict):
            package = {}
        dependencies = {
            **(package.get("dependencies") or {}),
            **(package.get("devDependencies") or {}),
        }
        scripts = package.get("scripts") or {}
        dependency_names = {str(name).lower() for name in dependencies}
        script_values = " ".join(str(value).lower() for value in scripts.values())
        if "next" in dependency_names or "next " in script_values:
            return "nextjs"
        if "vite" in dependency_names or "vite" in script_values or any(source.glob("vite.config.*")):
            return "vite"
        if "react-scripts" in dependency_names:
            return "react"
        if "@nestjs/core" in dependency_names or "express" in dependency_names:
            return "express"
        if "react" in dependency_names:
            return "vite"
        return "express"

    python_text = dependency_text(source, ("requirements.txt", "pyproject.toml", "Pipfile"))
    if (source / "manage.py").is_file() or "django" in python_text:
        return "django"
    if "fastapi" in python_text:
        return "fastapi"
    if "flask" in python_text:
        return "flask"
    if (source / "pom.xml").is_file():
        return "spring-maven"
    if (source / "build.gradle").is_file() or (source / "build.gradle.kts").is_file():
        return "spring-gradle"
    if (source / "go.mod").is_file():
        return "go"
    if any(source.glob("*.html")) or (source / "index.html").is_file():
        return "static"
    if (source / "Dockerfile").is_file():
        return "existing"
    return None


def record_service_deploy_metadata(
    project: str,
    service: str,
    *,
    framework: str | None,
    repo_url: str | None,
    is_web: bool | None,
    verified: dict[str, Any] | None,
) -> dict[str, Any]:
    services = load_service_metadata(project)
    current = dict(services.get(service) or {})
    port = first_verified_port(verified)
    deployed_at = datetime.now(timezone.utc).isoformat()
    next_metadata = {
        **current,
        "service": service,
        "framework": framework or current.get("framework"),
        "repo_url": repo_url or current.get("repo_url"),
        "frontend": bool(is_web) if is_web is not None else bool(current.get("frontend")),
        "deployed_at": deployed_at,
        "last_deployed_at": deployed_at,
    }
    if port:
        next_metadata["host_port"] = port["host"]
        next_metadata["container_port"] = port["container"]
    services[service] = {
        key: value
        for key, value in next_metadata.items()
        if value not in (None, "")
    }
    save_service_metadata(project, services)
    return services[service]


def docker_client():
    return docker.from_env()


def project_network_name(project: str, kind: str) -> str:
    validate_name(project, "project")
    if kind not in {"app", "control"}:
        raise SkillError(f"Unsupported network kind: {kind}")
    return f"cp_{project}_{kind}_net"


def ensure_docker_network(name: str, project: str, kind: str):
    client = docker_client()
    matches = client.networks.list(names=[name])
    for network in matches:
        if network.name == name:
            return network
    return client.networks.create(
        name,
        driver="bridge",
        labels={
            "cloud.platform.project": project,
            "cloud.platform.network": kind,
        },
    )


def attach_platform_api_to_control_network(network) -> None:
    container_id = os.getenv("HOSTNAME", "")
    if not container_id:
        return
    try:
        container = docker_client().containers.get(container_id)
        network.reload()
        if container.id in (network.attrs.get("Containers") or {}):
            return
        network.connect(container, aliases=["platform-api"])
    except Exception:
        # Network attachment is a convenience for future project agents. The
        # project namespace itself should still be created even if the current
        # runtime is not a long-lived platform-api container.
        return


def attach_platform_api_to_existing_control_networks() -> list[str]:
    if os.getenv("PLATFORM_API"):
        return []
    client = docker_client()
    attached: list[str] = []
    for network in client.networks.list(
        filters={"label": "cloud.platform.network=control"}
    ):
        before = set((network.attrs.get("Containers") or {}).keys())
        attach_platform_api_to_control_network(network)
        network.reload()
        after = set((network.attrs.get("Containers") or {}).keys())
        if after != before:
            attached.append(network.name)
    return attached


def ensure_project_networks(project: str, *, attach_platform_api: bool) -> dict[str, str]:
    app_name = project_network_name(project, "app")
    control_name = project_network_name(project, "control")
    ensure_docker_network(app_name, project, "app")
    control = ensure_docker_network(control_name, project, "control")
    if attach_platform_api:
        attach_platform_api_to_control_network(control)
    return {"app_network": app_name, "control_network": control_name}


def register_namespace_token(project: str) -> bool:
    _, created = ensure_namespace_token(project)
    return created


def ensure_namespace_token(project: str) -> tuple[str, bool]:
    validate_name(project, "project")
    NAMESPACE_TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(NAMESPACE_TOKEN_STORE.read_text())
        tokens = data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        tokens = {}
    for token, namespace in tokens.items():
        if str(namespace) == project:
            return str(token), False
    token = secrets.token_urlsafe(32)
    tokens[token] = project
    temporary = NAMESPACE_TOKEN_STORE.with_suffix(".tmp")
    temporary.write_text(json.dumps(tokens, ensure_ascii=False, indent=2))
    temporary.replace(NAMESPACE_TOKEN_STORE)
    return token, True


def project_agent_state_volume(project: str) -> str:
    validate_name(project, "project")
    return f"cp_{project}_agent_state"


def project_compose_scaffold(project: str, networks: dict[str, str]) -> dict[str, Any]:
    """Top-level networks and volumes every managed project compose declares.

    project.create and project.ensure_agent both write the agent service, so
    they must agree on what that service may reference. Keeping the scaffold in
    one place stops a new project from being created without the agent state
    volume its service definition mounts.
    """
    state_volume = project_agent_state_volume(project)
    return {
        "networks": {
            "app-net": {
                "name": networks["app_network"],
                "external": True,
            },
            "control-net": {
                "name": networks["control_network"],
                "external": True,
            },
            "control-plane": {
                "name": CONTROL_PLANE_NETWORK,
                "external": True,
            },
        },
        "volumes": {
            state_volume: {"name": state_volume},
        },
    }


def agent_inbound_token(project: str) -> str:
    """Derive the inbound token a project agent will require of its callers.

    Only the web layer and the control plane hold AGENT_INBOUND_SECRET, so a
    project agent can verify the token it was handed but cannot derive another
    project's token and drive that project's agent on its behalf.
    """
    validate_name(project, "project")
    secret = os.getenv("AGENT_INBOUND_SECRET", "").strip()
    if not secret:
        return ""
    return hmac.new(
        secret.encode("utf-8"),
        project.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def project_agent_service_definition(project: str, token: str) -> dict[str, Any]:
    validate_name(project, "project")
    template_version = project_agent_template_version()
    environment = {
        "PROJECTS_ROOT": str(PROJECTS_ROOT),
        "PLATFORM_NAMESPACE": project,
        "PLATFORM_TOKEN": token,
        "PLATFORM_API": f"http://platform-api:{PLATFORM_API_PORT}",
        "SESSION_STORE": f"/var/log/skill-agent/{project}-sessions.json",
        "PROJECT_AGENT_TEMPLATE_VERSION": template_version,
    }
    inbound_token = agent_inbound_token(project)
    if inbound_token:
        environment["AGENT_INBOUND_TOKEN"] = inbound_token
    for key in (
        "LLM_API_KEY",
        "LLM_API_URL",
        "LLM_MODEL",
        "LLM_MODELS",
        "LLM_REQUEST_TIMEOUT",
        "LLM_SLOT_FILL_ON_MISSING",
    ):
        if os.getenv(key):
            environment[key] = f"${{{key}}}"
    return {
        "image": os.getenv("PROJECT_AGENT_IMAGE", "cloud-platform-skill-agent:latest"),
        "command": "uvicorn app:app --host 0.0.0.0 --port 8080",
        "restart": "unless-stopped",
        "environment": environment,
        # Deliberately not on app-net: deployed service containers run
        # user-supplied code and must not be able to reach the agent.
        "networks": {
            "control-net": {
                "aliases": ["project-agent", f"{project}-agent"],
            },
            "control-plane": {
                "aliases": [f"project-agent-{project}"],
            },
        },
        # Conversation state must survive the force-recreate that any source
        # change triggers through PROJECT_AGENT_TEMPLATE_VERSION.
        "volumes": [f"{project_agent_state_volume(project)}:/var/log/skill-agent"],
        "labels": [
            f"cloud.platform.project={project}",
            "cloud.platform.role=agent",
            f"cloud.platform.agent.template_version={template_version}",
        ],
        "mem_limit": "512m",
        "memswap_limit": "1g",
    }


def ensure_project_agent(project: str, dry_run: bool = False) -> dict[str, Any]:
    validate_name(project, "project")
    data = load_compose(project)
    networks = ensure_project_networks(project, attach_platform_api=True)
    token, token_created = ensure_namespace_token(project)
    if not isinstance(data.get("services"), dict):
        data["services"] = {}
    scaffold = project_compose_scaffold(project, networks)
    for section in ("networks", "volumes"):
        if not isinstance(data.get(section), dict):
            data[section] = {}
        data[section].update(scaffold[section])
    desired = project_agent_service_definition(project, token)
    current_agent = data["services"].get("agent")
    changed = current_agent != desired
    template_version = desired["environment"]["PROJECT_AGENT_TEMPLATE_VERSION"]
    current_template_version = (
        (current_agent or {}).get("environment", {}) or {}
    ).get("PROJECT_AGENT_TEMPLATE_VERSION") if isinstance(current_agent, dict) else None
    plan = {
        "project": project,
        "agent_service": "agent",
        "dns": f"project-agent-{project}",
        "networks": ["control-net", "control-plane"],
        "state_volume": project_agent_state_volume(project),
        "token_created": token_created,
        "changed": changed,
        "template_version": template_version,
        "current_template_version": current_template_version,
    }
    if dry_run:
        return {"dry_run": True, **plan}
    if changed:
        backup = write_compose_atomic(project, {**data, "services": {**data["services"], "agent": desired}})
        try:
            compose_command(project, "up", "-d", "--force-recreate", "agent", timeout=300)
            backup.unlink(missing_ok=True)
        except Exception:
            rollback_compose(project, backup)
            raise
    else:
        compose_command(project, "up", "-d", "agent", timeout=300)
    container = find_container(project, "agent")
    return {
        "dry_run": False,
        **plan,
        "verified": container_summary(container) if container else None,
    }


def find_container(project: str, service: str):
    containers = docker_client().containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={project}",
                f"com.docker.compose.service={service}",
            ]
        },
    )
    return containers[0] if containers else None


def parse_published_port(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("published")
        return int(value) if str(value).isdigit() else None
    if not isinstance(value, str):
        return None
    parts = value.split("/")[0].rsplit(":", 2)
    return int(parts[-2]) if len(parts) >= 2 and parts[-2].isdigit() else None


def parse_target_port(value: Any) -> int | None:
    if isinstance(value, dict):
        value = value.get("target")
        return int(value) if str(value).isdigit() else None
    if not isinstance(value, str):
        return None
    target = value.split("/")[0].rsplit(":", 1)[-1]
    return int(target) if target.isdigit() else None


def reserved_ports(exclude: tuple[str, str] | None = None) -> dict[int, list[str]]:
    result: dict[int, list[str]] = {}
    for file_path in PROJECTS_ROOT.glob("*/docker-compose.yml"):
        try:
            data = yaml.safe_load(file_path.read_text()) or {}
            for service, config in data.get("services", {}).items():
                owner = (file_path.parent.name, service)
                if owner == exclude:
                    continue
                for value in config.get("ports", []):
                    port = parse_published_port(value)
                    if port is not None:
                        result.setdefault(port, []).append("/".join(owner))
        except (OSError, yaml.YAMLError, AttributeError):
            continue
    return result


def next_port(exclude: tuple[str, str] | None = None) -> int:
    used = reserved_ports(exclude)
    for port in range(PORT_START, PORT_END + 1):
        if port not in used:
            return port
    raise SkillError(f"No available ports between {PORT_START} and {PORT_END}")


def compose_command(
    project: str,
    *args: str,
    timeout: int = 300,
) -> subprocess.CompletedProcess:
    command = ["docker-compose", "-p", project, *args]
    return subprocess.run(
        command,
        cwd=project_path(project),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def git_clone(repo_url: str, destination: Path) -> None:
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise invalid_repo_url_error()
    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(destination)],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise SkillError(
            "GitHub 저장소 clone 시간이 초과되었습니다.",
            code="repo_clone_timeout",
            field="repo_url",
            hint="저장소 크기나 네트워크 상태를 확인하고 다시 시도하세요.",
            detail=str(exc),
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SkillError(
            "GitHub 저장소를 clone할 수 없습니다.",
            code="repo_clone_failed",
            field="repo_url",
            hint="URL이 맞는지, 공개 저장소인지, 기본 브랜치에 접근 가능한지 확인하세요.",
            detail=detail,
        )


def validate_github_repository_access(repo_url: str) -> None:
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise invalid_repo_url_error()
    now = time.monotonic()
    with REPOSITORY_ACCESS_CACHE_LOCK:
        if REPOSITORY_ACCESS_CACHE.get(repo_url, 0) > now:
            return
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            capture_output=True,
            text=True,
            timeout=float(os.getenv("GIT_REPOSITORY_VALIDATE_TIMEOUT", "30")),
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired as exc:
        raise SkillError(
            "GitHub 저장소 접근 확인 시간이 초과되었습니다.",
            code="repo_access_timeout",
            field="repo_url",
            hint="저장소 URL이 맞는지 확인하고 잠시 후 다시 시도하세요. GitHub 또는 서버 네트워크가 느릴 수 있습니다.",
            detail=str(exc),
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        lowered = detail.lower()
        if "repository not found" in lowered or "not found" in lowered:
            code = "repo_not_found_or_private"
            message = "GitHub 저장소를 찾을 수 없거나 비공개 저장소입니다."
            hint = "저장소 URL이 정확한지 확인하고, 현재 배포 기능은 공개 GitHub HTTPS 저장소만 지원합니다."
        elif "authentication failed" in lowered or "could not read" in lowered or "permission denied" in lowered:
            code = "repo_private_or_auth_required"
            message = "GitHub 저장소 접근에 인증이 필요합니다."
            hint = "비공개 저장소는 현재 지원하지 않습니다. 공개 저장소로 변경하거나 공개 저장소 URL을 입력하세요."
        else:
            code = "repo_access_failed"
            message = "GitHub 저장소 접근 검증에 실패했습니다."
            hint = "URL, 공개 여부, 네트워크 접근 가능 여부를 확인하세요."
        raise SkillError(
            message,
            code=code,
            field="repo_url",
            hint=hint,
            detail=detail or None,
        )
    with REPOSITORY_ACCESS_CACHE_LOCK:
        REPOSITORY_ACCESS_CACHE[repo_url] = time.monotonic() + REPOSITORY_ACCESS_CACHE_TTL


def inspect_repository(repo_url: str) -> dict[str, Any]:
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise invalid_repo_url_error()
    with tempfile.TemporaryDirectory(prefix="cloud-platform-inspect-") as temp_dir:
        root = Path(temp_dir) / "repository"
        git_clone(repo_url, root)
        candidates: list[str] = []
        evidence: list[str] = []

        package_path = root / "package.json"
        if package_path.is_file():
            package = json.loads(package_path.read_text())
            dependencies = {
                **(package.get("dependencies") or {}),
                **(package.get("devDependencies") or {}),
            }
            scripts = package.get("scripts") or {}
            if "next" in dependencies:
                candidates.append("nextjs")
                evidence.append("package.json contains next")
            if "vite" in dependencies:
                candidates.append("vite")
                evidence.append("package.json contains vite")
            if "react-scripts" in dependencies:
                candidates.append("react")
                evidence.append("package.json contains react-scripts")
            if "@nestjs/core" in dependencies or "express" in dependencies:
                candidates.append("express")
                evidence.append("package.json contains NestJS or Express")
            if not candidates and "react" in dependencies:
                candidates.extend(["vite", "react"])
                evidence.append("package.json contains React but the build framework is ambiguous")
            if "start" in scripts:
                evidence.append("package.json contains a start script")

        dependency_text = ""
        for dependency_file in ("requirements.txt", "pyproject.toml"):
            path = root / dependency_file
            if path.is_file():
                dependency_text += "\n" + path.read_text(errors="replace").lower()
        if "fastapi" in dependency_text:
            candidates.append("fastapi")
            evidence.append("Python dependencies contain FastAPI")
        if "flask" in dependency_text:
            candidates.append("flask")
            evidence.append("Python dependencies contain Flask")
        if (root / "manage.py").is_file() or "django" in dependency_text:
            candidates.append("django")
            evidence.append("Django manage.py or dependency detected")
        if (root / "pom.xml").is_file():
            candidates.append("spring-maven")
            evidence.append("pom.xml detected")
        if (root / "build.gradle").is_file() or (root / "build.gradle.kts").is_file():
            candidates.append("spring-gradle")
            evidence.append("Gradle build file detected")
        if (root / "go.mod").is_file():
            candidates.append("go")
            evidence.append("go.mod detected")
        if (root / "Dockerfile").is_file():
            evidence.append("repository already contains a Dockerfile")
            # A repository that ships its own Dockerfile has already decided how
            # it builds. A generated preset would overwrite that decision, so
            # offer to use what is there before offering to replace it.
            candidates.insert(0, "existing")
        if (
            not candidates
            and not package_path.is_file()
            and any(root.glob("*.html"))
        ):
            candidates.append("static")
            evidence.append(
                "root HTML files detected without a package manager; static site preset applies"
            )

        candidates = list(dict.fromkeys(candidates))
        return {
            "repo_url": repo_url,
            "candidates": candidates,
            "evidence": evidence,
            "has_dockerfile": (root / "Dockerfile").is_file(),
        }


def wait_stable(project: str, service: str, seconds: int = 4) -> dict[str, Any]:
    container = find_container(project, service)
    if container is None:
        raise SkillError(f"Container was not created: {project}/{service}")
    container.reload()
    restart_count = container.attrs.get("RestartCount", 0)
    time.sleep(seconds)
    container.reload()
    new_restart_count = container.attrs.get("RestartCount", 0)
    if container.status != "running" or new_restart_count > restart_count:
        logs = container.logs(tail=30).decode(errors="replace").strip()
        raise SkillError(logs or f"Container status is {container.status}")
    return container_summary(container)


def container_summary(container) -> dict[str, Any]:
    container.reload()
    ports = []
    for target, bindings in (container.ports or {}).items():
        for binding in bindings or []:
            ports.append(
                {
                    "host": int(binding["HostPort"]),
                    "container": int(target.split("/")[0]),
                }
            )
    health = (container.attrs.get("State", {}).get("Health") or {}).get("Status")
    memory: dict[str, Any] | None = None
    try:
        stats = container.client.api.stats(container.id, stream=False, one_shot=True)
        memory_stats = stats.get("memory_stats") or {}
        usage = int(memory_stats.get("usage") or 0)
        limit = int(memory_stats.get("limit") or 0)
        if usage:
            memory = {
                "usage_bytes": usage,
                "limit_bytes": limit or None,
                "usage_mb": round(usage / 1024 / 1024, 1),
                "limit_mb": round(limit / 1024 / 1024, 1) if limit else None,
                "percent": round((usage / limit) * 100, 1) if limit else None,
            }
    except Exception:
        memory = None
    return {
        "name": container.name,
        "status": container.status,
        "health": health,
        "restart_count": container.attrs.get("RestartCount", 0),
        "ports": ports,
        "memory": memory,
    }


def write_compose_atomic(project: str, data: dict[str, Any]) -> Path:
    path = compose_path(project)
    backup = path.with_suffix(".yml.skill-agent.bak")
    shutil.copy2(path, backup)
    temp = path.with_suffix(".yml.skill-agent.tmp")
    temp.write_text(yaml.safe_dump(data, sort_keys=False))
    temp.replace(path)
    return backup


def rollback_compose(project: str, backup: Path) -> None:
    if backup.exists():
        backup.replace(compose_path(project))


def audit(skill: str, arguments: dict[str, Any], status: str, result: Any) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "skill": skill,
        "arguments": arguments,
        "status": status,
        "result": result,
    }
    with AUDIT_LOG.open("a") as file:
        file.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")


def skill_documents() -> list[dict[str, Any]]:
    documents = []
    for path in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        text = path.read_text()
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
        if not match:
            continue
        metadata = yaml.safe_load(match.group(1)) or {}
        schema_path = path.parent / "schema.json"
        documents.append(
            {
                "name": API_SKILL_NAMES.get(path.parent.name, metadata.get("name", path.parent.name)),
                "document_name": metadata.get("name", path.parent.name),
                "description": metadata.get("description", ""),
                "instructions": match.group(2).strip(),
                "schema": json.loads(schema_path.read_text()) if schema_path.exists() else {},
            }
        )
    return documents


def llm_models() -> list[str]:
    configured = os.getenv("LLM_MODELS", "")
    if configured:
        models = [item.strip() for item in configured.split(",") if item.strip()]
    else:
        model = os.getenv("LLM_MODEL", "").strip()
        models = [model] if model else []
    return list(dict.fromkeys(models))


def llm_status() -> dict[str, Any]:
    models = llm_models()
    now = time.monotonic()
    with MODEL_COOLDOWN_LOCK:
        cooldowns = {
            model: max(0, round(until - now))
            for model, until in MODEL_COOLDOWNS.items()
            if until > now
        }
    return {
        "configured": bool(
            os.getenv("LLM_API_KEY", "") and os.getenv("LLM_API_URL", "") and models
        ),
        "models": models,
        "cooldowns": cooldowns,
    }


def rate_limit_cooldown(response: requests.Response) -> int:
    retry_after = response.headers.get("Retry-After", "")
    try:
        seconds = max(1, int(float(retry_after)))
    except ValueError:
        seconds = 60

    body = response.text.lower()
    if "perday" in body or "per_day" in body or "requestsperday" in body:
        now = datetime.now(ZoneInfo("America/Los_Angeles"))
        reset = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=5, microsecond=0
        )
        seconds = max(seconds, int((reset - now).total_seconds()))
    return seconds


def help_search(query: str) -> dict[str, Any]:
    words = [word.lower() for word in re.findall(r"[\w-]+", query) if len(word) > 1]
    sources = list(DOCS_ROOT.glob("*.md")) + list(SKILLS_ROOT.glob("*/SKILL.md"))
    matches = []
    for path in sources:
        text = path.read_text()
        score = sum(text.lower().count(word) for word in words)
        if score:
            lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("---")]
            snippets = [line for line in lines if any(word in line.lower() for word in words)][:4]
            matches.append({"source": str(path.relative_to(Path("/app"))), "score": score, "snippets": snippets})
    return {"query": query, "matches": sorted(matches, key=lambda item: item["score"], reverse=True)[:5]}


def framework_list() -> dict[str, Any]:
    return {"frameworks": preset_catalog()}


def normalize_entity_name(value: str) -> str:
    return re.sub(r"[\s_.-]+", "", value).casefold()


def entity_resolve(
    entity: str,
    query: str,
    project: str | None = None,
) -> dict[str, Any]:
    query = str(query).strip()
    if not query:
        raise SkillError("query is required")
    if entity == "project":
        choices = [item["name"] for item in project_list()["projects"]]
    elif entity == "service":
        if not project:
            raise SkillError("project is required when resolving a service")
        choices = sorted(load_compose(project)["services"])
    elif entity == "framework":
        choices = [item["id"] for item in preset_catalog()]
    else:
        raise SkillError(f"Unsupported entity type: {entity}")

    if query in choices:
        return {
            "entity": entity,
            "query": query,
            "status": "exact",
            "match": query,
            "candidates": [],
            "source": "live CLI catalog",
        }

    normalized_query = normalize_entity_name(query)
    scored = []
    for choice in choices:
        normalized_choice = normalize_entity_name(choice)
        score = SequenceMatcher(None, normalized_query, normalized_choice).ratio()
        if normalized_query == normalized_choice:
            score = 1.0
        if score >= 0.68:
            scored.append(
                {
                    "value": choice,
                    "score": round(score, 3),
                    "reason": (
                        "대소문자·공백·하이픈·언더바 차이"
                        if normalized_query == normalized_choice
                        else "이름 철자가 유사함"
                    ),
                }
            )
    scored.sort(key=lambda item: (-item["score"], item["value"]))
    if not scored:
        status = "none"
    elif (
        scored[0]["score"] >= 0.78
        and (len(scored) == 1 or scored[0]["score"] - scored[1]["score"] >= 0.12)
    ):
        status = "single"
    else:
        status = "multiple"
    return {
        "entity": entity,
        "query": query,
        "status": status,
        "match": scored[0]["value"] if status == "single" else None,
        "candidates": scored[:5],
        "source": "live CLI catalog",
    }


def field_contract(field: str, *, required: bool, label: str | None = None) -> dict[str, Any]:
    return cli_contracts.field_contract(
        field,
        required=required,
        port_start=PORT_START,
        port_end=PORT_END,
        label=label,
    )


def command_contract(skill: str) -> dict[str, Any]:
    document = next((item for item in skill_documents() if item["name"] == skill), None)
    schema = document.get("schema", {}) if document else {}
    read_only = skill in READ_ONLY_SKILLS
    return cli_contracts.build_command_contract(
        skill,
        document=document,
        schema=schema,
        read_only=read_only,
        port_start=PORT_START,
        port_end=PORT_END,
    )


def command_contracts() -> dict[str, Any]:
    skills = [item["name"] for item in skill_documents()]
    contracts = [command_contract(skill) for skill in sorted(skills)]
    return cli_contracts.build_command_contracts(contracts)


def command_catalog() -> dict[str, Any]:
    skills = sorted(item["name"] for item in skill_documents())
    contracts = [command_contract(skill) for skill in skills]
    return cli_contracts.build_command_catalog(skills, contracts)


def server_health() -> dict[str, Any]:
    client = docker_client()
    containers = client.containers.list(all=True)
    restarting = [container.name for container in containers if container.status == "restarting"]
    unhealthy = []
    for container in containers:
        health = (container.attrs.get("State", {}).get("Health") or {}).get("Status")
        if health == "unhealthy":
            unhealthy.append(container.name)
    disk = shutil.disk_usage(PROJECTS_ROOT)
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk_accounted = disk.used + disk.free
    disk_percent = round((disk.used / disk_accounted) * 100, 1) if disk_accounted else 0
    performance_warnings = []
    if disk_percent >= 90:
        performance_warnings.append("disk_low")
    if swap.percent >= 20:
        performance_warnings.append("swap_active")
    container_details = []
    for container in sorted(containers, key=lambda item: item.name):
        state = container.attrs.get("State", {})
        health = (state.get("Health") or {}).get("Status")
        ports = []
        for container_port, bindings in (
            container.attrs.get("NetworkSettings", {}).get("Ports", {}) or {}
        ).items():
            for binding in bindings or []:
                ports.append(
                    {
                        "host": binding.get("HostPort"),
                        "container": container_port,
                    }
                )
        container_details.append(
            {
                "name": container.name,
                "status": container.status,
                "health": health,
                "ports": ports,
            }
        )
    return {
        "docker": client.ping(),
        "containers": len(containers),
        "running": sum(container.status == "running" for container in containers),
        "restarting": restarting,
        "unhealthy": unhealthy,
        "container_details": container_details,
        "projects": project_list(),
        "disk_percent": disk_percent,
        "disk_free_mb": round(disk.free / 1024 / 1024, 1),
        "memory_percent": memory.percent,
        "swap_used_mb": round(swap.used / 1024 / 1024, 1),
        "swap_percent": swap.percent,
        "performance_warnings": performance_warnings,
    }


def project_list() -> dict[str, Any]:
    projects = []
    incomplete = []
    for path in sorted(PROJECTS_ROOT.iterdir() if PROJECTS_ROOT.exists() else []):
        if path.is_dir() and (path / "docker-compose.yml").exists():
            data = yaml.safe_load((path / "docker-compose.yml").read_text()) or {}
            services = [
                name
                for name, config in (data.get("services", {}) or {}).items()
                if name != "agent"
                and "cloud.platform.role=agent" not in (config.get("labels") or [])
            ]
            projects.append({"name": path.name, "services": sorted(services)})
        elif path.is_dir():
            incomplete.append(
                {
                    "name": path.name,
                    "reason": "docker-compose.yml is missing",
                }
            )
    return {"projects": projects, "incomplete_projects": incomplete}


def project_summaries(project: str | None = None) -> dict[str, Any]:
    catalog = project_list()
    projects = [
        item
        for item in catalog["projects"]
        if project is None or str(item.get("name")) == project
    ]
    return {
        "projects": [project_summary(str(item["name"]), item) for item in projects],
        "incomplete_projects": [
            item
            for item in catalog["incomplete_projects"]
            if project is None or str(item.get("name")) == project
        ],
    }


def project_summary(project: str, catalog_item: dict[str, Any]) -> dict[str, Any]:
    metadata_by_service = load_service_metadata(project)
    try:
        compose = load_compose(project)
        compose_services = compose.get("services", {}) or {}
    except Exception as exc:
        return {
            **catalog_item,
            "service_summaries": [],
            "frameworks": [],
            "running_count": 0,
            "service_count": len(catalog_item.get("services") or []),
            "attention_count": len(catalog_item.get("services") or []),
            "memory_total_mb": 0,
            "public_urls": [],
            "runtime_error": str(exc),
        }

    service_names = sorted(catalog_item.get("services") or [])
    service_summaries = []
    frameworks: list[str] = []
    public_urls = []
    running_count = 0
    attention_count = 0
    memory_total_mb = 0.0
    last_deployed_at: str | None = None

    for service in service_names:
        config = compose_services.get(service, {}) or {}
        labels = labels_as_dict(config.get("labels"))
        metadata = metadata_by_service.get(service, {})
        runtime_error = None
        container_data = None
        try:
            container = find_container(project, service)
            container_data = container_summary(container) if container else None
        except Exception as exc:
            runtime_error = str(exc)

        status = str((container_data or {}).get("status") or "unknown")
        health = (container_data or {}).get("health")
        if status == "running":
            running_count += 1
        if status != "running" or health == "unhealthy" or runtime_error:
            attention_count += 1

        memory = (container_data or {}).get("memory") or {}
        memory_mb = memory.get("usage_mb") if isinstance(memory, dict) else None
        if isinstance(memory_mb, (int, float)):
            memory_total_mb += float(memory_mb)

        framework = (
            metadata.get("framework")
            or labels.get("cloud.platform.framework")
            or infer_framework_from_source(project, service, config)
        )
        if framework and framework not in frameworks:
            frameworks.append(str(framework))

        deployed_at = (
            metadata.get("last_deployed_at")
            or metadata.get("deployed_at")
            or labels.get("cloud.platform.deployed_at")
        )
        if deployed_at and (last_deployed_at is None or str(deployed_at) > last_deployed_at):
            last_deployed_at = str(deployed_at)

        configured_ports = config.get("ports", []) or []
        verified_port = first_verified_port(container_data)
        configured_host_port = next(
            (
                port
                for port in (parse_published_port(value) for value in configured_ports)
                if port is not None
            ),
            metadata.get("host_port"),
        )
        configured_container_port = next(
            (
                port
                for port in (parse_target_port(value) for value in configured_ports)
                if port is not None
            ),
            metadata.get("container_port"),
        )
        host_port = (
            verified_port["host"]
            if verified_port
            else configured_host_port
        )
        container_port = (
            verified_port["container"]
            if verified_port
            else configured_container_port
        )
        frontend = (
            bool(metadata["frontend"])
            if "frontend" in metadata
            else label_truthy(labels, "is_web_service")
        )
        if frontend and host_port:
            public_urls.append({"service": service, "host_port": host_port})

        repo_url = metadata.get("repo_url") or labels.get("cloud.platform.repo_url")
        service_summaries.append(
            {
                "name": service,
                "service": service,
                "framework": framework,
                "framework_label": (
                    FRAMEWORK_PRESETS.get(str(framework), {}).get("label")
                    if framework
                    else None
                ),
                "repo_url": repo_url,
                "frontend": frontend,
                "configured_ports": configured_ports,
                "host_port": host_port,
                "container_port": container_port,
                "last_deployed_at": deployed_at,
                "status": status,
                "health": health,
                "memory_mb": memory_mb,
                "memory_limit_mb": memory.get("limit_mb") if isinstance(memory, dict) else None,
                "memory_percent": memory.get("percent") if isinstance(memory, dict) else None,
                "runtime_error": runtime_error,
            }
        )

    return {
        **catalog_item,
        "service_summaries": service_summaries,
        "frameworks": frameworks,
        "running_count": running_count,
        "service_count": len(service_names),
        "attention_count": attention_count,
        "memory_total_mb": round(memory_total_mb, 1),
        "public_urls": public_urls,
        "last_deployed_at": last_deployed_at,
    }


def missing_input(
    skill: str,
    fields: list[tuple[str, str]],
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    missing = [
        field_contract(field, required=True, label=label)
        for field, label in fields
        if arguments.get(field) in (None, "")
    ]
    if not missing:
        return None
    labels = ", ".join(item["label"] for item in missing)
    next_question = missing[0].get("question") or f"{missing[0]['label']} 값을 알려주세요."
    return {
        "dry_run": True,
        "status": "needs_input",
        "needs_input": missing,
        "missing": missing,
        "next_question": next_question,
        "requires_approval": False,
        "command": command_contract(skill),
        "message": f"`{skill}` 작업을 위해 다음 정보가 필요합니다: {labels}.",
    }


def project_create(project: str | None, dry_run: bool) -> dict[str, Any]:
    arguments = {"project": project}
    incomplete = missing_input(
        "project.create",
        [("project", "새 프로젝트 이름(영문·숫자·점·밑줄·하이픈)")],
        arguments,
    )
    if incomplete:
        projects = project_list()["projects"]
        incomplete["available_projects"] = projects
        if projects:
            incomplete["project_guidance"] = (
                "현재 프로젝트와 서비스: "
                + "; ".join(
                    f"{item['name']}({', '.join(item['services']) or '서비스 없음'})"
                    for item in projects
                )
            )
        return incomplete

    project = validate_name(str(project), "project")
    destination = PROJECTS_ROOT / project
    compose = destination / "docker-compose.yml"
    repairing = destination.is_dir() and not compose.exists()
    if destination.exists() and not repairing:
        raise SkillError(f"Project already exists: {project}")
    plan = {
        "project": project,
        "path": str(destination),
        "operation": "repair" if repairing else "create",
        "namespace": {
            "app_network": project_network_name(project, "app"),
            "control_network": project_network_name(project, "control"),
            "agent_template_version": project_agent_template_version(),
            "model": (
                "services join app-net only; the project agent joins control-net "
                "and control-plane, never app-net; platform-api joins control-net"
            ),
        },
        "steps": [
            (
                "reuse the existing incomplete project directory"
                if repairing
                else "create the managed project directory"
            ),
            "create a docker-compose.yml with project-scoped app/control networks",
            "verify the project appears in the managed project list",
        ],
    }
    if dry_run:
        return {"dry_run": True, **plan}

    try:
        if not repairing:
            destination.mkdir(parents=False)
        networks = ensure_project_networks(project, attach_platform_api=True)
        token, token_created = ensure_namespace_token(project)
        compose.write_text(
            yaml.safe_dump(
                {
                    "version": "3.8",
                    "services": {
                        "agent": project_agent_service_definition(project, token),
                    },
                    **project_compose_scaffold(project, networks),
                },
                sort_keys=False,
            )
        )
        compose_command(project, "up", "-d", "agent", timeout=300)
        projects = {item["name"] for item in project_list()["projects"]}
        if project not in projects:
            raise SkillError("Created project was not found during verification")
        trigger_safe_docker_cleanup("project.create")
        return {
            "dry_run": False,
            **plan,
            "namespace_token_created": token_created,
            "verified": True,
        }
    except Exception:
        if compose.exists():
            compose.unlink()
        if destination.exists() and not repairing:
            shutil.rmtree(destination)
        raise


def service_status(project: str, service: str | None = None) -> dict[str, Any]:
    data = load_compose(project)
    metadata_by_service = load_service_metadata(project)
    if service:
        names = [service]
    else:
        names = sorted(
            name
            for name, config in (data.get("services", {}) or {}).items()
            if name != "agent"
            and "cloud.platform.role=agent" not in (config.get("labels") or [])
        )
    result = []
    for name in names:
        config = service_config(project, name)
        labels = labels_as_dict(config.get("labels"))
        metadata = metadata_by_service.get(name, {})
        frontend = (
            bool(metadata["frontend"])
            if "frontend" in metadata
            else label_truthy(labels, "is_web_service")
        )
        container = find_container(project, name)
        result.append(
            {
                "service": name,
                "configured_ports": config.get("ports", []),
                "frontend": frontend,
                "framework": metadata.get("framework") or labels.get("cloud.platform.framework"),
                "repo_url": metadata.get("repo_url") or labels.get("cloud.platform.repo_url"),
                "last_deployed_at": metadata.get("last_deployed_at") or metadata.get("deployed_at"),
                "container": container_summary(container) if container else None,
            }
        )
    return {"project": project, "services": result}


def service_logs(project: str, service: str, lines: int) -> dict[str, Any]:
    container = find_container(project, service)
    if container is None:
        raise SkillError(f"Container not found: {project}/{service}")
    lines = min(max(lines, 1), 100)
    return {
        "project": project,
        "service": service,
        "lines": lines,
        "logs": container.logs(tail=lines).decode(errors="replace"),
    }


def service_control(project: str, service: str, action: str, dry_run: bool) -> dict[str, Any]:
    service_config(project, service)
    if action not in {"start", "stop", "restart"}:
        raise SkillError(f"Unsupported action: {action}")
    if dry_run:
        return {
            "dry_run": True,
            "action": action,
            "target": f"{project}/{service}",
            "verification": "container state and restart count",
        }

    container = find_container(project, service)
    if action == "stop":
        if container:
            container.stop(timeout=20)
            container.reload()
            if container.status == "running":
                raise SkillError("Container did not stop")
        return service_status(project, service)

    if container is None:
        compose_command(project, "up", "-d", "--no-build", service)
    elif action == "start" and container.status != "running":
        container.start()
    elif action == "restart":
        container.restart(timeout=20)
    return {"dry_run": False, "verified": wait_stable(project, service)}


def service_deploy(
    project: str | None,
    service: str | None,
    repo_url: str | None,
    container_port: int | None,
    host_port: int | None,
    is_web: bool,
    framework: str | None,
    environment_names: list[str] | None,
    dry_run: bool,
) -> dict[str, Any]:
    arguments = {
        "project": project,
        "service": service,
        "repo_url": repo_url,
        "framework": framework,
    }
    incomplete = missing_input(
        "service.deploy",
        [
            ("project", "기존 프로젝트 이름"),
            ("service", "새 서비스 이름"),
            ("repo_url", "공개 GitHub HTTPS 저장소 URL"),
            ("framework", "프레임워크 프리셋"),
        ],
        arguments,
    )
    if incomplete:
        projects = [item["name"] for item in project_list()["projects"]]
        incomplete["available_projects"] = projects
        if not project:
            if projects:
                incomplete["project_guidance"] = (
                    "서비스는 기존 프로젝트 안에 배포됩니다. "
                    f"현재 프로젝트: {', '.join(projects)}. 이 중 하나를 알려주세요. "
                    "새 프로젝트가 필요하면 먼저 프로젝트 생성을 요청할 수 있습니다."
                )
            else:
                incomplete["project_guidance"] = (
                    "현재 관리 중인 프로젝트가 없습니다. 서비스를 배포하려면 먼저 "
                    "`신규 프로젝트를 만들어줘`라고 요청해 프로젝트를 생성해야 합니다."
                )
        incomplete["optional"] = [
            "호스트 포트(생략 시 9000~9100에서 자동 선택)",
            "웹 서비스 여부(생략 시 웹 서비스)",
            "환경변수 이름 목록(실제 값은 대시보드 보안 입력에서 설정)",
        ]
        incomplete["frameworks"] = [
            {"id": key, "label": value["label"]}
            for key, value in FRAMEWORK_PRESETS.items()
        ]
        return incomplete

    project = str(project)
    service = str(service)
    repo_url = str(repo_url)
    framework = validate_framework(str(framework))
    container_port = (
        int(container_port)
        if container_port is not None
        else DEFAULT_CONTAINER_PORT
    )
    environment_names = []
    for raw_name in environment_names or []:
        name = str(raw_name).strip()
        if not name:
            continue
        if not ENV_NAME_PATTERN.fullmatch(name):
            raise SkillError(
                f"환경변수 이름 형식이 올바르지 않습니다: {name}",
                code="environment_name_invalid",
                field="environment_names",
                hint="환경변수 이름은 영문자 또는 밑줄로 시작하고, 영문자·숫자·밑줄만 사용할 수 있습니다. 예: API_KEY",
            )
        if name not in environment_names:
            environment_names.append(name)
    environment_names.sort()
    validate_name(service, "service")
    if not dry_run:
        ensure_project_agent(project, dry_run=False)
    data = load_compose(project)
    networks = ensure_project_networks(project, attach_platform_api=True)
    data.setdefault("networks", {})
    data["networks"]["app-net"] = {
        "name": networks["app_network"],
        "external": True,
    }
    data["networks"]["control-net"] = {
        "name": networks["control_network"],
        "external": True,
    }
    if service in data["services"]:
        raise SkillError(
            f"이미 존재하는 서비스 이름입니다: {service}",
            code="service_already_exists",
            field="service",
            hint="같은 프로젝트 안에서는 서비스 이름이 중복될 수 없습니다. 다른 서비스 이름을 입력하세요.",
        )
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise invalid_repo_url_error()
    validate_github_repository_access(repo_url)
    if not 1 <= container_port <= 65535:
        raise SkillError(
            "컨테이너 포트 범위가 올바르지 않습니다.",
            code="container_port_invalid",
            field="container_port",
            hint="컨테이너 포트는 1~65535 사이 숫자여야 합니다. 일반 웹 프론트는 보통 3000을 사용합니다.",
        )

    if is_web:
        selected_host_port = host_port if host_port is not None else next_port()
        if not PORT_START <= selected_host_port <= PORT_END:
            raise SkillError(
                "호스트 포트 범위가 올바르지 않습니다.",
                code="host_port_invalid_range",
                field="host_port",
                hint=f"호스트 포트는 {PORT_START}~{PORT_END} 사이 숫자여야 합니다. 비워두면 자동 선택됩니다.",
            )
        owners = reserved_ports().get(selected_host_port, [])
        if owners:
            raise SkillError(
                f"이미 사용 중인 호스트 포트입니다: {selected_host_port}",
                code="host_port_already_used",
                field="host_port",
                hint="다른 포트를 입력하거나 비워두면 사용 가능한 포트를 자동 선택합니다.",
                detail=", ".join(owners),
            )
    else:
        if host_port is not None:
            raise SkillError(
                "내부 서비스에는 호스트 포트를 지정할 수 없습니다.",
                code="host_port_not_allowed_for_internal_service",
                field="host_port",
                hint="외부 공개가 필요한 웹 서비스일 때만 호스트 포트를 사용합니다. 내부 서비스는 포트를 비워두세요.",
            )
        selected_host_port = None

    destination = project_path(project) / service
    if destination.exists():
        raise SkillError(
            f"서비스 디렉터리가 이미 존재합니다: {service}",
            code="service_directory_already_exists",
            field="service",
            hint="기존 서비스라면 재배포를 사용하고, 새 서비스라면 다른 이름을 입력하세요.",
        )

    plan = {
        "project": project,
        "service": service,
        "repo_url": repo_url,
        "host_port": selected_host_port,
        "container_port": container_port,
        "is_web": is_web,
        "framework": framework,
        "dockerfile": (
            "use repository Dockerfile"
            if framework == "existing"
            else f"generate {FRAMEWORK_PRESETS[framework]['label']} preset"
        ),
        "environment_names": environment_names,
        "suggested_environment_names": FRAMEWORK_PRESETS[framework]["environment"],
        "environment_note": (
            "Only variable names are planned. Configure values in the dashboard; "
            "secret values are never sent to the LLM."
        ),
        "framework_manual": framework_manual(framework),
        "steps": [
            "clone the public GitHub repository",
            (
                "use the repository root Dockerfile"
                if framework == "existing"
                else "generate the selected framework Dockerfile in the server clone"
            ),
            "add the service to the project app-net namespace",
            "build and start only the new service",
            (
                "verify the container stays running and publishes the requested port"
                if is_web
                else "verify the internal-only container stays running on the app network"
            ),
        ],
    }
    if dry_run:
        return {"dry_run": True, **plan}

    backup = compose_path(project).with_suffix(".yml.skill-agent.deploy.bak")
    shutil.copy2(compose_path(project), backup)
    try:
        git_clone(repo_url, destination)
        if framework == "existing" and not (destination / "Dockerfile").is_file():
            raise SkillError("Repository root does not contain a Dockerfile")
        if framework != "existing":
            (destination / "Dockerfile").write_text(render_dockerfile(framework))

        labels = [
            f"cloud.platform.project={project}",
            f"cloud.platform.service={service}",
            f"cloud.platform.framework={framework}",
            f"cloud.platform.repo_url={repo_url}",
        ]
        if is_web:
            labels.append("is_web_service=true")
        network_aliases = [service]
        normalized_service = re.sub(r"[^A-Za-z0-9]", "", service)
        if normalized_service and normalized_service != service:
            network_aliases.append(normalized_service)
        if service.lower() in {"demo-b", "demob", "api", "server"} or "back" in service.lower():
            network_aliases.append("backend")
        network_aliases = list(dict.fromkeys(network_aliases))
        service_definition: dict[str, Any] = {
            "build": {"context": f"./{service}"},
            "restart": "always",
            "mem_limit": "1g",
            "memswap_limit": "3g",
            "networks": {"app-net": {"aliases": network_aliases}},
            "labels": labels,
        }
        if is_web:
            service_definition["ports"] = [f"{selected_host_port}:{container_port}"]
        else:
            service_definition["expose"] = [str(container_port)]
        if environment_names:
            service_definition["environment"] = {
                name: "" for name in environment_names
            }
        data["services"][service] = service_definition
        temp = compose_path(project).with_suffix(".yml.skill-agent.tmp")
        temp.write_text(yaml.safe_dump(data, sort_keys=False))
        temp.replace(compose_path(project))

        compose_command(project, "up", "-d", "--build", service, timeout=900)
        verified = wait_stable(project, service)
        if is_web:
            expected = {"host": selected_host_port, "container": container_port}
            if expected not in verified["ports"]:
                raise SkillError(f"Port verification failed: expected {expected}, got {verified['ports']}")
        elif verified["ports"]:
            raise SkillError(f"Internal-only service unexpectedly published ports: {verified['ports']}")
        metadata = record_service_deploy_metadata(
            project,
            service,
            framework=framework,
            repo_url=repo_url,
            is_web=is_web,
            verified=verified,
        )
        backup.unlink(missing_ok=True)
        trigger_safe_docker_cleanup("service.deploy")
        return {"dry_run": False, **plan, "verified": verified, "metadata": metadata}
    except Exception:
        try:
            compose_command(project, "rm", "-s", "-f", service)
        except Exception:
            pass
        if backup.exists():
            backup.replace(compose_path(project))
        if destination.exists():
            shutil.rmtree(destination)
        raise


def normalized_github_remote(repo_url: str) -> str:
    if GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        return repo_url
    match = re.fullmatch(
        r"git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+(?:\.git)?)",
        repo_url,
    )
    if match:
        return f"https://github.com/{match.group(1)}/{match.group(2)}"
    raise SkillError("Existing service remote must be a GitHub repository")


def service_redeploy(
    project: str | None,
    service: str | None,
    dry_run: bool,
) -> dict[str, Any]:
    arguments = {"project": project, "service": service}
    incomplete = missing_input(
        "service.redeploy",
        [
            ("project", "기존 프로젝트 이름"),
            ("service", "재배포할 서비스 이름"),
        ],
        arguments,
    )
    if incomplete:
        projects = project_list()["projects"]
        incomplete["available_projects"] = projects
        if projects:
            incomplete["project_guidance"] = (
                "현재 프로젝트와 서비스: "
                + "; ".join(
                    f"{item['name']}({', '.join(item['services']) or '서비스 없음'})"
                    for item in projects
                )
            )
        return incomplete

    project = str(project)
    service = str(service)
    config = service_config(project, service)
    labels = labels_as_dict(config.get("labels"))
    current_metadata = load_service_metadata(project).get(service, {})
    framework = (
        current_metadata.get("framework")
        or labels.get("cloud.platform.framework")
        or "existing"
    )
    is_web = (
        bool(current_metadata["frontend"])
        if "frontend" in current_metadata
        else label_truthy(labels, "is_web_service")
    )
    source = project_path(project) / service
    if not (source / ".git").is_dir():
        raise SkillError(f"Service source is not a Git checkout: {project}/{service}")
    remote_result = subprocess.run(
        ["git", "-C", str(source), "remote", "get-url", "origin"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    repo_url = normalized_github_remote(remote_result.stdout.strip())
    plan = {
        "project": project,
        "service": service,
        "repo_url": repo_url,
        "steps": [
            "clone the latest default branch into a temporary directory",
            "validate the new root-level Dockerfile",
            "atomically swap the service source directory",
            "build a new image and force-recreate only the target service",
            "verify the new container stays running",
            "restore the previous source and container if verification fails",
        ],
    }
    if dry_run:
        return {"dry_run": True, **plan}

    root = project_path(project)
    fresh = root / f".{service}.skill-agent.fresh"
    backup = root / f".{service}.skill-agent.backup"
    if fresh.exists() or backup.exists():
        raise SkillError("A previous redeploy workspace still exists")

    try:
        git_clone(repo_url, fresh)
        if not (fresh / "Dockerfile").is_file():
            raise SkillError("Latest repository root does not contain a Dockerfile")
        source.rename(backup)
        fresh.rename(source)
        compose_command(
            project,
            "up",
            "-d",
            "--build",
            "--force-recreate",
            service,
            timeout=900,
        )
        verified = wait_stable(project, service)
        metadata = record_service_deploy_metadata(
            project,
            service,
            framework=str(framework) if framework else None,
            repo_url=repo_url,
            is_web=is_web,
            verified=verified,
        )
        shutil.rmtree(backup)
        trigger_safe_docker_cleanup("service.redeploy")
        return {"dry_run": False, **plan, "verified": verified, "metadata": metadata}
    except Exception:
        if fresh.exists():
            shutil.rmtree(fresh)
        if backup.exists():
            if source.exists():
                shutil.rmtree(source)
            backup.rename(source)
            try:
                compose_command(project, "up", "-d", "--no-build", service)
            except Exception:
                pass
        raise


def port_manage(
    project: str,
    service: str | None,
    operation: str,
    host_port: int | None,
    container_port: int | None,
    dry_run: bool,
) -> dict[str, Any]:
    if operation == "suggest":
        return {"suggested_host_port": next_port()}
    if service is None:
        raise SkillError("service is required")

    config = service_config(project, service)
    current_ports = config.get("ports", [])
    if not current_ports:
        raise SkillError(f"Service has no published port: {project}/{service}")
    current_host = parse_published_port(current_ports[0])
    current_target = parse_target_port(current_ports[0])

    if operation == "change_host":
        if host_port is None or not PORT_START <= host_port <= PORT_END:
            raise SkillError(
                "호스트 포트 범위가 올바르지 않습니다.",
                code="host_port_invalid_range",
                field="host_port",
                hint=f"호스트 포트는 {PORT_START}~{PORT_END} 사이 숫자여야 합니다.",
            )
        owners = reserved_ports((project, service)).get(host_port, [])
        if owners:
            raise SkillError(
                f"이미 사용 중인 호스트 포트입니다: {host_port}",
                code="host_port_already_used",
                field="host_port",
                hint="다른 포트를 입력하세요.",
                detail=", ".join(owners),
            )
        new_host, new_target = host_port, current_target
    elif operation == "change_container":
        if container_port is None or not 1 <= container_port <= 65535:
            raise SkillError(
                "컨테이너 포트 범위가 올바르지 않습니다.",
                code="container_port_invalid",
                field="container_port",
                hint="컨테이너 포트는 1~65535 사이 숫자여야 합니다.",
            )
        new_host, new_target = current_host, container_port
    else:
        raise SkillError(f"Unsupported operation: {operation}")

    plan = {
        "project": project,
        "service": service,
        "operation": operation,
        "before": current_ports[0],
        "after": f"{new_host}:{new_target}",
        "warning": (
            "Changing the container mapping does not change the application listener."
            if operation == "change_container"
            else None
        ),
    }
    if dry_run:
        return {"dry_run": True, **plan}

    data = load_compose(project)
    data["services"][service]["ports"][0] = plan["after"]
    backup = write_compose_atomic(project, data)
    try:
        compose_command(project, "up", "-d", "--no-build", service)
        verified = wait_stable(project, service)
        expected = {"host": new_host, "container": new_target}
        if expected not in verified["ports"]:
            raise SkillError(f"Port verification failed: expected {expected}, got {verified['ports']}")
        backup.unlink(missing_ok=True)
        return {"dry_run": False, **plan, "verified": verified}
    except Exception:
        rollback_compose(project, backup)
        compose_command(project, "up", "-d", "--no-build", service)
        raise


def qa_run() -> dict[str, Any]:
    health = server_health()
    duplicates = {port: owners for port, owners in reserved_ports().items() if len(owners) > 1}
    checks = {
        "docker": health["docker"],
        "no_restarting": not health["restarting"],
        "no_unhealthy": not health["unhealthy"],
        "no_duplicate_ports": not duplicates,
        "disk_below_95_percent": health["disk_percent"] < 95,
    }
    return {"passed": all(checks.values()), "checks": checks, "details": health, "duplicate_ports": duplicates}


READ_ONLY_SKILLS = {
    "entity.resolve",
    "framework.list",
    "help.search",
    "platform.help",
    "server.health",
    "project.list",
    "repository.inspect",
    "service.status",
    "service.logs",
    "port.suggest",
    "qa.run",
}


def required_argument(arguments: dict[str, Any], field: str, skill: str) -> Any:
    """Read a required argument, or say which one is missing.

    A bare KeyError here surfaced as the single word "'service'", which told
    neither the planner nor the user anything. Named errors let the planner ask
    for the value or look it up and retry.
    """
    value = arguments.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise SkillError(
            f"{skill} requires '{field}'.",
            code="missing_field",
            field=field,
        )
    return value


def execute_skill(skill: str, arguments: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    try:
        if skill == "help.search":
            result = help_search(str(arguments.get("query", "")))
        elif skill == "entity.resolve":
            result = entity_resolve(
                str(required_argument(arguments, "entity", skill)),
                str(required_argument(arguments, "query", skill)),
                arguments.get("project"),
            )
        elif skill == "framework.list":
            result = framework_list()
        elif skill == "platform.help":
            result = command_catalog()
        elif skill == "server.health":
            result = server_health()
        elif skill == "project.list":
            result = project_list()
        elif skill == "repository.inspect":
            result = inspect_repository(required_argument(arguments, "repo_url", skill))
        elif skill == "project.create":
            result = project_create(arguments.get("project"), dry_run)
        elif skill == "project.ensure_agent":
            result = ensure_project_agent(required_argument(arguments, "project", skill), dry_run)
        elif skill == "service.deploy":
            result = service_deploy(
                arguments.get("project"),
                arguments.get("service"),
                arguments.get("repo_url"),
                int(required_argument(arguments, "container_port", skill)) if arguments.get("container_port") is not None else None,
                int(required_argument(arguments, "host_port", skill)) if arguments.get("host_port") is not None else None,
                bool(arguments.get("is_web", True)),
                arguments.get("framework"),
                arguments.get("environment_names"),
                dry_run,
            )
        elif skill == "service.redeploy":
            result = service_redeploy(
                arguments.get("project"),
                arguments.get("service"),
                dry_run,
            )
        elif skill == "service.status":
            result = service_status(required_argument(arguments, "project", skill), arguments.get("service"))
        elif skill == "service.logs":
            result = service_logs(required_argument(arguments, "project", skill), required_argument(arguments, "service", skill), int(arguments.get("lines", 40)))
        elif skill == "service.control":
            result = service_control(
                required_argument(arguments, "project", skill), required_argument(arguments, "service", skill), required_argument(arguments, "action", skill), dry_run
            )
        elif skill == "port.suggest":
            result = port_manage("", None, "suggest", None, None, dry_run)
        elif skill == "port.manage":
            result = port_manage(
                required_argument(arguments, "project", skill),
                arguments.get("service"),
                required_argument(arguments, "operation", skill),
                arguments.get("host_port"),
                arguments.get("container_port"),
                dry_run,
            )
        elif skill == "qa.run":
            result = qa_run()
        else:
            raise SkillError(f"Unknown skill: {skill}")
        audit(skill, arguments, "ok", result)
        return result
    except Exception as exc:
        audit(skill, arguments, "error", str(exc))
        raise


def execute_cli_skill(
    skill: str,
    arguments: dict[str, Any],
    *,
    dry_run: bool,
    approved: bool = False,
) -> dict[str, Any]:
    command = [
        "cloud-platform",
        "preview" if dry_run else "execute",
        skill,
        "--arguments",
        json.dumps(arguments, ensure_ascii=False),
    ]
    if not dry_run and approved:
        command.append("--approve")
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=1000,
    )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise SkillError(
            completed.stderr.strip() or "CLI returned malformed JSON"
        ) from exc
    if completed.returncode != 0:
        raise SkillError.from_detail(payload.get("detail", "CLI execution failed"))
    key = "preview" if dry_run else "result"
    if key not in payload:
        raise SkillError(f"CLI response is missing {key}")
    return payload[key]


def tool_description_for_llm(document: dict[str, Any]) -> str:
    """Build a compact, Claude-Code-skill-like tool description.

    The LLM should make intent decisions from this contract. The CLI/API still
    owns validation, permission checks, preview, approval, and execution.
    """
    skill = str(document.get("name", ""))
    try:
        contract = command_contract(skill)
    except Exception:
        contract = {}
    required = contract.get("required_fields") or []
    optional = contract.get("optional_fields") or []
    fields = {
        item.get("field"): {
            "type": item.get("type"),
            "rules": item.get("rules"),
            "examples": item.get("examples"),
            "semantic_hint": item.get("semantic_hint"),
            "enum": item.get("enum"),
            "default": item.get("default"),
        }
        for item in contract.get("fields", [])
        if item.get("field")
    }
    payload = {
        "skill": skill,
        "role": contract.get("role") or document.get("description", ""),
        "use_when": contract.get("use_when", []),
        "not_for": contract.get("not_for", []),
        "required_fields": required,
        "optional_fields": optional,
        "field_contracts": fields,
        "examples": contract.get("examples", []),
        "read_only": contract.get("read_only"),
        "requires_approval": contract.get("requires_approval"),
        "security": contract.get("security", []),
        "ui": contract.get("ui", {}),
        "runtime_rule": (
            "Select this tool when the latest user intent matches. "
            "If required fields are missing, omit or partially fill them; the CLI dry-run "
            "will return needs_input. Never invent values. Never copy examples or placeholders "
            "such as https://github.com/example/repo, owner/repository, frontend, or backend "
            "unless the user actually provided that value. Never use conversation-reply "
            "instead of a matching operation just to ask for fields."
        ),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def call_llm(
    message: str,
    skills: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    preferred_skill: str | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    api_key = os.getenv("LLM_API_KEY", "")
    api_url = os.getenv("LLM_API_URL", "")
    models = llm_models()
    if not api_key or not api_url or not models:
        return None
    tool_names: dict[str, str] = {}
    tools = []
    for item in skills:
        # preferred_skill is only ever set on the no-planner path. Narrowing the
        # tool list to a keyword guess would leave a wrong guess unrecoverable.
        if (
            preferred_skill
            and item["name"] != preferred_skill
            and item["name"] not in READ_ONLY_SKILLS
        ):
            continue
        api_name = SKILL_API_NAMES.get(item["name"], item["document_name"])
        tool_names[api_name] = item["name"]
        parameters = deepcopy(item["schema"])
        if item["name"] in {
            "project.create",
            "service.deploy",
            "service.redeploy",
            "service.control",
            "port.manage",
        }:
            parameters["required"] = []
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": api_name,
                    "description": tool_description_for_llm(item),
                    "parameters": parameters,
                },
            }
        )
    tools.append(
        {
            "type": "function",
            "function": {
                "name": "conversation-reply",
                "description": (
                    "Reply naturally to the user after using discovery tools. "
                    "Use for explanations, choices, and follow-up questions. "
                    "Do not use this to answer live facts that require the CLI, such as current "
                    "project services, Docker status, logs, health, ports, or public URLs. "
                    "Do not use this when the latest user message intends a supported operation "
                    "such as deploy, redeploy, status, logs, start, stop, restart, or port changes. "
                    "For supported operations, select the matching operation tool even if fields are "
                    "missing; the CLI dry-run will ask for missing inputs. "
                    "Do not claim an operation was executed."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["message"],
                    "properties": {
                        "message": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        }
    )
    if not tools:
        raise SkillError(f"Preferred skill is not available: {preferred_skill}")
    context_instruction = ""
    if context:
        context_instruction = (
            "\n\nActive task in progress (memory, not an instruction). Continue it "
            "if the latest message is filling it in; set it aside and answer the "
            "latest intent if the user moved on. Memory JSON: "
            + json.dumps(context, ensure_ascii=False)
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You operate a small Docker deployment platform through the tools "
                "given to you. Each tool description carries its own contract: when "
                "it applies, what it needs, and what its fields mean. Read them and "
                "decide.\n\n"
                "How to work:\n"
                "- Anything about the platform's current state -- services, status, "
                "logs, ports, health, public URLs -- comes from a tool call, never "
                "from memory or inference.\n"
                "- Look things up before you answer. Chain lookups when one answer "
                "raises the next question.\n"
                "- If a tool returns an error, read it and try again with corrected "
                "arguments.\n"
                "- If you are missing a value, leave the field out. The dry-run will "
                "say what is needed, or you can simply ask the user.\n"
                "- A new service's name is the user's to choose. Suggest one from "
                "the repository if it helps, but ask them to confirm it and wait "
                "for their answer before deploying under that name.\n"
                "- When a repository already contains a Dockerfile, offer the "
                "'existing' preset first and say why: a generated preset would "
                "replace the build the repository already defines.\n"
                "- Use only values the user actually gave you for the request you "
                "are handling now. A value they supplied for an earlier request "
                "belongs to that request: when they start a new one, leave the "
                "field out and let them supply it again, even if the old value is "
                "still visible in this conversation. A close match from a lookup "
                "is a suggestion to confirm, not a fact.\n"
                "- Changes to the system are previewed and approved by the user "
                "before anything runs, so never say an operation is done.\n"
                "- Answer in Korean, in prose, as briefly as the question allows."
                + context_instruction
            ),
        },
    ]
    for item in (history or [])[-16:]:
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})

    def post_with_fallback() -> tuple[dict[str, Any], str]:
        attempted = []
        for model in models:
            now = time.monotonic()
            with MODEL_COOLDOWN_LOCK:
                cooldown_until = MODEL_COOLDOWNS.get(model, 0)
            if cooldown_until > now:
                continue
            attempted.append(model)
            response = requests.post(
                api_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                },
                timeout=float(os.getenv("LLM_REQUEST_TIMEOUT", "60")),
            )
            if response.status_code != 429:
                response.raise_for_status()
                return response.json()["choices"][0]["message"], model
            cooldown = rate_limit_cooldown(response)
            with MODEL_COOLDOWN_LOCK:
                MODEL_COOLDOWNS[model] = time.monotonic() + cooldown
        cooling = llm_status()["cooldowns"]
        raise SkillError(
            "All configured LLM models are rate-limited or cooling down. "
            f"Attempted: {attempted or 'none'}; cooldowns: {cooling}"
        )

    last_model = None
    for _ in range(LLM_MAX_STEPS):
        response_message, last_model = post_with_fallback()
        tool_calls = response_message.get("tool_calls") or []

        # No tool call means the planner is answering. Content can be empty on
        # some models, in which case keep looping rather than returning silence.
        if not tool_calls:
            reply = str(response_message.get("content") or "").strip()
            if reply:
                return {"kind": "answer", "message": reply, "model": last_model}
            messages.append(response_message)
            continue

        messages.append(response_message)
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            api_name = function.get("name", "")
            raw_arguments = function.get("arguments") or "{}"
            try:
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
            except json.JSONDecodeError:
                arguments = None
            if not isinstance(arguments, dict):
                arguments = {}

            if api_name == "conversation-reply":
                message_text = str(arguments.get("message", "")).strip()
                if message_text:
                    return {
                        "kind": "answer",
                        "message": message_text,
                        "model": last_model,
                    }
                observation: dict[str, Any] = {
                    "error": "EmptyReply",
                    "detail": "conversation-reply needs a non-empty message.",
                }
            else:
                skill = tool_names.get(api_name)
                if skill is None:
                    observation = {
                        "error": "UnknownTool",
                        "detail": f"No such tool: {api_name}",
                    }
                elif skill not in READ_ONLY_SKILLS:
                    # Mutations never run here. Hand the choice back so the
                    # caller can dry-run it and ask the user to approve.
                    return {
                        "skill": skill,
                        "arguments": arguments,
                        "explanation": f"Selected `{skill}` with `{last_model}`.",
                        "model": last_model,
                    }
                else:
                    try:
                        observation = execute_cli_skill(
                            skill,
                            arguments,
                            dry_run=False,
                        )
                    except Exception as exc:
                        # Errors are observations, not dead ends: the planner
                        # reads the validation message and corrects itself.
                        observation = {
                            "error": type(exc).__name__,
                            "detail": str(exc),
                        }

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", api_name),
                    "content": json.dumps(
                        observation,
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )

    raise SkillError(
        f"Planner did not reach an answer within {LLM_MAX_STEPS} steps"
    )


def call_llm_text(
    *,
    system: str,
    user: str,
) -> dict[str, Any] | None:
    api_key = os.getenv("LLM_API_KEY", "")
    api_url = os.getenv("LLM_API_URL", "")
    models = llm_models()
    if not api_key or not api_url or not models:
        return None

    attempted = []
    for model in models:
        now = time.monotonic()
        with MODEL_COOLDOWN_LOCK:
            cooldown_until = MODEL_COOLDOWNS.get(model, 0)
        if cooldown_until > now:
            continue
        attempted.append(model)
        response = requests.post(
            api_url.rstrip("/") + "/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=float(os.getenv("LLM_RESPONSE_TIMEOUT", os.getenv("LLM_REQUEST_TIMEOUT", "60"))),
        )
        if response.status_code == 429:
            cooldown = rate_limit_cooldown(response)
            with MODEL_COOLDOWN_LOCK:
                MODEL_COOLDOWNS[model] = time.monotonic() + cooldown
            continue
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]
        return {
            "message": str(message.get("content", "")).strip(),
            "model": model,
        }
    cooling = llm_status()["cooldowns"]
    raise SkillError(
        "All configured LLM models are rate-limited or cooling down. "
        f"Attempted: {attempted or 'none'}; cooldowns: {cooling}"
    )


def fallback_plan(message: str) -> dict[str, Any]:
    lowered = message.lower()
    project_match = re.search(r"(?:project|프로젝트)\s*[:=]?\s*([a-zA-Z0-9_.-]+)", message)
    service_match = re.search(r"(?:service|서비스)\s*[:=]?\s*([a-zA-Z0-9_.-]+)", message)
    known_projects = project_list()["projects"]
    project = project_match.group(1) if project_match else None
    if project is None:
        project = next((item["name"] for item in known_projects if item["name"].lower() in lowered), None)
    service = service_match.group(1) if service_match else None
    if project and service is None:
        services = next((item["services"] for item in known_projects if item["name"] == project), [])
        service = next((item for item in services if item.lower() in lowered), None)

    port_match = re.search(r"\b(9\d{3})\b", message)
    if ("포트" in message or "port" in lowered) and ("추천" in message or "suggest" in lowered):
        return {"skill": "port.suggest", "arguments": {}, "explanation": "Find the next available port."}
    if ("포트" in message or "port" in lowered) and port_match and project and service:
        return {
            "skill": "port.manage",
            "arguments": {
                "project": project,
                "service": service,
                "operation": "change_host",
                "host_port": int(port_match.group(1)),
            },
            "explanation": "Change the published host port.",
        }
    if ("로그" in message or "log" in lowered) and project and service:
        return {"skill": "service.logs", "arguments": {"project": project, "service": service, "lines": 40}, "explanation": "Read recent logs."}
    for keyword, action in (("재시작", "restart"), ("restart", "restart"), ("중지", "stop"), ("stop", "stop"), ("시작", "start"), ("start", "start")):
        if keyword in lowered and project and service:
            return {"skill": "service.control", "arguments": {"project": project, "service": service, "action": action}, "explanation": f"{action.title()} the service."}
    if ("상태" in message or "status" in lowered) and project:
        arguments = {"project": project}
        if service:
            arguments["service"] = service
        return {"skill": "service.status", "arguments": arguments, "explanation": "Inspect service status."}
    if "qa" in lowered or "점검" in message or "검사" in message:
        return {"skill": "qa.run", "arguments": {}, "explanation": "Run compact deterministic checks."}
    if "프로젝트" in message or "project" in lowered:
        return {"skill": "project.list", "arguments": {}, "explanation": "List projects and services."}
    return {"skill": "help.search", "arguments": {"query": message}, "explanation": "Search deployment help."}
