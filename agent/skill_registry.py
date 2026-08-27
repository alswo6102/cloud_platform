"""What skills exist, and what each one is allowed to do.

A skill declares its own permissions in its SKILL.md front matter:

    access: read | mutate     -- may it change anything
    plane:  root | project | shared

Those two lines used to be four hand-kept sets in two modules. Adding a skill
meant remembering all of them, and forgetting one produced a skill that ran
without the check nobody noticed was missing.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml

SKILLS_ROOT = Path(os.getenv("SKILLS_ROOT", "/app/skills"))

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

# Kept off the tool list and out of the catalog: the platform calls it while
# creating or repairing a project, never the planner.
UNDOCUMENTED_SKILLS = {
    "project.ensure_agent": {"access": "mutate", "plane": "root"},
}

ACCESS_VALUES = {"read", "mutate"}
PLANE_VALUES = {"root", "project", "shared"}

_DOCUMENT_CACHE: list[dict[str, Any]] | None = None
_CACHE_LOCK = threading.Lock()


def skill_documents() -> list[dict[str, Any]]:
    global _DOCUMENT_CACHE
    with _CACHE_LOCK:
        if _DOCUMENT_CACHE is not None:
            return _DOCUMENT_CACHE
    documents = []
    for path in sorted(SKILLS_ROOT.glob("*/SKILL.md")):
        text = path.read_text()
        match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
        if not match:
            continue
        metadata = yaml.safe_load(match.group(1)) or {}
        folder = path.parent.name
        name = API_SKILL_NAMES.get(folder, metadata.get("name", folder))
        access = str(metadata.get("access", "")).strip().lower()
        plane = str(metadata.get("plane", "")).strip().lower()
        if access not in ACCESS_VALUES or plane not in PLANE_VALUES:
            raise ValueError(
                f"{path} must declare access ({'|'.join(sorted(ACCESS_VALUES))}) "
                f"and plane ({'|'.join(sorted(PLANE_VALUES))})"
            )
        schema_path = path.parent / "schema.json"
        documents.append(
            {
                "name": name,
                "document_name": metadata.get("name", folder),
                "description": metadata.get("description", ""),
                "access": access,
                "plane": plane,
                "instructions": match.group(2).strip(),
                "schema": json.loads(schema_path.read_text()) if schema_path.exists() else {},
            }
        )
    with _CACHE_LOCK:
        _DOCUMENT_CACHE = documents
    return documents


def skill_permissions() -> dict[str, dict[str, str]]:
    permissions = dict(UNDOCUMENTED_SKILLS)
    for document in skill_documents():
        permissions[document["name"]] = {
            "access": document["access"],
            "plane": document["plane"],
        }
    return permissions


def _named(access: str | None = None, plane: str | None = None) -> frozenset[str]:
    return frozenset(
        name
        for name, rules in skill_permissions().items()
        if (access is None or rules["access"] == access)
        and (plane is None or rules["plane"] == plane)
    )


def read_only_skills() -> frozenset[str]:
    """Skills that change nothing, so they need no approval."""
    return _named(access="read")


def root_only_skills() -> frozenset[str]:
    """Skills a namespace token may not reach at all."""
    return _named(plane="root")


def project_scoped_skills() -> frozenset[str]:
    """Skills whose project argument is fixed to the caller's namespace."""
    return _named(plane="project")
