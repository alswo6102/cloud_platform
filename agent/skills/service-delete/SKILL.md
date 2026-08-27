---
name: service-delete
description: Permanently remove a deployed service from its project — the container, the Compose entry, the server-side source clone, the built image, and the deployment record. Use only when the user asks to delete, remove, or tear down a service. If project or service is missing, omit it so the application can ask a follow-up question. Always require preview and approval.
access: mutate
plane: project
---

# Service Delete

This is the only skill that destroys work. Nothing it removes can be restored
from the platform; the GitHub repository is the only copy that survives.

1. Validate the project and the service against Compose.
2. Refuse the `agent` service. A project without its agent cannot be managed.
3. Return a dry-run preview naming every artefact that will be removed and the
   host port that will be released.
4. Execute only after explicit approval.
5. Stop and remove the container, then rewrite Compose without the service.
6. Remove the server-side source clone, the deployment record, and the image
   built for this service alone.
7. Restore the previous Compose file when removal fails partway.

Do not accept commands, paths, Docker options, or shell input. Do not remove
images that other services share, and do not touch anything outside the
project directory.
