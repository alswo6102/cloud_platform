---
name: service-env-set
description: Write or remove environment variable values for a Compose service. Called by the console form only; it is withheld from the planner because its arguments carry secrets. Always require dry-run preview and user approval.
access: mutate
plane: project
---

# Service Env Set

Set environment variable values for a service, and remove the ones asked for.

1. Validate project and service against Compose.
2. Reject names that are not valid environment variable identifiers.
3. Reject values containing a newline: Compose reads env_file one line at a
   time and would truncate the value.
4. Return a dry-run preview carrying names and counts, never values.
5. Execute only after explicit approval.
6. Recreate the container when asked, because an env file is read only when a
   container is created; restarting the existing one changes nothing.

This skill is deliberately kept off the planner's tool list. Values reach it
from the console form, which calls the skill directly and does not pass through
the language model. Do not add it to the offered tools.
