"""The planner: what the model is given, and how it is asked.

Kept apart from the runtime it drives. Nothing here touches Docker, Compose,
or the filesystem; it reaches the platform only through execute_cli_skill,
which applies the same validation and approval rules as every other caller.
"""
from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import requests

from skill_registry import SKILL_API_NAMES, read_only_skills
from runtime import (
    SkillError,
    command_contract,
    execute_cli_skill,
)

# Prompts are text, not code. Keep them where they can be read and edited
# without opening a Python file.
PROMPTS_ROOT = Path(
    os.getenv("PROMPTS_ROOT", str(Path(__file__).resolve().parent / "prompts"))
)

PROMPT_CACHE: dict[str, str] = {}

PROMPT_CACHE_LOCK = threading.Lock()

# How many planner turns one message may take. Read-only lookups, a correction
# after a validation error, and the final answer all come out of this budget.
LLM_MAX_STEPS = int(os.getenv("LLM_MAX_STEPS", "12"))
# How many of the planner's own lookups travel back to the console as tool
# blocks. Twelve steps of raw skill results is a payload, not evidence.
STEP_REPORT_LIMIT = int(os.getenv("LLM_STEP_REPORT_LIMIT", "6"))

MODEL_COOLDOWNS: dict[str, float] = {}

MODEL_COOLDOWN_LOCK = threading.Lock()
# A retired model stays retired; do not pay a round trip for it every turn.
DEAD_MODEL_COOLDOWN = float(os.getenv("DEAD_MODEL_COOLDOWN", "600"))

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
    }
    return json.dumps(payload, ensure_ascii=False, default=str)

def load_prompt(name: str) -> str:
    with PROMPT_CACHE_LOCK:
        cached = PROMPT_CACHE.get(name)
    if cached is not None:
        return cached
    text = (PROMPTS_ROOT / f"{name}.md").read_text(encoding="utf-8").strip()
    with PROMPT_CACHE_LOCK:
        PROMPT_CACHE[name] = text
    return text

def llm_not_configured() -> SkillError:
    return SkillError(
        "플래너가 구성되지 않았습니다.",
        code="llm_not_configured",
        hint="LLM_API_KEY, LLM_API_URL, LLM_MODELS를 설정하세요.",
    )

def llm_chat_completion(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    timeout: float | None = None,
) -> tuple[dict[str, Any], str]:
    """Send one chat completion, moving down the model list on rate limits.

    The planner loop and the response writer both used to carry their own copy
    of this. Two copies meant a timeout knob that existed on one path only, and
    a retry or a usage log would have had to be added twice.
    """
    api_key = os.getenv("LLM_API_KEY", "")
    api_url = os.getenv("LLM_API_URL", "")
    models = llm_models()
    if not api_key or not api_url or not models:
        raise llm_not_configured()
    if timeout is None:
        timeout = float(os.getenv("LLM_REQUEST_TIMEOUT", "60"))

    def cooldown_of(name: str) -> float:
        with MODEL_COOLDOWN_LOCK:
            return MODEL_COOLDOWNS.get(name, 0.0)

    # A cooldown says "prefer another model", not "never ask this one". With
    # every model cooling down there is no other model, and refusing to send
    # anything at all answered "지금은 요청을 처리하지 못했습니다" with
    # Attempted: none -- while a model whose cooldown had been computed from a
    # single Retry-After header was answering normally. Try them anyway, least
    # recently limited first.
    now = time.monotonic()
    ready = [name for name in models if cooldown_of(name) <= now]
    order = ready or sorted(models, key=cooldown_of)

    attempted: list[str] = []
    failures: list[str] = []
    for model in order:
        attempted.append(model)
        payload: dict[str, Any] = {
            "model": model,
            "temperature": 0,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            response = requests.post(
                api_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            failures.append(f"{model}: {type(exc).__name__}")
            continue
        if response.status_code == 429:
            with MODEL_COOLDOWN_LOCK:
                MODEL_COOLDOWNS[model] = time.monotonic() + rate_limit_cooldown(response)
            failures.append(f"{model}: 429")
            continue
        if response.status_code >= 400:
            # A model gets retired, renamed, or withdrawn from a key without
            # warning, and the list exists so the next one gets its turn. This
            # used to raise here: a dead model in the middle of the list killed
            # every request, while working models sat untried behind it.
            if response.status_code < 500:
                with MODEL_COOLDOWN_LOCK:
                    MODEL_COOLDOWNS[model] = time.monotonic() + DEAD_MODEL_COOLDOWN
            failures.append(f"{model}: {response.status_code}")
            continue
        try:
            message = response.json()["choices"][0]["message"]
        except (ValueError, KeyError, IndexError):
            failures.append(f"{model}: unreadable response")
            continue
        # It answered, so whatever the cooldown was based on has passed.
        with MODEL_COOLDOWN_LOCK:
            MODEL_COOLDOWNS.pop(model, None)
        return message, model

    cooling = llm_status()["cooldowns"]
    raise SkillError(
        "No configured LLM model answered. "
        f"Attempted: {attempted or 'none'}; "
        f"failures: {failures or 'none'}; cooldowns: {cooling}"
    )

def withheld_from_the_planner(skill: str, observation: Any) -> Any:
    """Strip what a read-only result carries that the model must not see.

    `service.env.list` hands values back so the console can fill its form. The
    console asks for that over its own endpoint; the planner reads the same
    skill and would put whatever came back into the prompt and the transcript,
    where it stays. Only names, whether a value is set, and when it changed are
    an answer the planner needs -- so the value is dropped here rather than
    trusting every caller to have flagged it secret.
    """
    if skill != "service.env.list" or not isinstance(observation, dict):
        return observation
    entries = observation.get("entries")
    if not isinstance(entries, list):
        return observation
    return {
        **observation,
        "entries": [
            {key: value for key, value in entry.items() if key != "value"}
            if isinstance(entry, dict)
            else entry
            for entry in entries
        ],
    }


def call_llm(
    message: str,
    skills: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    history: list[dict[str, str]] | None = None,
    execute: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Plan a turn, running read-only tools to see what is actually there.

    `execute` runs one tool. The caller supplies it because the caller is the
    one that knows who is asking: the control plane hands in an executor that
    scopes every call to the caller's namespace. Defaulting to the unscoped
    runtime is what let a project token read another project's services, so a
    caller that has a namespace must not rely on the default.
    """
    run_tool = execute or execute_cli_skill
    if not llm_status()["configured"]:
        raise llm_not_configured()
    tool_names: dict[str, str] = {}
    tools = []
    for item in skills:
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
                    "Say something to the user: an explanation, a question, or an "
                    "answer built from what the other tools returned."
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
            "content": load_prompt("planner") + context_instruction,
        },
    ]
    # Restore the previous turns exactly as they happened, tool calls and
    # results included. Storing only the prose meant the planner started every
    # turn not knowing what it had already looked up.
    for item in history or []:
        role = item.get("role")
        if role == "tool":
            messages.append(item)
        elif role == "user":
            messages.append(item)
        elif role == "assistant" and (item.get("content") or item.get("tool_calls")):
            messages.append(item)
    messages.append({"role": "user", "content": message})

    def transcript() -> list[dict[str, Any]]:
        # Everything after the system prompt, which is rebuilt each turn.
        return messages[1:]

    # The read-only skills this turn actually ran. The transcript already holds
    # them, but as opaque OpenAI tool frames mixed with every earlier turn --
    # which is why an answer built from three lookups used to arrive at the
    # console looking like the model had simply known.
    steps: list[dict[str, Any]] = []

    def with_steps(payload: dict[str, Any]) -> dict[str, Any]:
        return {**payload, "steps": steps[-STEP_REPORT_LIMIT:]} if steps else payload

    last_model = None
    for _ in range(LLM_MAX_STEPS):
        response_message, last_model = llm_chat_completion(messages, tools=tools)
        tool_calls = response_message.get("tool_calls") or []

        # No tool call means the planner is answering. Content can be empty on
        # some models, in which case keep looping rather than returning silence.
        if not tool_calls:
            messages.append(response_message)
            reply = str(response_message.get("content") or "").strip()
            if reply:
                return with_steps({
                    "kind": "answer",
                    "message": reply,
                    "model": last_model,
                    "transcript": transcript(),
                })
            continue

        messages.append(response_message)
        answered: set[str] = set()

        def call_id_of(call: dict[str, Any]) -> str:
            return str(call.get("id") or (call.get("function") or {}).get("name", ""))

        def finish(payload: dict[str, Any], note: dict[str, Any]) -> dict[str, Any]:
            # Every tool call in an assistant message needs a result, or the
            # next turn's request is rejected for referring to a call that was
            # never answered. Returning early leaves some unanswered.
            for call in tool_calls:
                identifier = call_id_of(call)
                if identifier in answered:
                    continue
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": identifier,
                        "content": json.dumps(
                            note if identifier == handled else
                            {"status": "not run; the turn ended first"},
                            ensure_ascii=False,
                            default=str,
                        ),
                    }
                )
                answered.add(identifier)
            return with_steps({**payload, "transcript": transcript()})

        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            api_name = function.get("name", "")
            handled = call_id_of(tool_call)
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
                    return finish(
                        {
                            "kind": "answer",
                            "message": message_text,
                            "model": last_model,
                        },
                        {"status": "delivered to the user"},
                    )
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
                elif skill not in read_only_skills():
                    # Mutations never run here. Hand the choice back so the
                    # caller can dry-run it and ask the user to approve.
                    return finish(
                        {
                            "skill": skill,
                            "arguments": arguments,
                            "explanation": f"Selected `{skill}` with `{last_model}`.",
                            "model": last_model,
                        },
                        {"status": "handed to the preview and approval gate"},
                    )
                else:
                    try:
                        observation = withheld_from_the_planner(
                            skill,
                            run_tool(skill, arguments, dry_run=False),
                        )
                        steps.append({
                            "skill": skill,
                            "arguments": arguments,
                            "result": observation,
                        })
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
                    "tool_call_id": handled,
                    "content": json.dumps(
                        observation,
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )
            answered.add(handled)

    raise SkillError(
        f"Planner did not reach an answer within {LLM_MAX_STEPS} steps"
    )

def call_llm_text(
    *,
    system: str,
    user: str,
) -> dict[str, Any]:
    """Write one reply. No tools, one round trip, the same transport."""
    message, model = llm_chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        timeout=float(
            os.getenv("LLM_RESPONSE_TIMEOUT", os.getenv("LLM_REQUEST_TIMEOUT", "60"))
        ),
    )
    return {
        "message": str(message.get("content", "")).strip(),
        "model": model,
    }
