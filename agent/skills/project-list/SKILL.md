---
name: project-list
description: List valid Docker Compose projects and service names under the managed project root. Use before selecting or operating on a project or service.
---

# Project List

Read only directories containing `docker-compose.yml` under `/srv/projects`.

Verification: Return project and service names parsed from Compose. Never accept arbitrary paths.
