# Product

## Register

product

## Users

Cloud Platform Console is used by three permission levels:

- **Visitor**: can see public service/project surfaces only when allowed, but cannot use AI agents or operate infrastructure.
- **User**: can create projects, open projects they belong to, deploy services inside those projects, and operate only their own project services.
- **Admin**: can see all projects, use root-level maintenance tools, and operate any project when necessary.

The main user is a developer or project maintainer who wants to preserve and demonstrate multiple Dockerized projects on one small server without memorizing Docker commands.

## Product Purpose

The console makes project-scoped deployment and service operation safe, visible, and repeatable. It should let a user create a project, enter that project workspace, deploy frontend/backend services, check runtime state, open public frontend URLs, view logs, and run guarded start/stop/restart/redeploy actions.

AI is not the primary navigation. AI is a project-scoped assistant for ambiguous natural-language requests and guided deployment flows. Deterministic buttons and forms should handle direct, common operations.

## Brand Personality

Calm, operational, trustworthy.

The product should feel like a compact infrastructure console, not an AI demo page. Copy should be direct, short, and action-oriented. Avoid marketing language and decorative explanations.

## Anti-references

- Generic AI/SaaS dashboard chrome: oversized gradient heroes, glassmorphism, glowing cards, motivational copy.
- Equal-weight card grids where every item looks equally important.
- Showing implementation trivia as primary UI, such as “scoped”, “CLI guard”, raw container counts, or internal architecture labels.
- Raw JSON or raw execution plans in normal user-facing flows.
- Chat-only control for actions that should be available as buttons.

## Design Principles

1. **Projects are the home object.** The main screen prioritizes project list, project ownership, and server capacity. Services belong inside project detail.
2. **Operations beat explanations.** Cards show state, resource usage, URLs, ports, and direct actions before descriptive text.
3. **AI is scoped and assistive.** In a project page, the agent assumes that project as default context. It asks for missing deployment inputs, shows structured forms when useful, and never silently changes infrastructure.
4. **Dangerous changes require confirmation.** Deploy, redeploy, stop, delete, and other mutating actions show a human-readable plan and explicit approval.
5. **Security is visible but quiet.** Permission boundaries matter, but the UI should communicate them through available actions and disabled states, not through architecture jargon.

## Accessibility & Inclusion

Baseline WCAG AA. Use visible focus states, semantic forms/buttons, sufficient contrast, and readable Korean/English mixed text. Loading, empty, error, success, and permission-denied states must be clear without relying on color alone.
