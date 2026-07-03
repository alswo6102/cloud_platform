---
name: service-status
description: Inspect the live service list/status inside a project, including configured ports, frontend labels, Docker state, health, restart count, published ports, and public URLs. Use when the user asks for service list, running state, frontend link, URL, port, or whether a project service is up.
---

# Service Status

Require a valid `project`. Accept an optional `service`.

Verification: Join Compose configuration with Docker containers using Compose labels.

In a project-scoped chat, phrases like "서비스 목록 보여줘", "뭐 떠 있어?",
"프론트 URL 있어?", "바로가기 알려줘", "포트 확인해줘", or
"상태 확인해줘" should use this command, because the answer depends on live
Compose/Docker state. Do not answer those questions from conversation memory.
