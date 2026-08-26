"""Who is calling, and what they are allowed to touch.

One place decides it. Every path that runs a skill goes through
namespace_scoped_arguments on the way in and namespace_scoped_result on the
way out, so a skill added later cannot quietly skip the check.
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request

PROJECT_SCOPED_HIDDEN_SKILLS = {
    "project.create",
    "project.ensure_agent",
    "server.health",
    "qa.run",
}

def namespace_tokens() -> dict[str, str]:
    tokens: dict[str, str] = {}
    store = Path(
        os.getenv("NAMESPACE_TOKEN_STORE", "/var/log/skill-agent/namespace_tokens.json")
    )
    try:
        data = json.loads(store.read_text())
        if isinstance(data, dict):
            tokens.update({str(token): str(namespace) for token, namespace in data.items()})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    raw = os.getenv("PLATFORM_NAMESPACE_TOKENS", "").strip()
    if not raw:
        return tokens
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail="Invalid PLATFORM_NAMESPACE_TOKENS JSON",
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=500,
            detail="PLATFORM_NAMESPACE_TOKENS must be a JSON object",
        )
    tokens.update({str(token): str(namespace) for token, namespace in data.items()})
    return tokens

def bearer_token(http_request: Request) -> str:
    header = http_request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token is required")
    return header.removeprefix("Bearer ").strip()

def authenticated_namespace(http_request: Request) -> str | None:
    # A process with PLATFORM_API configured is a project agent. It holds only
    # its own namespace token and reaches the control plane through the CLI, so
    # namespace scoping is enforced there rather than here. What this process
    # must still do is refuse callers other than the web layer: otherwise any
    # peer that can reach it makes this agent act with its own namespace token.
    if os.getenv("PLATFORM_API"):
        expected = os.getenv("AGENT_INBOUND_TOKEN", "").strip()
        if not expected:
            raise HTTPException(
                status_code=500,
                detail="AGENT_INBOUND_TOKEN is not configured for this project agent",
            )
        if not hmac.compare_digest(bearer_token(http_request), expected):
            raise HTTPException(status_code=401, detail="Unauthorized caller")
        return None

    # Control plane. Refuse to run wide open: a missing root token used to mean
    # "no enforcement", which silently disabled every namespace check below.
    root_token = os.getenv("PLATFORM_ROOT_TOKEN", "").strip()
    if not root_token:
        raise HTTPException(
            status_code=500,
            detail="PLATFORM_ROOT_TOKEN is not configured on the control plane",
        )
    token = bearer_token(http_request)
    if hmac.compare_digest(token, root_token):
        return None
    namespace = namespace_tokens().get(token)
    if not namespace:
        raise HTTPException(status_code=403, detail="Invalid namespace token")
    return namespace

def namespace_scoped_arguments(
    skill: str,
    arguments: dict[str, Any],
    namespace: str | None,
) -> dict[str, Any]:
    if not namespace:
        return arguments
    scoped = dict(arguments)
    if skill in {
        "service.deploy",
        "service.redeploy",
        "service.status",
        "service.logs",
        "service.control",
        "port.manage",
    }:
        requested = scoped.get("project")
        if requested and str(requested) != namespace:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Namespace token can only access project {namespace!r}; "
                    f"requested {requested!r}"
                ),
            )
        scoped["project"] = namespace
    if skill == "entity.resolve" and scoped.get("entity") == "service":
        requested = scoped.get("project")
        if requested and str(requested) != namespace:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Namespace token can only resolve services in {namespace!r}; "
                    f"requested {requested!r}"
                ),
            )
        scoped["project"] = namespace
    if skill in {"project.create", "project.ensure_agent", "server.health", "qa.run"}:
        raise HTTPException(
            status_code=403,
            detail=f"{skill} is only available to the root/admin plane",
        )
    return scoped

def namespace_scoped_result(
    skill: str,
    result: dict[str, Any],
    namespace: str | None,
) -> dict[str, Any]:
    if not namespace or skill != "project.list":
        return result
    projects = [
        item
        for item in result.get("projects", [])
        if str(item.get("name")) == namespace
    ]
    incomplete = [
        item
        for item in result.get("incomplete_projects", [])
        if str(item.get("name")) == namespace
    ]
    return {"projects": projects, "incomplete_projects": incomplete}
