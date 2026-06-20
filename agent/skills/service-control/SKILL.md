---
name: service-control
description: Start, stop, or restart a known Compose service through fixed Docker APIs. Use for explicit service lifecycle requests. Always require dry-run preview and user approval.
---

# Service Control

Accept only `start`, `stop`, or `restart`.

1. Validate project and service against Compose.
2. Return a dry-run preview.
3. Execute only after explicit approval.
4. Verify state after execution.
5. For start or restart, wait four seconds and reject restart loops.

Do not accept commands, paths, Docker options, or shell input.
