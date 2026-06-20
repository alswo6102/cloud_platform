---
name: service-logs
description: Read a bounded tail of Docker logs for a known Compose service. Use to diagnose startup, health, proxy, and runtime failures without shell access.
---

# Service Logs

Require valid `project` and `service`. Limit output to 100 lines.

Verification: Resolve the container using Compose labels. Never expose environment variables.
