# Design

## Visual Register

Cloud Platform Console is a restrained product/admin interface. Design serves task completion: project selection, service operation, deployment guidance, and capacity awareness.

## Layout

- Use a simple app shell: compact top bar, login/account area, main content.
- Home screen hierarchy:
  1. server capacity summary,
  2. project list,
  3. project creation,
  4. secondary service catalog only if useful.
- Project detail hierarchy:
  1. project identity and membership/permission state,
  2. project resource summary,
  3. service cards/table with direct actions,
  4. project-scoped AI assistant.
- Avoid a large marketing hero. Avoid full-width decorative cards that do not carry operational content.
- Use tables or dense cards for services when facts matter: status, public URL, internal/public port, memory, logs, actions.

## Components

- **Capacity indicators**: disk and memory should be scan-friendly gauges/rings/bars with percentages and warning thresholds.
- **Project cards**: show project name, service count, member/role cue, and primary “open” action.
- **Service cards**: show running/stopped/error state, frontend URL when public, internal-only marker for backends, port mapping, memory usage, and action buttons.
- **AI assistant**: keep it secondary. It can render structured questionnaires, confirmation plans, and natural-language results. It should not replace direct operation buttons.
- **Approval panels**: never show raw JSON by default. Summarize action, target project/service, inputs, risks, and expected result. Provide approve/cancel buttons.

## Typography

- Use one clean system/Pretendard-style sans stack.
- Prefer clear labels and compact body text over oversized display headings.
- Keep headings descriptive: “Projects”, “Server capacity”, “Services”, “Project agent”.
- Do not use tiny uppercase eyebrow labels as repeated decoration.

## Color

- Light background by default.
- Use neutral surfaces and a single blue primary action color.
- Use green/yellow/red only for operational states.
- Do not use decorative gradients, glass panels, or neon AI styling.
- Text contrast must meet WCAG AA; muted text should remain readable.

## Interaction

- Buttons for direct service actions: start, stop, restart, redeploy, logs.
- AI-guided deploy should use form/question cards when required fields are missing.
- Keep user-entered context in the conversation, but allow intent changes without repeating stale deployment prompts.
- For frontend services, provide a direct public URL link. For backend/internal services, show internal-only connectivity instead of a public URL.

## Motion

Use minimal motion: loading indicators, small transitions, no decorative animated backgrounds. Respect `prefers-reduced-motion`.

## Things to avoid

- Huge rounded cards and nested cards.
- Repeated same-size cards with the same visual weight.
- Raw Docker/CLI architecture labels as primary UI.
- Decorative grid backgrounds.
- Placeholder explanations like “AI/CLI 기반으로 안전하게 처리합니다” when a concrete status/action would be more useful.
