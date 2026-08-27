#!/usr/bin/env python3
"""Regression checks for the defects the full-codebase review turned up.

Each check names the behaviour it protects, not the code that implements it.
Runs inside the skill-agent image with a throwaway PROJECTS_ROOT and no Docker
daemon, so it can run anywhere the image runs.

Some of the code under test lives in processes this image does not carry --
the Streamlit dashboard and the web API -- so those functions are lifted out
of their module by AST and executed against stubs, the same technique
remote_smoke_test.sh already uses for the dashboard's port allocator.
"""
import ast
import os
import re
import shutil
import subprocess
import sys
import textwrap
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agent"))

PROJECTS = Path("/tmp/cloud-platform-review-projects")
shutil.rmtree(PROJECTS, ignore_errors=True)
PROJECTS.mkdir(parents=True)
os.environ["PROJECTS_ROOT"] = str(PROJECTS)
os.environ["PLATFORM_ROOT_TOKEN"] = "review-root-token"
os.environ["SKILLS_ROOT"] = str(ROOT / "agent" / "skills")
# Both default to /var/log/skill-agent, which exists in the image and nowhere
# else. Point them at the throwaway root so the suite runs off the server too.
os.environ["SESSION_STORE"] = str(PROJECTS / "sessions.json")
os.environ["AUDIT_LOG"] = str(PROJECTS / "audit.jsonl")
os.environ.pop("PLATFORM_API", None)
os.environ.pop("PLATFORM_NAMESPACE", None)
os.environ.pop("LLM_API_KEY", None)

import app  # noqa: E402
import planner  # noqa: E402
import runtime  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label):
    def decorate(function):
        try:
            function()
            PASSED.append(label)
            print(f"OK {label}")
        except Exception as exc:  # noqa: BLE001 - report, do not stop
            FAILED.append(label)
            print(f"FAIL {label}\n    {type(exc).__name__}: {exc}")
        return function

    return decorate


def runtime_source_between(start: str, end: str) -> str:
    source = (ROOT / "agent" / "runtime.py").read_text()
    first = source.index(start)
    last = source.index(end, first) + len(end)
    return textwrap.dedent(source[first:last])


def lift(path: Path, names: set[str], namespace: dict) -> dict:
    """Execute selected top-level definitions from a module we cannot import."""
    tree = ast.parse(path.read_text())
    wanted: list[ast.stmt] = []
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            wanted.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            hit = {
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and target.id in names
            }
            if hit:
                wanted.append(node)
                found |= hit
    missing = names - found
    assert not missing, f"{path.name}에서 찾지 못함: {sorted(missing)}"
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def write_project(name: str, compose: str) -> Path:
    project = PROJECTS / name
    project.mkdir(parents=True, exist_ok=True)
    (project / "docker-compose.yml").write_text(compose)
    return project


# --- Redeploying a preset service rebuilds its Dockerfile ---------------------
# The generated Dockerfile only ever existed in the server-side clone, so a
# fresh clone never carries it. Requiring one from the repository made every
# preset-deployed service impossible to redeploy.


@check("redeploy_regenerates_preset_dockerfile")
def _redeploy_plan_names_the_preset():
    project = write_project(
        "presetqa",
        "version: '3.8'\nservices:\n  web:\n    build:\n      context: ./web\n",
    )
    source = project / "web"
    source.mkdir()
    (source / "index.html").write_text("<h1>hi</h1>")
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "remote", "add", "origin",
         "https://github.com/owner/repo"],
        check=True,
    )
    metadata = project / runtime.SERVICE_METADATA_DIR
    metadata.mkdir()
    (metadata / runtime.SERVICE_METADATA_FILE).write_text(
        '{"version": 1, "services": {"web": {"service": "web", "framework": "vite"}}}'
    )

    plan = runtime.service_redeploy("presetqa", "web", dry_run=True)
    assert plan["framework"] == "vite", plan
    assert "regenerate" in plan["dockerfile"], plan
    assert any("regenerate" in step for step in plan["steps"]), plan


@check("redeploy_keeps_repository_dockerfile_for_existing")
def _redeploy_existing_still_validates():
    project = write_project(
        "existingqa",
        "version: '3.8'\nservices:\n  web:\n    build:\n      context: ./web\n",
    )
    source = project / "web"
    source.mkdir()
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    subprocess.run(
        ["git", "-C", str(source), "remote", "add", "origin",
         "https://github.com/owner/repo"],
        check=True,
    )
    metadata = project / runtime.SERVICE_METADATA_DIR
    metadata.mkdir()
    (metadata / runtime.SERVICE_METADATA_FILE).write_text(
        '{"version": 1, "services": {"web": {"service": "web", "framework": "existing"}}}'
    )

    plan = runtime.service_redeploy("existingqa", "web", dry_run=True)
    assert plan["dockerfile"] == "use repository Dockerfile", plan


# --- A deploy keeps the environment variable names it was handed -------------


@check("deploy_keeps_environment_names")
def _environment_names_survive():
    body = runtime_source_between(
        "    requested_environment_names =",
        "    environment_names.sort()",
    )
    namespace = {
        "ENV_NAME_PATTERN": runtime.ENV_NAME_PATTERN,
        "SkillError": runtime.SkillError,
        "environment_names": ["SECRET_KEY", "DATABASE_URL", "DATABASE_URL", "  "],
    }
    exec(body, namespace)
    assert namespace["environment_names"] == ["DATABASE_URL", "SECRET_KEY"], namespace

    namespace = {
        "ENV_NAME_PATTERN": runtime.ENV_NAME_PATTERN,
        "SkillError": runtime.SkillError,
        "environment_names": ["1BAD-NAME!"],
    }
    try:
        exec(body, namespace)
    except runtime.SkillError:
        return
    raise AssertionError("잘못된 환경변수 이름이 통과했다")


# --- Chat scopes every skill call to the caller's namespace ------------------
# /execute and /preview always did. This path did not, so a namespace token
# could read another project's logs and status just by asking.


@check("chat_scopes_every_skill_call")
def _no_unscoped_call_survives_in_chat():
    tree = ast.parse((ROOT / "agent" / "app.py").read_text())
    chat = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "chat"
    )
    scoped = next(
        node
        for node in ast.walk(chat)
        if isinstance(node, ast.FunctionDef) and node.name == "scoped_execute"
    )
    unscoped = [
        node.lineno
        for node in ast.walk(chat)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "execute_cli_skill"
        and not scoped.lineno <= node.lineno <= scoped.end_lineno
    ]
    assert not unscoped, f"namespace 스코핑을 거치지 않는 호출: {unscoped}행"


@check("chat_namespace_denial_is_not_a_planner_failure")
def _http_exception_passes_through():
    tree = ast.parse((ROOT / "agent" / "app.py").read_text())
    chat = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "chat"
    )
    top_level = [
        handler
        for handler in ast.walk(chat)
        if isinstance(handler, ast.ExceptHandler) and handler.col_offset == 4
    ]
    first = min(top_level, key=lambda handler: handler.lineno)
    assert isinstance(first.type, ast.Name) and first.type.id == "HTTPException", (
        "403 거부가 502 Planner failed로 바뀐다"
    )


@check("namespace_token_cannot_reach_another_project")
def _scoping_rejects_cross_project():
    from fastapi import HTTPException

    for skill in ("service.logs", "service.status", "service.control"):
        try:
            app.namespace_scoped_arguments(
                skill, {"project": "other", "service": "web"}, "mine"
            )
        except HTTPException as exc:
            assert exc.status_code == 403, exc
            continue
        raise AssertionError(f"{skill}이 다른 프로젝트를 허용했다")

    scoped = app.namespace_scoped_arguments("service.logs", {}, "mine")
    assert scoped["project"] == "mine", scoped


# --- A new session keeps the context it was just handed ----------------------


@check("new_session_keeps_its_first_context")
def _first_turn_context_survives():
    session_id = "review-session-0001"
    app.SESSIONS.pop(session_id, None)
    handed = {
        "project_scope": "demoa",
        "public_base_url": "https://console.example",
        "arguments": {"project": "demoa"},
    }
    context, _ = app.load_session(session_id, handed)
    assert context is not None, "첫 턴에서 컨텍스트가 버려졌다"
    assert context["project_scope"] == "demoa", context
    assert app.public_base_url_from_context(context) == "https://console.example"


# --- Deterministic routing hands off instead of raising ----------------------


@check("the_rule_based_parallel_path_stays_deleted")
def _no_keyword_router_returns():
    write_project(
        "knownqa", "version: '3.8'\nservices:\n  web:\n    image: example/web\n"
    )
    # These were a second implementation of what the planner does. They were
    # only ever reachable with no LLM configured, and that mode is gone.
    gone = [
        "preferred_skill_for",
        "ambiguity_for",
        "strict_arguments",
        "explicit_arguments",
        "deterministic_read_request",
        "cli_proposal_for_input",
        "handle_proposed_input",
        "framework_context_help",
        "project_problem_response",
        "no_project_transition",
        "render_read_only_result",
        "confirmed_information",
        "FRAMEWORK_ALIASES",
        "HELP_MESSAGE",
    ]
    back = [name for name in gone if hasattr(app, name)]
    assert not back, f"룰베이스 구현이 되살아남: {back}"
    assert not hasattr(planner, "fallback_plan"), "키워드 플래너가 되살아남"
    assert not hasattr(runtime, "call_llm"), "플래너가 런타임에 다시 섞임"
    source = (ROOT / "agent" / "app.py").read_text()
    assert "LLM_API_KEY" not in source, "LLM 유무로 갈라지는 분기가 다시 생김"


@check("session_carries_the_task_and_clears_it_after_execution")
def _agent_owned_session():
    session_id = "review-session-0002"
    app.SESSIONS.pop(session_id, None)
    context = {
        "skill": "service.deploy",
        "arguments": {"project": "demoa", "service": "frontend"},
        "missing": [{"field": "repo_url"}],
    }
    app.remember_response(
        session_id,
        "demoa에 frontend 서비스 만들래",
        {"message": "저장소 URL이 필요합니다.", "context": context, "requires_approval": False},
    )
    loaded, history = app.load_session(session_id, None)
    assert loaded == context, loaded
    assert history[-2]["role"] == "user" and history[-1]["role"] == "assistant", history
    app.remember_execution(session_id, "service.deploy", None)
    loaded, history = app.load_session(session_id, None)
    assert loaded is None, loaded


@check("entity_resolution_still_answers_from_live_data")
def _entity_resolve():
    write_project(
        "demoa", "version: '3.8'\nservices:\n  web:\n    image: example/web\n"
    )
    assert runtime.entity_resolve("project", "demoa")["status"] == "exact"
    close = runtime.entity_resolve("project", "demo-a")
    assert close["status"] == "single" and close["match"] == "demoa", close
    assert runtime.entity_resolve("project", "nothing-like-this")["status"] == "none"


@check("every_preset_renders_a_dockerfile_on_port_3000")
def _framework_templates():
    from deployment_presets import FRAMEWORK_PRESETS, render_dockerfile

    for framework in FRAMEWORK_PRESETS:
        if framework == "existing":
            continue
        dockerfile = render_dockerfile(framework)
        assert "EXPOSE 3000" in dockerfile, framework


# --- The deploy form offers every preset the platform supports ---------------


@check("deploy_form_offers_every_preset")
def _form_matches_the_catalog():
    from deployment_presets import FRAMEWORK_PRESETS

    hint = app.deploy_form_hint({}, [{"field": "framework"}], {})
    assert hint["choices"]["framework"] == list(FRAMEWORK_PRESETS), hint
    assert "spring-gradle" in hint["choices"]["framework"]

    schema = next(
        item for item in runtime.skill_documents() if item["name"] == "service.deploy"
    )["schema"]
    assert set(hint["choices"]["framework"]) == set(
        schema["properties"]["framework"]["enum"]
    ), "폼 선택지와 스킬 스키마가 어긋난다"


# --- A container-port change needs a published host port --------------------


@check("container_port_change_needs_a_published_host_port")
def _no_none_port_reaches_the_compose_file():
    write_project(
        "portqa",
        "version: '3.8'\nservices:\n  web:\n    image: example/web\n    ports:\n      - \"3000\"\n",
    )
    try:
        runtime.port_manage("portqa", "web", "change_container", None, 8080, True)
    except runtime.SkillError as exc:
        assert exc.code == "host_port_not_published", exc.to_dict()
        return
    raise AssertionError('"None:8080" 매핑이 계획에 들어갔다')


# --- The dashboard never offers the project agent for deletion ---------------
# The agent has no build context, so its folder resolved to the project
# directory and deleting it removed every other service's source.


@check("dashboard_hides_the_agent_and_never_targets_the_project_root")
def _dashboard_service_list_is_safe():
    compose = {
        "services": {
            "agent": {
                "image": "cloud-platform-skill-agent:latest",
                "labels": [
                    "cloud.platform.project=demoa",
                    "cloud.platform.role=agent",
                ],
            },
            "frontend": {
                "build": {"context": "./frontend"},
                "labels": ["is_web_service=true"],
            },
            "backend": {"build": {"context": "./backend"}, "labels": []},
            "imageonly": {"image": "example/x", "labels": []},
        }
    }
    project = write_project(
        "dashqa",
        "version: '3.8'\nservices:\n  frontend:\n    build:\n      context: ./frontend\n",
    )

    class DockerUnavailable(Exception):
        pass

    def refuse():
        raise DockerUnavailable("no docker in this check")

    namespace = lift(
        ROOT / "admin.py",
        {"get_project_services"},
        {
            "Path": Path,
            "PROJECTS_ROOT": PROJECTS,
            "yaml": types.SimpleNamespace(
                safe_load=lambda handle: compose, YAMLError=Exception
            ),
            "docker": types.SimpleNamespace(
                from_env=refuse,
                errors=types.SimpleNamespace(DockerException=DockerUnavailable),
            ),
            "st": types.SimpleNamespace(error=lambda *args: None),
        },
    )
    services, _ = namespace["get_project_services"]("dashqa")

    assert "agent" not in services, "에이전트가 삭제 가능한 서비스로 노출된다"
    assert set(services) == {"frontend", "backend", "imageonly"}, services
    for name, meta in services.items():
        target = (project / meta["folder"]).resolve()
        assert target != project.resolve(), f"{name}의 삭제 대상이 프로젝트 루트다"
        assert project.resolve() in target.parents, f"{name}이 프로젝트 밖을 가리킨다"


# --- The web layer ships no default credential and no public repo URLs -------


def web_namespace(names: set[str]) -> dict:
    return lift(ROOT / "web" / "app.py", names, {"Any": object, "os": os})


@check("no_admin_account_exists_unless_one_was_configured")
def _default_store_has_no_admin():
    namespace = web_namespace({"default_auth_store"})
    os.environ.pop("PLATFORM_ADMIN_PASSWORD", None)
    store = namespace["default_auth_store"]()
    assert "admin" not in store["users"], "기본 admin 계정이 다시 생겼다"

    os.environ["PLATFORM_ADMIN_PASSWORD"] = "set-by-the-operator"
    try:
        store = namespace["default_auth_store"]()
        assert store["users"]["admin"]["password"] == "set-by-the-operator"
        assert store["users"]["admin"]["role"] == "admin"
    finally:
        os.environ.pop("PLATFORM_ADMIN_PASSWORD", None)


@check("public_catalog_hides_repository_urls_and_runtime_errors")
def _catalog_projection_is_narrow():
    namespace = web_namespace(
        {"public_project_view", "PUBLIC_PROJECT_FIELDS", "PUBLIC_SERVICE_FIELDS"}
    )
    view = namespace["public_project_view"](
        {
            "name": "demoa",
            "services": ["frontend"],
            "frameworks": ["vite"],
            "memory_total_mb": 12.0,
            "running_count": 1,
            "service_count": 1,
            "attention_count": 0,
            "last_deployed_at": "2026-08-01T00:00:00+00:00",
            "public_urls": [{"service": "frontend", "host_port": 9000}],
            "runtime_error": "Cannot connect to /var/run/docker.sock",
            "service_summaries": [
                {
                    "service": "frontend",
                    "framework": "vite",
                    "framework_label": "Vite (React/Vue/Svelte)",
                    "frontend": True,
                    "host_port": 9000,
                    "status": "running",
                    "repo_url": "https://github.com/owner/private-thing",
                    "runtime_error": "boom",
                    "configured_ports": ["9000:3000"],
                    "memory_percent": 41.2,
                }
            ],
        }
    )
    rendered = repr(view)
    assert "private-thing" not in rendered, "저장소 주소가 공개 목록으로 새어나간다"
    assert "docker.sock" not in rendered, "오류 원문이 공개 목록으로 새어나간다"
    assert view["runtime_error"] is True

    # Everything the console reads must survive the projection.
    for key in (
        "name",
        "services",
        "frameworks",
        "public_urls",
        "memory_total_mb",
        "service_count",
        "running_count",
        "attention_count",
        "last_deployed_at",
    ):
        assert key in view, f"콘솔이 쓰는 {key}가 사라졌다"
    summary = view["service_summaries"][0]
    for key in ("service", "framework", "framework_label", "frontend", "host_port", "status"):
        assert key in summary, f"콘솔이 쓰는 {key}가 사라졌다"


# --- The console offers the same presets the platform does -------------------


@check("console_framework_options_match_the_platform")
def _console_is_not_behind():
    from deployment_presets import FRAMEWORK_PRESETS

    console = (ROOT / "frontend" / "src" / "main.tsx").read_text()
    options = console[console.index("const frameworkOptions") :]
    options = options[: options.index("];")]
    listed = set(re.findall(r'\{ id: "([a-z-]+)"', options))
    missing = set(FRAMEWORK_PRESETS) - listed
    assert not missing, f"콘솔에서 고를 수 없는 프리셋: {sorted(missing)}"


# --- The planner remembers what it looked up --------------------------------
# A turn used to leave only prose behind, so the next turn began with the
# model not knowing which tools it had already called.


@check("a_turn_keeps_its_tool_calls_and_results")
def _transcript_round_trips():
    session_id = "review-session-0003"
    app.SESSIONS.pop(session_id, None)
    transcript = [
        {"role": "user", "content": "demoa의 web 로그 보여줘"},
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "service-logs", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"logs": "boom"}'},
    ]
    app.remember_response(
        session_id,
        "demoa의 web 로그 보여줘",
        {"message": "에러가 한 건 있습니다.", "requires_approval": False},
        transcript,
    )
    _, history = app.load_session(session_id, None)
    roles = [item.get("role") for item in history]
    assert roles == ["user", "assistant", "tool", "assistant"], roles
    assert history[1]["tool_calls"][0]["id"] == "call_1", history[1]
    assert "boom" in history[2]["content"], history[2]


@check("trimming_never_orphans_a_tool_result")
def _trim_keeps_pairs():
    limit = app.SESSION_HISTORY_LIMIT
    messages = []
    while len(messages) < limit * 2:
        messages += [
            {"role": "user", "content": "q"},
            {"role": "assistant", "tool_calls": [{"id": f"c{len(messages)}"}]},
            {"role": "tool", "tool_call_id": f"c{len(messages)}", "content": "{}"},
            {"role": "assistant", "content": "a"},
        ]
    kept = app.trim_transcript(messages)
    assert len(kept) <= limit, len(kept)
    assert kept[0]["role"] == "user", kept[0]
    # Every tool result still has the call that produced it.
    offered = set()
    for item in kept:
        for call in item.get("tool_calls") or []:
            offered.add(call["id"])
        if item.get("role") == "tool":
            assert item["tool_call_id"] in offered, item


@check("an_early_return_closes_every_open_tool_call")
def _no_unanswered_calls_in_source():
    # A turn asks for several tools at once. Returning as soon as one of them
    # decides the turn leaves the others unanswered, and the next request is
    # rejected for referring to a tool call that never got a result. Every
    # return that ends a turn while calls are open has to go through finish().
    source = (ROOT / "agent" / "planner.py").read_text()
    tree = ast.parse(source)
    call_llm = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "call_llm"
    )
    finish = next(
        (n for n in ast.walk(call_llm)
         if isinstance(n, ast.FunctionDef) and n.name == "finish"),
        None,
    )
    assert finish is not None, "조기 반환이 열린 도구 호출을 닫지 않음"

    # The one branch with nothing open: the planner answered without calling
    # any tool, so there is no result to supply.
    no_tool_calls = next(
        n for n in ast.walk(call_llm)
        if isinstance(n, ast.If)
        and isinstance(n.test, ast.UnaryOp)
        and isinstance(n.test.op, ast.Not)
        and isinstance(n.test.operand, ast.Name)
        and n.test.operand.id == "tool_calls"
    )
    exempt = {id(n) for n in ast.walk(no_tool_calls) if isinstance(n, ast.Return)}

    def returns_of(scope):
        """Returns belonging to this function, not to helpers nested in it."""
        for child in ast.iter_child_nodes(scope):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Return):
                yield child
            yield from returns_of(child)

    for node in returns_of(call_llm):
        if id(node) in exempt:
            continue
        assert (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "finish"
        ), f"line {node.lineno}: 열린 도구 호출을 남긴 채 반환한다"


# --- A repository's own image decides its port -------------------------------
# Deploying with `existing` published the preset's default port. A repository
# whose Dockerfile exposes 80 was published on 3000: the container ran, docker
# reported it healthy, and the public URL answered nothing.


@check("an_existing_dockerfile_decides_the_container_port")
def _existing_uses_the_dockerfiles_port():
    root = PROJECTS / "dockerfile-port"
    root.mkdir(parents=True, exist_ok=True)

    (root / "Dockerfile").write_text("FROM nginx\nEXPOSE 80\nCMD nginx\n")
    assert runtime.dockerfile_exposed_ports(root / "Dockerfile") == [80]

    (root / "Dockerfile").write_text(
        "FROM x\n# EXPOSE 9999\nexpose 8080/tcp 8443\nEXPOSE $PORT\n"
    )
    assert runtime.dockerfile_exposed_ports(root / "Dockerfile") == [8080, 8443]

    assert runtime.dockerfile_exposed_ports(root / "Missing") == []


# --- A plan hands over facts, and never overrules the planner -----------------
# The app layer used to re-open a finished plan and turn the planner's own
# choices back into questions. Permission separation is what makes a mutation
# safe; what the user still needs is to know what they are approving. So the
# facts travel with the plan, and a value nobody can know stays a missing field
# in the skill's own contract.


@check("a_plan_carries_facts_not_verdicts")
def _plan_carries_repository_and_host_facts():
    source = (ROOT / "agent" / "app.py").read_text()
    for gone in ("def deploy_confirmations(", "def already_asked(", "SOURCE_BUILD_FRAMEWORKS"):
        assert gone not in source, gone

    original = runtime.inspect_repository
    try:
        runtime.inspect_repository = lambda url: {
            "has_dockerfile": True, "dockerfile_ports": [8080]
        }
        preset = runtime.repository_facts("https://github.com/a/b", "static")
        assert preset["has_dockerfile"] is True, preset
        assert preset["dockerfile_ports"] == [8080], preset
        assert "preset_replaces_dockerfile" in preset, preset

        existing = runtime.repository_facts("https://github.com/a/b", "existing")
        assert "preset_replaces_dockerfile" not in existing, existing

        def unreachable(url):
            raise RuntimeError("no network")

        runtime.inspect_repository = unreachable
        assert runtime.repository_facts("https://github.com/a/b", "static") == {}
    finally:
        runtime.inspect_repository = original

    assert runtime.build_capacity("static") is None
    assert runtime.build_capacity("existing") is None
    vite = runtime.build_capacity("vite")
    assert vite["builds_from_source"] is True, vite
    assert set(vite) >= {"host_memory_mb", "recommended_memory_mb", "likely_to_fail"}, vite


@check("an_unknowable_port_is_a_missing_field")
def _port_is_asked_by_the_contract_not_by_the_app():
    source = (ROOT / "agent" / "runtime.py").read_text()
    tree = ast.parse(source)
    deploy = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "service_deploy"
    )
    body = ast.get_source_segment(source, deploy) or ""
    assert "dockerfile_ports" in body, "배포가 저장소가 선언한 포트를 읽지 않는다"
    tail = body[body.index("dockerfile_ports"):]
    assert "missing_input(" in tail, "선언이 없을 때 물어보지 않고 추측한다"
    assert '"container_port"' in tail, tail[:200]


@check("tool_descriptions_carry_a_contract_not_a_lecture")
def _no_prohibition_boilerplate():
    import skill_registry

    # What a skill refuses is part of its own contract and stays. What went is
    # the identical paragraph that was appended to all sixteen of them, telling
    # the planner not to invent values and not to answer with the reply tool --
    # rules the system prompt already states once.
    boilerplate = (
        "runtime_rule",
        "Never invent values",
        "Never copy examples",
        "Never use conversation-reply",
        "Select this tool when the latest user intent matches",
    )
    for document in skill_registry.skill_documents():
        description = planner.tool_description_for_llm(document)
        for phrase in boilerplate:
            assert phrase not in description, f"{document['name']}: {phrase}"

    # The reply tool is built inline, so read it where it is written.
    source = (ROOT / "agent" / "planner.py").read_text()
    reply = source[source.index('"name": "conversation-reply"'):]
    reply = reply[:reply.index('"parameters"')]
    for scold in ("Never ", "Do not "):
        assert scold not in reply, reply


# --- A dead model does not take the whole request down -----------------------
# gemini-2.5-flash was retired and answered 404. Only 429 fell through to the
# next model, so every request died on it while a working model sat untried
# behind it in the same list.


@check("a_failing_model_falls_through_to_the_next")
def _model_list_survives_a_dead_model():
    source = (ROOT / "agent" / "planner.py").read_text()
    tree = ast.parse(source)
    transport = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "llm_chat_completion"
    )
    body = ast.get_source_segment(source, transport) or ""
    assert "raise_for_status" not in body, "첫 실패에서 요청 전체가 죽는다"
    assert "status_code >= 400" in body, body[-400:]

    calls = []
    def fake_post(url, **kwargs):
        model = kwargs["json"]["model"]
        calls.append(model)
        class Response:
            status_code = 404 if model == "dead-model" else 200
            text = "retired"
            headers: dict = {}
            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "ok"}}]}
        return Response()

    original_post = planner.requests.post
    original_models = os.environ.get("LLM_MODELS", "")
    try:
        planner.MODEL_COOLDOWNS.clear()
        os.environ["LLM_MODELS"] = "dead-model,live-model"
        os.environ["LLM_API_KEY"] = "k"
        os.environ["LLM_API_URL"] = "https://example.invalid"
        planner.requests.post = fake_post
        message, model = planner.llm_chat_completion([{"role": "user", "content": "hi"}])
        assert model == "live-model", model
        assert calls == ["dead-model", "live-model"], calls
        assert message["content"] == "ok", message
        # And it is not retried while a working model is available.
        assert "dead-model" in planner.MODEL_COOLDOWNS
        calls.clear()
        planner.llm_chat_completion([{"role": "user", "content": "hi"}])
        assert calls == ["live-model"], calls

        # But a cooldown is a preference, not a prohibition: with every model
        # cooling down, sending nothing answers nothing.
        calls.clear()
        planner.MODEL_COOLDOWNS.update({"dead-model": 1e9, "live-model": 1e9})
        message, model = planner.llm_chat_completion([{"role": "user", "content": "hi"}])
        assert model == "live-model", model
        assert calls, "쿨다운뿐일 때 한 번도 시도하지 않았다"
        # A model that answered is no longer cooling down.
        assert "live-model" not in planner.MODEL_COOLDOWNS
    finally:
        planner.requests.post = original_post
        planner.MODEL_COOLDOWNS.clear()
        os.environ["LLM_MODELS"] = original_models
        os.environ.pop("LLM_API_KEY", None)
        os.environ.pop("LLM_API_URL", None)


# --- A project agent notices when the agent's code changed -------------------
# The version stamped into each project's compose file is what tells the
# platform to rebuild that project's agent. It was a hand-written list of five
# files, and the refactor moved the planner, the permission registry and the
# prompts out of them.


@check("every_agent_source_changes_the_template_version")
def _template_version_covers_the_whole_agent():
    baseline = runtime.project_agent_template_version()
    assert len(baseline) == 16, baseline
    for relative in ("planner.py", "authz.py", "skill_registry.py", "prompts/planner.md"):
        path = ROOT / "agent" / relative
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        try:
            changed = runtime.project_agent_template_version()
        finally:
            path.write_bytes(original)
        assert changed != baseline, f"{relative} 변경이 버전에 반영되지 않음"
    assert runtime.project_agent_template_version() == baseline


# --- The planner's own tool calls are scoped too -----------------------------
# chat scoped the mutation it hands to the approval gate, but the read-only
# tools the planner runs to answer a question went straight to the runtime. A
# project token could list every project's services just by asking.


@check("the_planner_runs_tools_through_the_callers_executor")
def _planner_takes_an_executor():
    source = (ROOT / "agent" / "planner.py").read_text()
    tree = ast.parse(source)
    call_llm = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "call_llm"
    )
    parameters = {argument.arg for argument in call_llm.args.args}
    parameters |= {argument.arg for argument in call_llm.args.kwonlyargs}
    assert "execute" in parameters, sorted(parameters)

    body = ast.get_source_segment(source, call_llm) or ""
    observation = [line for line in body.splitlines() if "observation = " in line]
    assert observation, body[-400:]
    assert all("execute_cli_skill" not in line for line in observation), observation


@check("chat_scopes_the_tools_the_planner_runs")
def _chat_injects_the_scoped_executor():
    source = (ROOT / "agent" / "app.py").read_text()
    tree = ast.parse(source)
    chat = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "chat"
    )
    call = next(
        n for n in ast.walk(chat)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "call_llm"
    )
    executor = next(
        (kw.value for kw in call.keywords if kw.arg == "execute"), None
    )
    assert isinstance(executor, ast.Name) and executor.id == "scoped_execute", \
        ast.dump(call)[:300]


@check("a_project_token_is_not_offered_root_tools")
def _root_tools_are_withheld():
    import skill_registry

    everything = {item["name"] for item in app.available_skills(None)}
    scoped = {item["name"] for item in app.available_skills("demoa")}
    # project.ensure_agent is root-only and undocumented, so it was never on
    # the tool list to begin with.
    assert everything - scoped == set(skill_registry.root_only_skills()) & everything, \
        sorted(everything - scoped)
    assert "project.create" not in scoped, sorted(scoped)
    assert "service.deploy" in scoped, sorted(scoped)


# --- Permissions come from the skill documents ------------------------------


@check("every_skill_declares_its_own_permissions")
def _permissions_are_declared():
    import skill_registry

    documents = skill_registry.skill_documents()
    assert len(documents) == 16, len(documents)
    for document in documents:
        assert document["access"] in {"read", "mutate"}, document["name"]
        assert document["plane"] in {"root", "project", "shared"}, document["name"]


@check("permission_sets_are_derived_not_restated")
def _no_hardcoded_permission_sets():
    for name in ("app", "authz", "planner", "runtime", "cli"):
        source = (ROOT / "agent" / f"{name}.py").read_text()
        assert "READ_ONLY_SKILLS = {" not in source, name
        assert "PROJECT_SCOPED_HIDDEN_SKILLS" not in source, name
    authz_source = (ROOT / "agent" / "authz.py").read_text()
    for skill in ("service.deploy", "service.redeploy", "port.manage", "qa.run"):
        assert f'"{skill}"' not in authz_source, f"authz가 {skill}을 이름으로 들고 있음"


@check("a_new_skill_cannot_slip_past_the_gate")
def _sets_match_the_documents():
    import skill_registry

    read = skill_registry.read_only_skills()
    root = skill_registry.root_only_skills()
    project = skill_registry.project_scoped_skills()
    # The behaviour these replaced, spelled out so a change has to be deliberate.
    assert read == frozenset({
        "entity.resolve", "framework.list", "help.search", "platform.help",
        "server.health", "project.list", "repository.inspect", "service.status",
        "service.logs", "port.suggest", "qa.run",
    }), sorted(read)
    assert root == frozenset({
        "project.create", "project.ensure_agent", "server.health", "qa.run",
    }), sorted(root)
    assert project == frozenset({
        "service.deploy", "service.redeploy", "service.status",
        "service.logs", "service.control", "port.manage",
    }), sorted(project)
    # Root-plane skills stay refused for a namespace token.
    from fastapi import HTTPException

    for skill in sorted(root):
        try:
            app.namespace_scoped_arguments(skill, {}, "mine")
        except HTTPException as exc:
            assert exc.status_code == 403, skill
            continue
        raise AssertionError(f"{skill}이 네임스페이스 토큰에 허용됨")


# --- Modules depend in one direction ----------------------------------------


@check("module_dependencies_point_one_way")
def _no_cycles():
    layers = ["app", "planner", "authz", "runtime", "skill_registry"]
    allowed = {
        # A module may only import from ones below it.
        "app": {"authz", "planner", "runtime", "skill_registry"},
        "planner": {"runtime", "skill_registry"},
        "authz": {"skill_registry"},
        "runtime": {"skill_registry"},
        "skill_registry": set(),
        "cli": {"runtime", "skill_registry"},
    }
    for module, permitted in allowed.items():
        tree = ast.parse((ROOT / "agent" / f"{module}.py").read_text())
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module in set(layers) | {"cli"}
        }
        illegal = imported - permitted
        assert not illegal, f"{module}.py가 {sorted(illegal)}을 임포트함"
    # The planner must not be able to reach Docker directly.
    planner_source = (ROOT / "agent" / "planner.py").read_text()
    for forbidden in ("import docker", "subprocess", "compose_command"):
        assert forbidden not in planner_source, f"planner가 {forbidden}에 닿음"


# --- Tools run in this process, and go through the namespace gate -----------


@check("tool_execution_does_not_spawn_a_process")
def _no_cli_subprocess():
    source = (ROOT / "agent" / "runtime.py").read_text()
    tree = ast.parse(source)
    node = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "execute_cli_skill"
    )
    body = ast.get_source_segment(source, node) or ""
    assert "subprocess" not in body, "도구 실행이 아직 프로세스를 띄움"
    assert "execute_skill(" in body, "컨트롤 플레인에서 인프로세스로 실행하지 않음"
    assert "call_platform_api_skill(" in body, "프로젝트 에이전트 경로가 없음"


@check("only_project_free_skills_run_outside_the_namespace_gate")
def _gate_covers_project_scoped_skills():
    source = (ROOT / "agent" / "app.py").read_text()
    tree = ast.parse(source)
    gated = {"chat", "execute", "preview"}
    outside = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name in gated:
            continue
        for call in ast.walk(node):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                    and call.func.id == "execute_cli_skill" and call.args):
                skill = getattr(call.args[0], "value", None)
                outside.append((node.name, skill))
    # repository.inspect takes a repository URL and no project, so scoping it
    # would be a no-op. Anything else outside the gate is a leak.
    for owner, skill in outside:
        assert skill == "repository.inspect", f"{owner}가 {skill}을 게이트 밖에서 실행"


# --- One transport, and prompts that live outside the code ------------------


@check("one_transport_serves_both_llm_roles")
def _single_transport():
    source = (ROOT / "agent" / "planner.py").read_text()
    posts = source.count("chat/completions")
    assert posts == 1, f"전송 구현이 {posts}벌"
    # Cooldowns are written for a rate limit and for a model that answered an
    # error; what matters is that both live inside the one transport.
    tree = ast.parse(source)
    transport = next(
        n for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "llm_chat_completion"
    )
    inside = (ast.get_source_segment(source, transport) or "").count("MODEL_COOLDOWNS[model]")
    assert inside == source.count("MODEL_COOLDOWNS[model]"), "전송 밖에서 쿨다운을 기록함"

    # Both roles have to go through it.
    for name in ("call_llm", "call_llm_text"):
        node = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
        )
        body = ast.get_source_segment(source, node) or ""
        assert "llm_chat_completion(" in body, f"{name}이 공용 클라이언트를 쓰지 않음"
        assert "requests.post" not in body, f"{name}이 직접 POST함"


@check("prompts_are_files_not_string_literals")
def _prompts_load():
    for name in ("planner", "read_only_reply", "mutation_reply"):
        text = planner.load_prompt(name)
        assert len(text) > 80, f"{name} 프롬프트가 비어 있음"
    for path in (
        ROOT / "agent" / "app.py",
        ROOT / "agent" / "runtime.py",
        ROOT / "agent" / "planner.py",
    ):
        source = path.read_text()
        assert "You operate a small Docker deployment" not in source, path.name
        assert "You are the final response writer" not in source, path.name
        assert "You write the final Korean reply" not in source, path.name


print()
print(f"RESULT: {len(PASSED)} passed / {len(FAILED)} failed")
if FAILED:
    for label in FAILED:
        print(f"  - {label}")
    sys.exit(1)
