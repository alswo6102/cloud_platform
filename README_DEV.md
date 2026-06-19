# cloud_platform Codex Development Workflow

This repo is developed locally and verified on the NCP server through scripts.
Codex should edit local files only. The server is a deployment and QA target.

## Loop

1. Edit local code.
2. Run local checks.
3. Review `git diff`.
4. Deploy to NCP with `scripts/deploy_to_ncp.sh`.
5. Run `scripts/qa_all.sh`.
6. If QA fails, inspect short logs with `scripts/remote_logs.sh`.
7. Repeat until all checks pass.

## Token Rule

Scripts should print compact `OK` / `FAIL` lines by default.
Long command output should be hidden unless a check fails.

## Required Local Config

Copy `.env.example` to `.env.local` and fill in the server values.

```sh
cp .env.example .env.local
```

Do not commit `.env.local`.

For password SSH, wrap passwords containing shell characters in single quotes.

The server preparation script installs Docker and Docker Compose, creates
`/srv/projects`, and maintains a 2GB swap file.

## MVP QA Scope

- SSH connection works.
- Remote base tools exist: Python, Docker, Docker Compose, and 2GB swap.
- Project directory exists.
- App can be deployed.
- App process starts.
- Dashboard health endpoint responds.
- Docker access works from the app user.

## Later

- Add LLM skill CLI tests.
- Add Streamlit smoke tests.
- Add GitHub push/PR automation.
- Add login and HTTPS.
