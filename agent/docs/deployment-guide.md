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
