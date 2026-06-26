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
    command_catalog,
    execute_skill,
    entity_resolve,
    inspect_repository,
    project_list,
    service_logs,
    service_status,
    skill_documents,
)


def platform_api_url() -> str:
    return os.getenv("PLATFORM_API", "").rstrip("/")


def platform_api_headers() -> dict[str, str]:
    token = os.getenv("PLATFORM_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


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
        raise RuntimeError(str(detail))
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


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cloud-platform",
        description="Strict CLI adapter for the allowlisted skill runtime.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("help", help="Show the machine-readable command catalog")
    commands.add_parser("skills", help="List allowlisted skills and schemas")
    commands.add_parser("projects", help="List managed projects and services")
    commands.add_parser("frameworks", help="List framework deployment presets")
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
    status_parser.add_argument("project")
    status_parser.add_argument("service", nargs="?")
    logs_parser = commands.add_parser(
        "logs",
        help="Show a bounded tail of logs for a Compose service",
    )
    logs_parser.add_argument("project")
    logs_parser.add_argument("service")
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
            emit(call_platform_api("/help", method="GET") if remote else command_catalog())
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
            emit(
                execute_via_platform_api(
                    "service.status",
                    {"project": args.project, "service": args.service},
                    dry_run=False,
                )
                if remote
                else service_status(args.project, args.service)
            )
            return 0
        if args.command == "logs":
            emit(
                execute_via_platform_api(
                    "service.logs",
                    {
                        "project": args.project,
                        "service": args.service,
                        "lines": args.lines,
                    },
                    dry_run=False,
                )
                if remote
                else service_logs(args.project, args.service, args.lines)
            )
            return 0
        arguments = load_arguments(args.arguments, args.arguments_file)
        if args.command == "preview":
            if args.skill in READ_ONLY_SKILLS:
                raise ValueError("Read-only skills do not require preview")
            emit(
                {
                    "skill": args.skill,
                    "preview": (
                        execute_via_platform_api(
                            args.skill,
                            arguments,
                            dry_run=True,
                        )
                        if remote
                        else execute_skill(args.skill, arguments, dry_run=True)
                    ),
                }
            )
            return 0

        if args.skill not in READ_ONLY_SKILLS and not args.approve:
            raise ValueError("Mutation skills require --approve")
        emit(
            {
                "skill": args.skill,
                "result": (
                    execute_via_platform_api(
                        args.skill,
                        arguments,
                        dry_run=False,
                        approved=args.approve,
                    )
                    if remote
                    else execute_skill(args.skill, arguments, dry_run=False)
                ),
            }
        )
        return 0
    except Exception as exc:
        emit({"error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
