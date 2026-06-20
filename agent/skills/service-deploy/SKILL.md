---
name: service-deploy
description: Deploy a new service into an existing managed Compose project from a public GitHub repository. Use when the user wants to add or deploy a service. Omit missing arguments so the application can ask follow-up questions. Always require dry-run preview and approval.
---

# Service Deploy

Accept only public `https://github.com/<owner>/<repository>` URLs.
Require a framework preset. All presets expose container port 3000 by default.

1. Validate the existing project and new service name.
2. Select or validate a host port from 9000 through 9100.
3. Return a dry-run preview before cloning or building.
4. After approval, shallow-clone the repository into the managed project.
5. Use the repository Dockerfile only for the `existing` preset; otherwise generate the selected framework Dockerfile in the server clone.
6. Add one fixed Compose service definition, build it, and start it.
7. Verify the container remains running and publishes the expected port.
8. Restore Compose and remove the cloned directory if deployment fails.

Do not accept arbitrary paths, branches, Git options, Docker flags, or shell commands.
Accept environment variable names only. Secret values must be entered directly in the dashboard and must never be sent to the LLM or audit log.
