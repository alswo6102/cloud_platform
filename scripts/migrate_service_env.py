"""Move Compose `environment` blocks into per-service env files.

Run inside the skill agent container, where runtime's helpers and /srv/projects
are both available:

    docker exec cloud-platform-skill-agent python /app/scripts/migrate_service_env.py --apply

Without --apply it only reports what it would do.

The `agent` service is never touched. Its environment is written by the
platform on every deploy (tokens, the control-plane URL, the template version)
and moving it would both break that and put real credentials in a file the
console can edit.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/app")

import yaml  # noqa: E402

from runtime import (  # noqa: E402
    PROJECTS_ROOT,
    compose_env_file_ref,
    compose_path,
    load_env_meta,
    load_service_env,
    looks_secret,
    save_env_meta,
    save_service_env,
)


def migrate(project: str, apply: bool) -> list[str]:
    path = compose_path(project)
    data = yaml.safe_load(path.read_text()) or {}
    services = data.get("services")
    if not isinstance(services, dict):
        return []

    notes: list[str] = []
    changed = False
    for service, config in services.items():
        if service == "agent" or not isinstance(config, dict):
            continue
        environment = config.get("environment")
        names: list[str] = []
        values: dict[str, str] = {}
        if isinstance(environment, dict):
            for name, value in environment.items():
                names.append(str(name))
                values[str(name)] = "" if value is None else str(value)
        elif isinstance(environment, list):
            for item in environment:
                name, _, value = str(item).partition("=")
                names.append(name)
                values[name] = value

        has_env_file = bool(config.get("env_file"))
        if not names and has_env_file:
            continue
        if not names and not has_env_file:
            notes.append(f"{project}/{service}: 환경변수 없음 → env_file만 연결")
        else:
            filled = [name for name in names if values.get(name)]
            notes.append(
                f"{project}/{service}: {len(names)}개 이동"
                + (f" (값 있음 {len(filled)})" if filled else " (모두 빈 값)")
            )

        if not apply:
            continue

        stored = load_service_env(project, service)
        for name, value in values.items():
            stored.setdefault(name, value)
        save_service_env(project, service, stored)

        meta = load_env_meta(project, service)
        for name in stored:
            if name not in meta:
                meta[name] = {"secret": looks_secret(name), "updated_at": None}
        save_env_meta(project, service, meta)

        config.pop("environment", None)
        config["env_file"] = [compose_env_file_ref(service)]
        changed = True

    if apply and changed:
        backup = path.with_suffix(".yml.pre-env-migration")
        if not backup.exists():
            backup.write_text(path.read_text())
        temporary = path.with_suffix(".yml.migrate.tmp")
        temporary.write_text(yaml.safe_dump(data, sort_keys=False))
        temporary.replace(path)
        notes.append(f"{project}: compose 갱신 (백업 {backup.name})")
    return notes


def main() -> int:
    apply = "--apply" in sys.argv
    projects = sorted(
        item.name
        for item in PROJECTS_ROOT.iterdir()
        if item.is_dir() and (item / "docker-compose.yml").exists()
    )
    print("적용" if apply else "미리보기 (--apply 없이 실행)")
    for project in projects:
        for note in migrate(project, apply):
            print(" ", note)
    if not apply:
        print("\n실제로 반영하려면 --apply 를 붙여 다시 실행하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
