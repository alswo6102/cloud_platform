# Impeccable-based console redesign notes

Local reference clone:

- `/opt/cloud_platform/.codex_refs/impeccable`

Use this reference like a design skill for frontend UI work. Before redesigning the console, read:

- `.codex_refs/impeccable/skill/SKILL.src.md`
- `.codex_refs/impeccable/skill/reference/product.md`
- `.codex_refs/impeccable/skill/reference/layout.md`
- `.codex_refs/impeccable/skill/reference/typeset.md`
- `.codex_refs/impeccable/skill/reference/polish.md`
- `.codex_refs/impeccable/skill/reference/audit.md`

The cloud platform console is product/admin UI, not a marketing page. Use predictable app patterns, strong hierarchy, compact operational density, and restrained styling.

Next UI redesign constraints:

1. Main view should prioritize project list, not service list.
2. Remove low-value top-level chrome such as Docker online and raw container count from the primary visual hierarchy.
3. Show memory and disk capacity with highly scannable gauges or circular indicators.
4. Avoid identical same-weight cards everywhere. Use hierarchy: primary project area, secondary resource indicators, tertiary actions.
5. Service cards must show operational facts first: status, public URL for frontend services, internal/public port, memory, and direct actions.
6. Direct service buttons should execute real API actions; AI chat is for ambiguous natural-language requests and guided deployment.
7. No decorative grid backgrounds, glassmorphism, huge rounded cards, or generic SaaS/AI-dashboard styling.
