# Deployment Guide

The dashboard manages Docker Compose projects under `/srv/projects`.

- Host ports are allocated from `9000` through `9100`.
- Container ports default to `3000`, but the Compose mapping can be changed per service.
- Frontend services need the `is_web_service=true` label to show an Open button.
- A frontend reverse proxy must reference the exact Compose backend service name.
- The dashboard runs on port `8501`.
- The skill agent is internal-only and is not published to a host port.
- Use `qa_fast.sh` for compact operational checks and `qa_all.sh` for deployment plus smoke tests.

Dockerfiles must start production servers on `0.0.0.0`, not `127.0.0.1`.
Changing a Compose container-port mapping does not automatically change the application process
or Dockerfile. Verify that the application actually listens on the new port.

## Easy Framework Deployment

New services can use a framework preset instead of preparing a Dockerfile in
the Git repository. Presets generate a Dockerfile only in the server clone and
standardize the container port to `3000`.

Supported presets include Vite, Create React App, Next.js, Express/NestJS,
FastAPI, Flask, Django, Spring Boot with Maven or Gradle, and Go. Select
`existing` for repositories that need custom Docker behavior.

Before execution the dashboard shows the project, service, framework,
Dockerfile policy, host and container ports, environment variable names,
execution steps, verification, and rollback plan. Deployment begins only after
explicit approval.

Environment variable names may be included in a deployment plan. Actual values
must be entered through the dashboard service settings and are not sent to the
LLM or written to the Agent audit log.
