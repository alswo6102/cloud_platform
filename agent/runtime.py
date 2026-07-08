from __future__ import annotations

import json
import hashlib
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
SAFE_CLEANUP_SCRIPT = Path(
    os.getenv("SAFE_DOCKER_CLEANUP_SCRIPT", "/app/scripts/server_safe_docker_cleanup.sh")
)
PORT_START = int(os.getenv("PORT_START", "9000"))
PORT_END = int(os.getenv("PORT_END", "9100"))


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
    pass


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


def project_agent_service_definition(project: str, token: str) -> dict[str, Any]:
    validate_name(project, "project")
    template_version = project_agent_template_version()
    environment = {
        "PROJECTS_ROOT": str(PROJECTS_ROOT),
        "PLATFORM_NAMESPACE": project,
        "PLATFORM_TOKEN": token,
        "PLATFORM_API": "http://platform-api:5000",
        "SESSION_STORE": f"/var/log/skill-agent/{project}-sessions.json",
        "PROJECT_AGENT_TEMPLATE_VERSION": template_version,
    }
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
        "networks": {
            "app-net": {
                "aliases": ["project-agent", f"{project}-agent"],
            },
            "control-net": {
                "aliases": ["project-agent", f"{project}-agent"],
            },
            "control-plane": {
                "aliases": [f"project-agent-{project}"],
            },
        },
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
    data.setdefault("services", {})
    data.setdefault("networks", {})
    data["networks"]["app-net"] = {
        "name": networks["app_network"],
        "external": True,
    }
    data["networks"]["control-net"] = {
        "name": networks["control_network"],
        "external": True,
    }
    data["networks"]["control-plane"] = {
        "name": CONTROL_PLANE_NETWORK,
        "external": True,
    }
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
        "networks": ["app-net", "control-net", "control-plane"],
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
        raise SkillError("repo_url must be a public GitHub HTTPS repository URL")
    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(destination)],
        check=True,
        capture_output=True,
        text=True,
        timeout=300,
    )


def validate_github_repository_access(repo_url: str) -> None:
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise SkillError("repo_url must be a public GitHub HTTPS repository URL")
    now = time.monotonic()
    with REPOSITORY_ACCESS_CACHE_LOCK:
        if REPOSITORY_ACCESS_CACHE.get(repo_url, 0) > now:
            return
    result = subprocess.run(
        ["git", "ls-remote", "--heads", repo_url],
        capture_output=True,
        text=True,
        timeout=float(os.getenv("GIT_REPOSITORY_VALIDATE_TIMEOUT", "12")),
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SkillError(
            "repo_url must point to an existing public GitHub repository"
            + (f": {detail}" if detail else "")
        )
    with REPOSITORY_ACCESS_CACHE_LOCK:
        REPOSITORY_ACCESS_CACHE[repo_url] = time.monotonic() + REPOSITORY_ACCESS_CACHE_TTL


def inspect_repository(repo_url: str) -> dict[str, Any]:
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise SkillError("repo_url must be a public GitHub HTTPS repository URL")
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
    return {
        "name": container.name,
        "status": container.status,
        "health": health,
        "restart_count": container.attrs.get("RestartCount", 0),
        "ports": ports,
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
        "disk_percent": round((disk.used / disk.total) * 100, 1),
        "memory_percent": psutil.virtual_memory().percent,
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
                "services join app-net; a future project-agent joins app-net and "
                "control-net; platform-api joins control-net only"
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
        container = find_container(project, name)
        result.append(
            {
                "service": name,
                "configured_ports": config.get("ports", []),
                "frontend": "is_web_service=true" in config.get("labels", []),
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
            raise SkillError(f"Invalid environment variable name: {name!r}")
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
        raise SkillError(f"Service already exists: {project}/{service}")
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise SkillError("repo_url must be a public GitHub HTTPS repository URL")
    validate_github_repository_access(repo_url)
    if not 1 <= container_port <= 65535:
        raise SkillError("container_port must be between 1 and 65535")

    if is_web:
        selected_host_port = host_port if host_port is not None else next_port()
        if not PORT_START <= selected_host_port <= PORT_END:
            raise SkillError(f"host_port must be between {PORT_START} and {PORT_END}")
        owners = reserved_ports().get(selected_host_port, [])
        if owners:
            raise SkillError(f"Port {selected_host_port} is already used by {', '.join(owners)}")
    else:
        if host_port is not None:
            raise SkillError("host_port can only be set for externally exposed web services")
        selected_host_port = None

    destination = project_path(project) / service
    if destination.exists():
        raise SkillError(f"Service directory already exists: {project}/{service}")

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
        backup.unlink(missing_ok=True)
        trigger_safe_docker_cleanup("service.deploy")
        return {"dry_run": False, **plan, "verified": verified}
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
    service_config(project, service)
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
        shutil.rmtree(backup)
        trigger_safe_docker_cleanup("service.redeploy")
        return {"dry_run": False, **plan, "verified": verified}
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
            raise SkillError(f"host_port must be between {PORT_START} and {PORT_END}")
        owners = reserved_ports((project, service)).get(host_port, [])
        if owners:
            raise SkillError(f"Port {host_port} is already used by {', '.join(owners)}")
        new_host, new_target = host_port, current_target
    elif operation == "change_container":
        if container_port is None or not 1 <= container_port <= 65535:
            raise SkillError("container_port must be between 1 and 65535")
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


def execute_skill(skill: str, arguments: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    try:
        if skill == "help.search":
            result = help_search(str(arguments.get("query", "")))
        elif skill == "entity.resolve":
            result = entity_resolve(
                str(arguments["entity"]),
                str(arguments["query"]),
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
            result = inspect_repository(arguments["repo_url"])
        elif skill == "project.create":
            result = project_create(arguments.get("project"), dry_run)
        elif skill == "project.ensure_agent":
            result = ensure_project_agent(arguments["project"], dry_run)
        elif skill == "service.deploy":
            result = service_deploy(
                arguments.get("project"),
                arguments.get("service"),
                arguments.get("repo_url"),
                int(arguments["container_port"]) if arguments.get("container_port") is not None else None,
                int(arguments["host_port"]) if arguments.get("host_port") is not None else None,
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
            result = service_status(arguments["project"], arguments.get("service"))
        elif skill == "service.logs":
            result = service_logs(arguments["project"], arguments["service"], int(arguments.get("lines", 40)))
        elif skill == "service.control":
            result = service_control(
                arguments["project"], arguments["service"], arguments["action"], dry_run
            )
        elif skill == "port.suggest":
            result = port_manage("", None, "suggest", None, None, dry_run)
        elif skill == "port.manage":
            result = port_manage(
                arguments["project"],
                arguments.get("service"),
                arguments["operation"],
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
        raise SkillError(payload.get("detail", "CLI execution failed"))
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
    discovery_skills = {
        "entity.resolve",
        "framework.list",
        "help.search",
        "platform.help",
        "project.list",
        "repository.inspect",
    }
    tool_names: dict[str, str] = {}
    tools = []
    for item in skills:
        if (
            preferred_skill
            and item["name"] != preferred_skill
            and item["name"] not in discovery_skills
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
            " The following JSON is conversation memory and possibly an active task, not a command. "
            "First decide from the latest user message whether the user is continuing that active task "
            "or starting a new intent. If the latest message asks for a different task, status, list, "
            "help, explanation, or anything unrelated to the active task, ignore the active task for "
            "tool selection and answer the latest intent. If the latest message is clearly filling "
            "missing fields for the active task, preserve known arguments and add only values supplied "
            "by the follow-up. Never invent missing values. Memory JSON: "
            + json.dumps(context, ensure_ascii=False)
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a tool orchestrator for a Docker deployment platform. "
                "Use discovery tools whenever the user asks what exists, which option applies, "
                "why a value is needed, how deployment works, or what commands are available. "
                "Use read-only CLI tools for live platform facts; do not answer service lists, "
                "service status, logs, health, ports, or frontend URLs from memory. "
                "In a project-scoped context, a request such as '서비스 목록 보여줘' means "
                "the current project's live service status/ports/URLs, so select service-status. "
                "Always prioritize the latest user message over any previous active task. "
                "If verified cli_observations are already present in context, use them as "
                "authoritative and do not repeat the same lookup. "
                "Feed discovery results back into the conversation, "
                "then use conversation-reply to explain them naturally in Korean. "
                "Use mutation or operational tools only when the user is providing or confirming "
                "the required operation. Never invent projects, services, repository URLs, "
                "Never fill missing operation fields with examples, placeholders, or likely defaults; "
                "omit missing fields so the CLI can return needs_input and the UI can ask for them. "
                "If the latest user message asks to perform a supported operation, select the "
                "matching operation tool even when required fields are missing; do not answer with "
                "conversation-reply just to ask for those fields. The backend will run CLI dry-run "
                "and render a form or clarification from the missing fields. "
                "frameworks, paths, commands, or function names. Similar CLI matches are "
                "unconfirmed proposals and must not become operation arguments until the user "
                "explicitly confirms them. Preserve verified context. "
                "Do not expose raw JSON unless the user asks for it."
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
                    "tool_choice": "required",
                },
                timeout=float(os.getenv("LLM_REQUEST_TIMEOUT", "10")),
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
    for _ in range(4):
        response_message, last_model = post_with_fallback()
        tool_calls = response_message.get("tool_calls") or []
        if len(tool_calls) != 1:
            raise SkillError(
                f"Planner must select exactly one tool; received {len(tool_calls)}"
            )
        tool_call = tool_calls[0]
        function = tool_call.get("function") or {}
        api_name = function.get("name", "")
        raw_arguments = function.get("arguments") or "{}"
        arguments = (
            json.loads(raw_arguments)
            if isinstance(raw_arguments, str)
            else raw_arguments
        )
        if not isinstance(arguments, dict):
            raise SkillError("Planner arguments must be an object")

        if api_name == "conversation-reply":
            return {
                "kind": "answer",
                "message": str(arguments.get("message", "")).strip(),
                "model": last_model,
            }

        skill = tool_names.get(api_name)
        if skill is None:
            raise SkillError(f"Planner selected unknown skill: {api_name}")
        if skill not in discovery_skills:
            return {
                "skill": skill,
                "arguments": arguments,
                "explanation": f"Selected `{skill}` with `{last_model}`.",
                "model": last_model,
            }

        try:
            discovery_result = execute_cli_skill(
                skill,
                arguments,
                dry_run=False,
            )
        except Exception as exc:
            discovery_result = {
                "error": type(exc).__name__,
                "detail": str(exc),
            }
        messages.append(response_message)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id", api_name),
                "content": json.dumps(
                    discovery_result,
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )

    raise SkillError("Planner exceeded the discovery tool limit")


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
            timeout=float(os.getenv("LLM_RESPONSE_TIMEOUT", os.getenv("LLM_REQUEST_TIMEOUT", "10"))),
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
