from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from runtime import READ_ONLY_SKILLS, execute_skill, project_list, skill_documents


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
    commands.add_parser("skills", help="List allowlisted skills and schemas")
    commands.add_parser("projects", help="List managed projects and services")

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
        if args.command == "skills":
            emit({"skills": skill_documents()})
            return 0
        if args.command == "projects":
            emit(project_list())
            return 0

        arguments = load_arguments(args.arguments, args.arguments_file)
        if args.command == "preview":
            if args.skill in READ_ONLY_SKILLS:
                raise ValueError("Read-only skills do not require preview")
            emit(
                {
                    "skill": args.skill,
                    "preview": execute_skill(args.skill, arguments, dry_run=True),
                }
            )
            return 0

        if args.skill not in READ_ONLY_SKILLS and not args.approve:
            raise ValueError("Mutation skills require --approve")
        emit(
            {
                "skill": args.skill,
                "result": execute_skill(args.skill, arguments, dry_run=False),
            }
        )
        return 0
    except Exception as exc:
        emit({"error": type(exc).__name__, "detail": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
