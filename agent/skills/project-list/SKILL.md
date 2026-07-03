---
name: project-list
description: List valid Docker Compose projects and service names under the managed project root. Use at root/admin scope before selecting or operating on a project or service.
---

# Project List

Read only directories containing `docker-compose.yml` under `/srv/projects`.

Verification: Return project and service names parsed from Compose. Never accept arbitrary paths.

In a project-scoped chat where the current project is already fixed, do not use
this command just to answer "서비스 목록". Use `service.status` instead so the
reply can include live container state, ports, and frontend URLs.
