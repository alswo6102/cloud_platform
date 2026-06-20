---
name: project-create
description: Create a new empty managed Docker Compose project. Use when the user wants to add or create a project. If the project name is missing, omit it so the application can ask a follow-up question. Always require preview and approval.
---

# Project Create

Accept only a managed project name containing letters, numbers, dots, underscores, or hyphens.

Create `/srv/projects/<project>/docker-compose.yml` with an empty services map.
Never overwrite an existing project and never accept an arbitrary path.
