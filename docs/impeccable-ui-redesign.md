# Impeccable-based console redesign notes

Local reference clone:

- `/opt/cloud_platform/.codex_refs/impeccable`

Installed local skill copies:

- `/root/.codex/skills/impeccable` for Codex skill discovery in future sessions.
- `/opt/cloud_platform/.agents/skills/impeccable` for project-local agent/hook compatibility.

Use Impeccable as a real design workflow, not as a visual inspiration folder. Before redesigning the console, load:

- `PRODUCT.md`
- `DESIGN.md`
- `.agents/skills/impeccable/SKILL.md`
- `.agents/skills/impeccable/reference/product.md`
- `.agents/skills/impeccable/reference/layout.md`
- `.agents/skills/impeccable/reference/typeset.md`
- `.agents/skills/impeccable/reference/polish.md`
- `.agents/skills/impeccable/reference/audit.md`

The cloud platform console is product/admin UI, not a marketing page. Use predictable app patterns, strong hierarchy, compact operational density, and restrained styling.

## Required design gate

Before editing frontend UI code:

1. Identify the target surface: home, project detail, service card/table, AI assistant, approval flow, login/account, or capacity summary.
2. State the primary user action for that surface.
3. Name what should be removed or demoted.
4. Choose the Impeccable command/reference that fits:
   - `shape` for planning a new surface or large redesign.
   - `layout` for hierarchy, spacing, and IA.
   - `polish` for final visual quality.
   - `harden` for error, loading, empty, permission, overflow, and i18n states.
   - `clarify` for copy, labels, and raw-result cleanup.
5. Ask for confirmation when the change is structural. Do not jump straight into CSS if the IA is still wrong.

When the user asks for a Claude Code design-like flow, use the question/brief pattern:

1. Ask 2-3 targeted questions or render a structured questionnaire.
2. Produce a compact design brief.
3. Wait for confirmation.
4. Implement.
5. Audit against PRODUCT.md, DESIGN.md, and the relevant Impeccable references.

## Hook note

The upstream Codex hook is:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|apply_patch",
        "hooks": [
          {
            "type": "command",
            "command": "node \".agents/skills/impeccable/scripts/hook.mjs\"",
            "timeout": 5,
            "statusMessage": "Checking UI changes"
          }
        ]
      }
    ]
  }
}
```

Do not enable this hook on a host that lacks `node`. This VM currently serves the app and does not build the React frontend, so hook activation should wait until Node is available or the check runs in the local Mac/build environment.

Next UI redesign constraints:

1. Main view should prioritize project list, not service list.
2. Remove low-value top-level chrome such as Docker online and raw container count from the primary visual hierarchy.
3. Show memory and disk capacity with highly scannable gauges or circular indicators.
4. Avoid identical same-weight cards everywhere. Use hierarchy: primary project area, secondary resource indicators, tertiary actions.
5. Service cards must show operational facts first: status, public URL for frontend services, internal/public port, memory, and direct actions.
6. Direct service buttons should execute real API actions; AI chat is for ambiguous natural-language requests and guided deployment.
7. No decorative grid backgrounds, glassmorphism, huge rounded cards, or generic SaaS/AI-dashboard styling.
