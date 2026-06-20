---
name: port-manage
description: Suggest an available host port or change a service host/container port mapping. Use for port allocation and Compose port changes. Changes require dry-run preview and approval.
---

# Port Manage

Accept:

- `change_host`: Require `host_port` from 9000 through 9100 and reject collisions.
- `change_container`: Require `container_port` from 1 through 65535.

After approval, update Compose atomically, recreate only the target service, and verify the
published binding. Roll back Compose if execution or verification fails.

Changing the container mapping does not modify the application listener or Dockerfile.
