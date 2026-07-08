from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

from deployment_presets import preset_catalog
from runtime import (
    READ_ONLY_SKILLS,
    command_contract,
    command_contracts,
    command_catalog,
    execute_skill,
    entity_resolve,
    inspect_repository,
    project_list,
    service_logs,
    service_status,
    skill_documents,
)


class PlatformApiError(RuntimeError):
    def __init__(self, detail: Any) -> None:
        super().__init__(str(detail))
        self.detail = detail


def platform_api_url() -> str:
    return os.getenv("PLATFORM_API", "").rstrip("/")


def platform_api_headers() -> dict[str, str]:
    token = os.getenv("PLATFORM_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def current_namespace() -> str | None:
    value = os.getenv("PLATFORM_NAMESPACE", "").strip()
    return value or None


def call_platform_api(
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    method: str = "POST",
) -> dict[str, Any]:
    base = platform_api_url()
    if not base:
        raise RuntimeError("PLATFORM_API is not configured")
    url = f"{base}{path}"
    if method == "GET":
        response = requests.get(url, headers=platform_api_headers(), timeout=120)
    else:
        response = requests.post(
            url,
            headers=platform_api_headers(),
            json=payload or {},
            timeout=120,
        )
    try:
        data = response.json()
    except ValueError:
        data = {"detail": response.text}
    if response.status_code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        raise PlatformApiError(detail)
    return data if isinstance(data, dict) else {"result": data}


def execute_via_platform_api(
    skill: str,
    arguments: dict[str, Any],
    *,
    dry_run: bool,
    approved: bool = False,
) -> dict[str, Any]:
    if dry_run:
        return call_platform_api(
            "/preview",
            {"skill": skill, "arguments": arguments},
        )["preview"]
    return call_platform_api(
        "/execute",
        {
            "skill": skill,
            "arguments": arguments,
            "approved": approved or skill in READ_ONLY_SKILLS,
        },
    )["result"]


def load_arguments(value: str | None, file_path: str | None) -> dict[str, Any]:
    if value and file_path:
        raise ValueError("Use either --arguments or --arguments-file, not both")
    if file_path:
        text = Path(file_path).read_text()
    elif value:
        text = value
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        text = "{}"
    data = json.loads(text or "{}")
    if not isinstance(data, dict):
        raise ValueError("Arguments must be a JSON object")
    return data


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def preview_envelope(skill: str, arguments: dict[str, Any], preview: dict[str, Any]) -> dict[str, Any]:
    missing = preview.get("needs_input") or preview.get("missing") or []
    if missing:
        status = "needs_input"
        requires_approval = False
        next_question = preview.get("next_question")
    else:
        status = "ready"
        requires_approval = skill not in READ_ONLY_SKILLS
        next_question = None
    return {
        "skill": skill,
        "status": status,
        "arguments": arguments,
        "missing": missing,
        "next_question": next_question,
        "requires_approval": requires_approval,
        "preview": preview,
    }


def execute_envelope(skill: str, arguments: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    return {
        "skill": skill,
        "status": "executed",
        "arguments": arguments,
        "requires_approval": False,
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cloud-platform",
        description="Strict CLI adapter for the allowlisted skill runtime.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("help", help="Show the machine-readable command catalog")
    commands.add_parser("commands", help="Show all machine-readable command contracts")
    commands.add_parser("skills", help="List allowlisted skills and schemas")
    commands.add_parser("projects", help="List managed projects and services")
    commands.add_parser("frameworks", help="List framework deployment presets")
    schema_parser = commands.add_parser(
        "schema",
        help="Show one machine-readable command contract",
    )
    schema_parser.add_argument("skill")
    resolve_parser = commands.add_parser(
        "resolve",
        help="Resolve an entity name against live platform data",
    )
    resolve_parser.add_argument("entity", choices=("project", "service", "framework"))
    resolve_parser.add_argument("query")
    resolve_parser.add_argument("--project")
    describe_parser = commands.add_parser(
        "describe",
        help="Describe one allowlisted skill",
    )
    describe_parser.add_argument("skill")
    inspect_parser = commands.add_parser(
        "inspect-repo",
        help="Inspect a public GitHub repository and return framework evidence",
    )
    inspect_parser.add_argument("repo_url")
    status_parser = commands.add_parser(
        "status",
        help="Show live Compose and Docker status for a project or service",
    )
    status_parser.add_argument("target", nargs="?")
    status_parser.add_argument("service", nargs="?")
    logs_parser = commands.add_parser(
        "logs",
        help="Show a bounded tail of logs for a Compose service",
    )
    logs_parser.add_argument("target")
    logs_parser.add_argument("service", nargs="?")
    logs_parser.add_argument("--lines", type=int, default=40)

    for command in ("preview", "execute"):
        sub = commands.add_parser(command)
        sub.add_argument("skill")
        sub.add_argument("--arguments", help="Arguments as one JSON object")
        sub.add_argument("--arguments-file", help="Path to a JSON arguments file")
        if command == "execute":
            sub.add_argument(
                "--approve",
                action="store_true",
                help="Required for mutation skills",
            )

    args = parser.parse_args()
    try:
        remote = bool(platform_api_url())
        if args.command == "help":
            emit(call_platform_api("/catalog", method="GET") if remote else command_catalog())
            return 0
        if args.command == "commands":
            emit(call_platform_api("/commands", method="GET") if remote else command_contracts())
            return 0
        if args.command == "schema":
            emit(call_platform_api(f"/schema/{args.skill}", method="GET") if remote else command_contract(args.skill))
            return 0
        if args.command == "skills":
            emit(call_platform_api("/skills", method="GET") if remote else {"skills": skill_documents()})
            return 0
        if args.command == "describe":
            skill = next(
                (
                    item
                    for item in skill_documents()
                    if item["name"] == args.skill
                ),
                None,
            )
            if skill is None:
                raise ValueError(f"Unknown skill: {args.skill}")
            emit({"skill": skill})
            return 0
        if args.command == "projects":
            emit(
                execute_via_platform_api(
                    "project.list",
                    {},
                    dry_run=False,
                )
                if remote
                else project_list()
            )
            return 0
        if args.command == "frameworks":
            emit(call_platform_api("/frameworks", method="GET") if remote else {"frameworks": preset_catalog()})
            return 0
        if args.command == "resolve":
            emit(
                execute_via_platform_api(
                    "entity.resolve",
                    {
                        "entity": args.entity,
                        "query": args.query,
                        "project": args.project,
                    },
                    dry_run=False,
                )
                if remote
                else entity_resolve(args.entity, args.query, args.project)
            )
            return 0
        if args.command == "inspect-repo":
            emit(
                execute_via_platform_api(
                    "repository.inspect",
                    {"repo_url": args.repo_url},
                    dry_run=False,
                )
                if remote
                else inspect_repository(args.repo_url)
            )
            return 0
        if args.command == "status":
            namespace = current_namespace()
            project = namespace or args.target
            service = args.target if namespace else args.service
            if not project:
                raise ValueError("Project is required outside project-scoped CLI")
            emit(
                execute_via_platform_api(
                    "service.status",
                    {"project": project, "service": service},
                    dry_run=False,
                )
                if remote
                else service_status(project, service)
            )
            return 0
        if args.command == "logs":
            namespace = current_namespace()
            project = namespace or args.target
            service = args.target if namespace else args.service
            if not service:
                raise ValueError("Service is required")
            emit(
                execute_via_platform_api(
                    "service.logs",
                    {
                        "project": project,
                        "service": service,
                        "lines": args.lines,
                    },
                    dry_run=False,
                )
                if remote
                else service_logs(project, service, args.lines)
            )
            return 0
        arguments = load_arguments(args.arguments, args.arguments_file)
        if args.command == "preview":
            if args.skill in READ_ONLY_SKILLS:
                raise ValueError("Read-only skills do not require preview")
            preview = (
                execute_via_platform_api(
                    args.skill,
                    arguments,
                    dry_run=True,
                )
                if remote
                else execute_skill(args.skill, arguments, dry_run=True)
            )
            emit(
                preview_envelope(args.skill, arguments, preview)
            )
            return 0

        if args.skill not in READ_ONLY_SKILLS and not args.approve:
            raise ValueError("Mutation skills require --approve")
        result = (
            execute_via_platform_api(
                args.skill,
                arguments,
                dry_run=False,
                approved=args.approve,
            )
            if remote
            else execute_skill(args.skill, arguments, dry_run=False)
        )
        emit(
            execute_envelope(args.skill, arguments, result)
        )
        return 0
    except Exception as exc:
        emit({
            "error": type(exc).__name__,
            "detail": exc.detail if isinstance(exc, PlatformApiError) else str(exc),
        })
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
