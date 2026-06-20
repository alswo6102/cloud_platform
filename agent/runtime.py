from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
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

PROJECTS_ROOT = Path(os.getenv("PROJECTS_ROOT", "/srv/projects"))
SKILLS_ROOT = Path(os.getenv("SKILLS_ROOT", "/app/skills"))
DOCS_ROOT = Path(os.getenv("DOCS_ROOT", "/app/docs"))
AUDIT_LOG = Path(os.getenv("AUDIT_LOG", "/var/log/skill-agent/audit.jsonl"))
PORT_START = int(os.getenv("PORT_START", "9000"))
PORT_END = int(os.getenv("PORT_END", "9100"))
NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}$")
API_SKILL_NAMES = {
    "help-search": "help.search",
    "server-health": "server.health",
    "project-list": "project.list",
    "service-deploy": "service.deploy",
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


class SkillError(RuntimeError):
    pass


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
    return {
        "docker": client.ping(),
        "containers": len(containers),
        "running": sum(container.status == "running" for container in containers),
        "restarting": restarting,
        "unhealthy": unhealthy,
        "disk_percent": round((disk.used / disk.total) * 100, 1),
        "memory_percent": psutil.virtual_memory().percent,
    }


def project_list() -> dict[str, Any]:
    projects = []
    for path in sorted(PROJECTS_ROOT.iterdir() if PROJECTS_ROOT.exists() else []):
        if path.is_dir() and (path / "docker-compose.yml").exists():
            data = yaml.safe_load((path / "docker-compose.yml").read_text()) or {}
            projects.append({"name": path.name, "services": sorted(data.get("services", {}).keys())})
    return {"projects": projects}


def service_status(project: str, service: str | None = None) -> dict[str, Any]:
    data = load_compose(project)
    names = [service] if service else sorted(data["services"])
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
    project: str,
    service: str,
    repo_url: str,
    container_port: int,
    host_port: int | None,
    is_web: bool,
    dry_run: bool,
) -> dict[str, Any]:
    validate_name(service, "service")
    data = load_compose(project)
    if service in data["services"]:
        raise SkillError(f"Service already exists: {project}/{service}")
    if not GITHUB_HTTPS_PATTERN.fullmatch(repo_url):
        raise SkillError("repo_url must be a public GitHub HTTPS repository URL")
    if not 1 <= container_port <= 65535:
        raise SkillError("container_port must be between 1 and 65535")

    selected_host_port = host_port if host_port is not None else next_port()
    if not PORT_START <= selected_host_port <= PORT_END:
        raise SkillError(f"host_port must be between {PORT_START} and {PORT_END}")
    owners = reserved_ports().get(selected_host_port, [])
    if owners:
        raise SkillError(f"Port {selected_host_port} is already used by {', '.join(owners)}")

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
        "steps": [
            "clone the public GitHub repository",
            "require a Dockerfile at the repository root",
            "add the service to docker-compose.yml",
            "build and start only the new service",
            "verify the container stays running and publishes the requested port",
        ],
    }
    if dry_run:
        return {"dry_run": True, **plan}

    backup = compose_path(project).with_suffix(".yml.skill-agent.deploy.bak")
    shutil.copy2(compose_path(project), backup)
    try:
        git_clone(repo_url, destination)
        if not (destination / "Dockerfile").is_file():
            raise SkillError("Repository root does not contain a Dockerfile")

        service_definition: dict[str, Any] = {
            "build": {"context": f"./{service}"},
            "restart": "always",
            "ports": [f"{selected_host_port}:{container_port}"],
            "mem_limit": "1g",
            "memswap_limit": "3g",
        }
        if is_web:
            service_definition["labels"] = ["is_web_service=true"]
        data["services"][service] = service_definition
        temp = compose_path(project).with_suffix(".yml.skill-agent.tmp")
        temp.write_text(yaml.safe_dump(data, sort_keys=False))
        temp.replace(compose_path(project))

        compose_command(project, "up", "-d", "--build", service, timeout=900)
        verified = wait_stable(project, service)
        expected = {"host": selected_host_port, "container": container_port}
        if expected not in verified["ports"]:
            raise SkillError(f"Port verification failed: expected {expected}, got {verified['ports']}")
        backup.unlink(missing_ok=True)
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
    "help.search",
    "server.health",
    "project.list",
    "service.status",
    "service.logs",
    "port.suggest",
    "qa.run",
}


def execute_skill(skill: str, arguments: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    try:
        if skill == "help.search":
            result = help_search(str(arguments.get("query", "")))
        elif skill == "server.health":
            result = server_health()
        elif skill == "project.list":
            result = project_list()
        elif skill == "service.deploy":
            result = service_deploy(
                arguments["project"],
                arguments["service"],
                arguments["repo_url"],
                int(arguments["container_port"]),
                int(arguments["host_port"]) if arguments.get("host_port") is not None else None,
                bool(arguments.get("is_web", True)),
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


def call_llm(message: str, skills: list[dict[str, Any]]) -> dict[str, Any] | None:
    api_key = os.getenv("LLM_API_KEY", "")
    api_url = os.getenv("LLM_API_URL", "")
    models = llm_models()
    if not api_key or not api_url or not models:
        return None
    tool_names: dict[str, str] = {}
    tools = []
    for item in skills:
        api_name = SKILL_API_NAMES.get(item["name"], item["document_name"])
        tool_names[api_name] = item["name"]
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": api_name,
                    "description": f"{item['description']} {item['instructions']}",
                    "parameters": item["schema"],
                },
            }
        )
    request_body = {
        "temperature": 0,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Select exactly one provided function for this Docker deployment request. "
                    "Never invent projects, services, repository URLs, paths, commands, or function names. "
                    "Use only arguments explicitly present in the user request. "
                    "Do not answer with JSON or prose; call one function."
                ),
            },
            {"role": "user", "content": message},
        ],
        "tools": tools,
        "tool_choice": "required",
    }

    attempted = []
    response = None
    selected_model = None
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
            json={"model": model, **request_body},
            timeout=30,
        )
        if response.status_code != 429:
            response.raise_for_status()
            selected_model = model
            break

        cooldown = rate_limit_cooldown(response)
        with MODEL_COOLDOWN_LOCK:
            MODEL_COOLDOWNS[model] = time.monotonic() + cooldown

    if response is None or selected_model is None:
        cooling = llm_status()["cooldowns"]
        raise SkillError(
            "All configured LLM models are rate-limited or cooling down. "
            f"Attempted: {attempted or 'none'}; cooldowns: {cooling}"
        )

    response_message = response.json()["choices"][0]["message"]
    tool_calls = response_message.get("tool_calls") or []
    if len(tool_calls) != 1:
        raise SkillError(f"Planner must select exactly one skill; received {len(tool_calls)}")
    function = tool_calls[0].get("function") or {}
    api_name = function.get("name", "")
    skill = tool_names.get(api_name)
    if skill is None:
        raise SkillError(f"Planner selected unknown skill: {api_name}")
    raw_arguments = function.get("arguments") or "{}"
    arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    if not isinstance(arguments, dict):
        raise SkillError("Planner arguments must be an object")
    return {
        "skill": skill,
        "arguments": arguments,
        "explanation": f"Selected `{skill}` with `{selected_model}`.",
        "model": selected_model,
    }


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
