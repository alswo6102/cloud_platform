---
name: service-redeploy
description: Safely rebuild and redeploy an existing managed service from the latest default branch of its configured GitHub origin. Use after the user has pushed new code. If project or service is missing, omit it so the application can ask a follow-up question. Always require preview and approval.
---

# Service Redeploy

1. Validate the existing project and service.
2. Read the service Git origin without accepting user-supplied paths or Git options.
3. Clone the latest source into a temporary sibling directory.
4. Require a root-level Dockerfile.
5. Swap source directories only after the fresh clone is ready.
6. Build a new image and force-recreate only the target service.
7. Verify the new container remains running.
8. Restore the previous source and container when build or verification fails.

Do not use `git pull` in the existing working tree and do not discard the old source before verification.
