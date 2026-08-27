# 프론트엔드 구현 가이드

대상 레포: `cloud_platform/frontend` (React 19 + Vite + TS, lucide-react, 순수 CSS)
디자인 소스: `Cloud Platform Console Redesign.dc.html` — 옵션 id(2a~2m)로 참조.

현재 `src/main.tsx` 2,747줄 / `src/styles.css` 2,418줄 단일 파일 구조. 한 번에 다 갈아엎지 말고 아래 순서로.

---

## 0단계 · 토큰 교체 (반나절, 시각적으로 가장 큰 변화)

`styles.css` 맨 위 `:root`만 교체한다. 클래스 이름은 그대로 두면 대부분 화면이 자동으로 새 톤을 입는다. (<a>2a</a>)

```css
:root{
  --ink:#0f1419; --text:#33404d; --muted:#6b7785; --faint:#949daa;
  --line:#e2e6ea; --line-strong:#cdd4dc; --line-soft:#eef0f2;
  --bg:#f6f7f8; --surface:#ffffff; --surface-sunk:#fafbfc;
  --primary:#2563eb; --primary-hover:#1d4ed8; --primary-soft:#f5f8fe;
  --ok:#067647; --ok-bg:#ecfdf3; --ok-line:#b7e4c7;
  --warn:#b45309; --warn-bg:#fffbeb; --warn-line:#f3dfa2;
  --danger:#b42318; --danger-bg:#fef3f2; --danger-line:#f3c4c0;
  --agent:#5b4bb8; --agent-bg:#f4f2fb; --agent-line:#ddd7f0;
  --r-xs:4px; --r-sm:6px; --r-md:8px;      /* 12px 이상 라운드 폐기 */
  --shadow:0 1px 2px rgba(15,20,25,.05);
  --shadow-pop:0 8px 24px rgba(15,20,25,.12);
  --shadow-modal:0 20px 52px rgba(15,20,25,.26);
}
```

동시에 정리할 것:
- 전역 `button{}` 규칙에서 `background:var(--primary)` 기본값을 **제거**한다. 현재는 모든 버튼이 파랑이라 위계를 만들 수 없다. 기본을 secondary(흰 배경 + `--line-strong`)로 두고 `.btnPrimary`, `.btnQuiet`, `.btnDanger`를 추가.
- `font-weight:750` → `600`.
- `--r-lg:12px`, `--r-pill:999px` 사용처를 전부 찾아 `--r-sm/--r-md`로 내린다. 상태 배지도 pill → `--r-xs`.
- 숫자·포트·URL에 `font-variant-numeric:tabular-nums` + mono 유틸 클래스(`.num`) 하나 만들어 붙인다.

## 1단계 · 컴포넌트 분리 (main.tsx 쪼개기)

지금 구조에서 새 위계를 넣으려면 파일 분리가 선행돼야 한다. 최소 단위로만:

```
src/
  App.tsx                 라우팅(page state) + 세션만
  lib/api.ts              api(), authHeaders, formatApiError  (기존 코드 그대로 이동)
  lib/format.ts           메모리·포트·시각 포맷터
  components/
    AppHeader.tsx         브랜드 + breadcrumb + 사용자/로그아웃
    ProjectIndex.tsx      2b — 서버 스트립 + 필터 + 프로젝트 표
    ServerStrip.tsx       2b/2l — 한 줄 가용량 + 접히는 상세
    ProjectWorkspace.tsx  2c — 헤더 메타 + 서비스 표
    ServiceRow.tsx        2c — 상태별 액션 결정 로직 포함
    ActionMenu.tsx         ···  오버플로 메뉴
    NewProjectModal.tsx   2m
    LoginModal.tsx        2j
    DeployForm.tsx        2i
    agent/AgentPanel.tsx  2d~2h 셸(레일/확장/전체화면)
    agent/Message.tsx     사용자·에이전트 메시지
    agent/ToolBlock.tsx   접히는 도구 사용 블록
    agent/ApprovalCard.tsx 2f (기존 코드 재사용, 스타일만 교체)
    agent/DeployQuestions.tsx 2g 되묻기
```

`ProjectAgentPanel`과 `AdminConsole`이 지금 거의 동일한 코드를 중복 보유한다 → 하나의 `AgentPanel`에 `scope: {kind:'project', name} | {kind:'root'}` prop으로 합치고, 엔드포인트(`/api/projects/:name/chat` vs `/api/admin/chat`)만 분기한다.

## 2단계 · 버튼 위계 (2c의 핵심)

`ServiceRow`에서 **상태로부터 가능한 동작을 계산**한다. 렌더 후 disabled로 막지 않는다.

```ts
type Status = 'running' | 'exited' | 'restarting';

function actionsFor(s: {status: Status; restartCount: number}) {
  if (s.status === 'exited')     return {primary:'start',  secondary:'logs',    menu:['redeploy','ports','env']};
  if (s.restartCount >= 5)       return {primary:'logs',   secondary:'stop',    menu:['restart','redeploy','ports','env']};
  return                                {primary:'logs',   secondary:'restart', menu:['stop','redeploy','ports','env']};
}
```

- `logs`는 quiet(테두리 없음), `restart`는 secondary, `redeploy`는 danger 색 + 승인 카드 필수, 나머지는 메뉴 안.
- 메뉴는 `<ActionMenu>`에서 native `<button aria-haspopup="menu">` + `role="menu"`로. 키보드: `↑↓`, `Esc`, `Enter`. 포커스 트랩 없이 `onBlurCapture`로 닫기.
- 파괴적 동작은 메뉴에서 바로 실행하지 않고 승인 카드(AI 패널)로 보낸다 — 이미 `/api/projects/:name/execute`가 `approved:true`를 요구하므로 계약 변경 없음.

## 3단계 · AI 패널 (2d~2h, 작업량 대부분)

### 3-1. 셸: 폭 3단계
```tsx
type PanelMode = 'rail' | 'wide' | 'full';   // 420px / 드래그 420~720 / 오버레이
```
- `rail`/`wide`: 워크스페이스 grid의 두 번째 트랙. 폭은 CSS 변수 `--rail-w`로 두고 드래그 핸들이 `pointermove`로 갱신 → `localStorage`에 저장.
- `full`: `position:fixed; inset:26px` 오버레이 + `rgba(15,20,25,.34)` 백드롭. **뒤 화면을 언마운트하지 않는다** — 워크스페이스는 그대로 살아 있고 스크롤 위치도 유지된다(2h). `Esc`로 닫기, `role="dialog" aria-modal="true"`, 열 때 포커스 이동/닫을 때 복귀.
- 전체화면에서 대화 컬럼은 `max-width:640px; margin:0 auto`.

### 3-2. 스트리밍
현재는 `fetch` 한 번으로 완성 응답을 받는다(`sendText`). 스트리밍 느낌을 내려면 백엔드가 필요하다:
- **서버 변경 가능하면**: `/api/projects/:name/chat`에 SSE(`text/event-stream`) 추가. 프론트는 `fetch` + `response.body.getReader()`로 청크를 이어 붙이며 `setMessages`.
- **서버를 못 건드리면**: 응답을 받은 뒤 `requestAnimationFrame`으로 20~30자/프레임씩 흘리는 타이핑 렌더. 시각적으로는 동일하고, 진행 표시(`로그 80줄 읽는 중…`)는 요청 시작 시점부터 보여준다. 나중에 SSE로 갈아끼울 수 있게 `useStreamedText(text, isStreaming)` 훅으로 격리.
- 커서는 `@keyframes` 하나(`0,49%{opacity:1} 50%,100%{opacity:0}`). `prefers-reduced-motion: reduce`면 커서·스피너 애니메이션을 끄고 정적 표시로.

### 3-3. 도구 사용 표시
백엔드가 이미 `data.context`와 `preview`를 돌려준다. 여기에 실행된 skill 이름을 담아 `ToolBlock`으로 렌더:
```tsx
<ToolBlock name="service.logs" summary="collector · 80줄" evidence={lines} />
```
접힌 상태가 기본. 펼치면 **정제된 근거 3줄**만. `JSON.stringify(preview)`를 그대로 뿌리는 현재 동작을 없앤다.

### 3-4. 되묻기 (2g)
`DeployGuideState`를 유지하되 카드 하나에 전 필드를 몰아넣지 않고, **미충족 필드 하나씩** 대화에 붙인다. 서버가 이미 `ui.missing`, `ui.field_errors`를 주므로:
```ts
const nextQuestion = ui?.missing?.[0];   // 이것만 렌더
```
답한 필드는 접힌 요약 줄(`✓ 이름 horse_api · 저장소 …  수정`)로 남긴다.
자동 감지 결과는 `제안 · 확인 필요` 배지 + `맞아요` 확인 버튼을 반드시 거친다 — 값이 채워진 채 확정된 것처럼 보이면 안 된다.

## 4단계 · 나머지 화면

| 화면 | 파일 | 메모 |
|---|---|---|
| 로그인 2j | `LoginModal.tsx` | 별도 라우트를 만들지 않는다. 비회원 홈이 진입점, 로그인은 모달. 성공 시 페이지 이동 없이 `setSession` → 목록만 다시 fetch |
| 새 프로젝트 2m | `NewProjectModal.tsx` | 주 버튼 = 생성 후 곧바로 `DeployForm` 열기 |
| 배포 폼 2i | `DeployForm.tsx` | 프레임워크 11종은 `deployment_presets.py`의 `category`(Frontend/Backend/Fullstack/Custom)로 그룹화 — 프론트에 하드코딩하지 말고 `/api/frameworks`로 받아오기 |
| 관리자 2l | `ProjectIndex.tsx` 재사용 | 새 화면이 아니다. `scope==='all'` 필터 + 소유자 열 + 서버 상세 펼침 + AI 범위에 `전체 서버` 추가. `AdminConsole` 컴포넌트는 삭제 |

## 5단계 · 상태 (2k)

- **로딩**: 스켈레톤은 실제 행 높이와 동일하게. `/api/system/summary`가 캐시로 0.1초대이므로 200ms 이내 응답이면 스켈레톤을 아예 띄우지 않는다(플래시 방지).
- **오류**: AI 실패가 조작 버튼을 막지 않는다 — 패널 안에서만 오류를 표시하고 `다시 시도` / `AI 없이 계속`.
- **권한 거부**: 누를 수 있는 버튼을 만들고 403을 받는 구조를 금지. 목록 응답의 멤버십 정보로 렌더 시점에 결정.
- **긴 이름/URL**: `min-width:0` + `overflow:hidden; text-overflow:ellipsis`, `title` 속성으로 전체값. 부모 flex/grid에 `min-width:0` 빠지면 안 잘린다.
- **좁은 화면**: `@media (max-width:820px)`에서 서비스 표 → 카드, AI 패널은 하단 고정 버튼 → 열면 `full` 모드.

## 접근성 체크 (머지 전)

- 모든 상태를 색 + 도형/텍스트로 이중 표시 (배지 안 점·사각형·막대).
- `:focus-visible` 아웃라인 유지 (현재 `outline:2px solid var(--info)` → `--primary`로).
- 대화 영역 `aria-live="polite"`, 스트리밍 중 중복 낭독 방지를 위해 완료된 메시지만 라이브 영역에 커밋.
- 한국어·영어 혼용: 본문 `line-height:1.55` 이상, 라벨 `1.4` 이상.

## 하지 말 것

- `styles.css` 한 파일에 새 클래스를 계속 append. 컴포넌트 분리와 함께 `components/*.css`로 co-locate.
- AI가 조작 버튼을 대체하는 방향. 안전한 동작은 표에서 바로 처리되어야 한다.
- 화면이 자기 기능을 설명하는 문장 추가. 지금 코드의 `subtitle`, `description` prop 상당수는 삭제 대상이다.
