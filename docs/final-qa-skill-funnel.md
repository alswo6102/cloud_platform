# Final QA Skill Funnel

## Goal

Run final QA in two layers:

1. Design and UX quality with `impeccable`.
2. Real browser, platform, and AI behavior QA with `playwright` plus internal platform skills.

The QA target is the Cloud Platform Console as a compact infrastructure console. AI is assistive, not the primary control surface.

## Installed Codex QA Skill

Installed:

- `playwright`
- Source: `openai/skills`, `skills/.curated/playwright`
- Local path: `/root/.codex/skills/playwright`

Restart Codex before expecting `$playwright` to appear in the available skill list.

Do not install browser binaries permanently under `/root` on this server. The root disk is small. When browser binaries are needed, prefer a temporary browser path and clean it after QA.

## Skill Routing

Use this routing order.

| QA Need | Skill / Tool | Purpose |
| --- | --- | --- |
| Visual hierarchy, UI quality, responsive design, Korean UX copy | `$impeccable` | Product UI critique and polish |
| Real browser clicking, form fill, DOM snapshot, screenshot | `$playwright` | Browser-level QA evidence |
| Whole desktop screenshot fallback | `screenshot` | Optional only; not installed by default |
| Runtime server and container health | `server.health` | Read-only platform health |
| Compact deterministic platform QA | `qa.run` | Docker, unhealthy, restart loop, duplicate port, disk pressure |
| Project/service inventory | `project.list`, `service.status` | Verify visible UI data against live platform data |
| Logs | `service.logs` | Bounded log QA without shell access |
| Deployment preset correctness | `framework.list`, `repository.inspect` | Verify deploy form and framework selection |
| Name ambiguity | `entity.resolve` | Verify similar names are not auto-confirmed |
| Safe mutation QA | `project.create`, `service.deploy`, `service.control`, `service.redeploy`, `port.manage` | Only on disposable `skill-qa` |

## Phase 1: Design QA Funnel

Run in this order:

```bash
node /root/.codex/skills/impeccable/scripts/detect.mjs --json frontend/src/main.tsx frontend/src/styles.css
```

Then use:

```text
$impeccable critique frontend
$impeccable audit frontend
$impeccable adapt frontend
$impeccable clarify frontend
$impeccable polish frontend
```

Design QA pass criteria:

- No P0/P1 issue remains.
- Mobile, tablet, desktop, and wide desktop screenshots have no overflow or broken alignment.
- Server capacity, project list, service state, primary service actions, and AI are visually prioritized in that order.
- Start, stop, restart, redeploy are more prominent than logs.
- AI is visible but secondary.
- Korean labels are short, direct, and action-oriented.
- Raw JSON, Docker internals, and CLI architecture jargon are not shown in normal user flows.

Required screenshot states:

- Visitor home
- User home
- Admin home with root AI
- Project detail
- Project AI empty state
- Deploy request form before and after valid input
- Approval card
- Log view
- Loading, empty, error, and permission-denied states

Required viewports:

- `390x844`
- `768x1024`
- `1365x900`
- `1440x1000`

Suggested artifact names:

- `/tmp/final-qa-visitor-mobile.png`
- `/tmp/final-qa-user-home-mobile.png`
- `/tmp/final-qa-admin-root-ai-desktop.png`
- `/tmp/final-qa-project-ai-mobile.png`
- `/tmp/final-qa-deploy-form-mobile.png`
- `/tmp/final-qa-approval-card-desktop.png`

## Phase 2: Browser and Functional QA Funnel

After restarting Codex so `$playwright` is available:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
command -v npx
"$PWCLI" --help
```

Browser QA loop:

1. Open the target page.
2. Take a snapshot.
3. Interact using snapshot refs.
4. Re-snapshot after each meaningful UI change.
5. Capture a screenshot for every signoff claim.

Core browser flows:

- Visitor:
  - Open `/`.
  - Verify public catalog, login form, disabled or denied operations.
- User:
  - Login.
  - Switch `전체 프로젝트`, `내 프로젝트`, `새 프로젝트`.
  - Open owned project.
  - Verify direct service actions are visible.
- Admin:
  - Login as admin.
  - Verify all project visibility.
  - Verify root AI panel and admin-only execution.
- Project:
  - Open project detail.
  - Verify service status, URL, framework, memory, recent deploy data.
  - Click logs.
  - Trigger project AI suggestion buttons.
  - Open deploy request form.
  - Fill valid and invalid GitHub URLs.
  - Verify field-level correction.
- Approval:
  - Trigger mutating intent.
  - Verify approval card appears.
  - Cancel once.
  - Approve only in `skill-qa`.

## Internal Platform QA Funnel

Read-only baseline:

```bash
curl -sS -H 'X-User-Role: admin' -H 'X-User-Id: admin' http://127.0.0.1:8000/api/system/summary
curl -sS -H 'X-User-Role: admin' -H 'X-User-Id: admin' http://127.0.0.1:8000/api/projects
curl -sS -H 'X-User-Role: admin' -H 'X-User-Id: admin' http://127.0.0.1:8000/api/commands
```

Run existing deterministic QA:

```bash
./scripts/server_qa_all.sh --fast
```

Run mutation QA only when disposable resources are allowed:

```bash
test ! -e /srv/projects/skill-qa
./scripts/server_skill_mutation_test.sh
test ! -e /srv/projects/skill-qa
```

Do not run mutation QA against `demoa` or `horse_race`.

## LLM Natural-Language QA Funnel

The LLM is the test subject, not the judge. Assertions must use JSON contracts and UI state.

Root/admin prompts:

- `서버가 왜 느린지 봐줘`
- `디스크랑 swap 기준으로 확인해줘`
- `실행 중인 프로젝트 요약해줘`

Expected root behavior:

- Uses `server.health`, `qa.run`, or `project.list`.
- Requires admin for `/api/admin/execute`.
- User role receives 403 for root execution.

Project prompts:

- `서비스 목록 보여줘`
- `프론트 URL 알려줘`
- `로그 보고 핵심만 알려줘`
- `다시 띄워줘`
- `최신 코드로 다시 반영해줘`
- `새 서비스 배포하고 싶어`

Expected project behavior:

- Uses current project as default scope.
- Uses `service.status` for service list and URLs.
- Uses `service.logs` for logs.
- Uses `service.control` or `service.redeploy` only with approval.
- Uses `service.deploy` clarification or deploy form when required fields are missing.

Ambiguity and failure prompts:

- Misspelled project or service names should trigger `entity.resolve` candidates.
- Missing project or service should produce a specific next question.
- Invalid GitHub URL should produce a field-level correction.
- Mutating actions must not execute before approval.

## Cleanup

After QA:

```bash
rm -rf /tmp/ms-playwright
rm -rf /root/.cache/ms-playwright
rm -rf /root/.npm/_npx
rm -f frontend/tsconfig.tsbuildinfo
df -h /
```

If `disk_low` or `swap_active` remains after cleanup, record it as an operational risk. Do not treat it as a UI QA failure unless it causes page/API failure.

## Final Pass Criteria

- `impeccable` design QA has no P0/P1 issues.
- Playwright browser flows pass across required viewports.
- All screenshot artifacts exist and match the signed-off claims.
- `server_qa_all.sh --fast` passes.
- Mutation QA passes in `skill-qa` and cleans up.
- Admin/user/visitor permission boundaries pass.
- No raw execution JSON leaks into normal UI.
- Root disk has recovered after Playwright cleanup.
