---
name: service-env-list
description: List the environment variable names configured for a Compose service, with whether each is set. Use when asked which variables a service has or what is still missing. Never returns secret values.
access: read
plane: project
---

# Service Env List

Report the environment variables a service is configured with.

1. Validate project and service against Compose.
2. Return one entry per name: whether it is secret, whether it has a value, and when it changed.
3. Include the value only for entries that are not marked secret.
4. Report how many are still unset, so an unfinished deploy is visible.

A secret entry omits the value key entirely rather than sending an empty
string, so a caller cannot read "hidden" as "not set".
