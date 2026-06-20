# cloud_platform Server Development Workflow

This repository is developed directly on the NCP server at
`/opt/cloud_platform`. The server Git repository is the source of truth. Local
machines are used only to remotely control the server. Do not rsync a local
checkout over this directory.

## Runtime Paths

- Application source and Git repository: `/opt/cloud_platform`
- Managed project data: `/srv/projects`
- Dashboard container: `cloud-platform-dashboard`
- Skill Agent container: `cloud-platform-skill-agent`
- Dashboard URL: port `8501`

Both application containers use `restart: unless-stopped`.

## Development Loop

1. Inspect Git status and the running Docker containers.
2. Edit files in `/opt/cloud_platform`.
3. Run focused syntax and behavior checks.
4. Review `git diff`.
5. Rebuild and recreate only the affected application container.
6. Run server-native QA.
7. Commit and push from the server.

Do not mix this workflow with the legacy local-to-server rsync scripts without
reviewing every difference first.

## Server-Native Checks

```sh
python3 -c 'from pathlib import Path; [compile(Path(f).read_text(), f, "exec") for f in ["admin.py", "agent/app.py", "agent/runtime.py"]]'
curl -fsS http://127.0.0.1:8501/_stcore/health
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

Run isolated natural-language mutation QA:

```sh
./scripts/server_skill_mutation_test.sh
```

The mutation script uses only `/srv/projects/skill-qa` and removes it on exit.
Never run destructive QA against an existing managed project.

The assistant supports multi-turn deployment setup. Missing project names,
service names, repository URLs, or container ports are requested before a
mutation preview is generated. Explicit new intents override pending context,
so a user can switch from service deployment to project creation when no
project exists.

Existing services are redeployed without running `git pull` in the active
working tree. The Agent clones fresh source beside the service, swaps it in,
builds and force-recreates the target container, and restores the prior source
if verification fails.

## Secrets

Runtime LLM settings are stored in `.agent.env`. Do not commit or print API
keys. Recreate the Skill Agent after changing the environment file; restarting
the existing container does not reload it.

Multiple planner models can be configured in preferred order:

```env
LLM_MODELS=gemini-3.1-flash-lite,gemini-3-flash-preview,gemini-2.5-flash,gemini-2.5-flash-lite
```

The Agent moves to the next model only for HTTP 429 rate-limit responses and
temporarily skips models that are cooling down. Authentication, malformed
request, and permission errors fail immediately instead of being hidden by a
fallback.

## Output Rule

QA scripts should print compact `OK` or `FAIL` lines. Detailed logs should be
shown only when a check fails.
