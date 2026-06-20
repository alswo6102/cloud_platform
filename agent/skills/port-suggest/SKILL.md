---
name: port-suggest
description: Suggest the first unused host port from 9000 through 9100 by inspecting every managed Compose file. Use before deploying or changing a published port.
---

# Port Suggest

Return the first host port not reserved by any managed Compose service.

Verification: Scan every `/srv/projects/*/docker-compose.yml` file and return only a port from
9000 through 9100.
