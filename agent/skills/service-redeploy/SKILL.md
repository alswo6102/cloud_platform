---
name: service-redeploy
description: Safely rebuild and redeploy an existing managed service. Checks the configured GitHub origin first and clones only when it has commits the server does not have; when the origin is unchanged or unreachable it rebuilds the checkout already on the server. Use after the user has pushed new code, and also to rebuild a service on the current preset without any code change. If project or service is missing, omit it so the application can ask a follow-up question. Always require preview and approval.
access: mutate
plane: project
---

# Service Redeploy

1. Validate the existing project and service.
2. Read the service Git origin without accepting user-supplied paths or Git options.
3. Compare the origin's HEAD with the checkout on the server.
   - New commits: clone the latest source into a temporary sibling directory.
   - No new commits, or the origin cannot be reached: copy the checkout already
     on the server into that directory instead.
4. Require a root-level Dockerfile.
5. Swap source directories only after the new one is ready.
6. Build a new image and force-recreate only the target service.
7. Verify the new container remains running.
8. Restore the previous source and container when build or verification fails.

Do not use `git pull` in the existing working tree and do not discard the old source before verification.

The preview names which source the build will use and why, so a rebuild from the
server's own checkout is always something the user approved rather than a silent
fallback. This is what keeps a service redeployable after its origin is renamed,
made private, or deleted -- the server holds a complete checkout of exactly the
source that is running.
