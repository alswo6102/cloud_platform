---
name: qa-run
description: Run compact deterministic checks for Docker, restart loops, unhealthy containers, duplicate Compose ports, and disk pressure. Use after operations or when asked to inspect the platform.
---

# QA Run

Run read-only checks and return one result object.

Verification passes only when Docker responds, no container is restarting or unhealthy, no
Compose host port is duplicated, and project-disk usage is below 95 percent.
