# Handoff: Cloud Platform Console 재디자인

## Overview

기존 Cloud Platform Console(React + Vite 프론트엔드)의 **정보 위계와 버튼 위계를 재정립**하는 재디자인이다. 현재 화면의 문제는 셋이다.

1. **모든 버튼이 같은 무게** — 실행 중인 서비스에 "시작"이 파랑 강조로 남아 있고, `로그`(안전)와 `재배포`(파괴적)가 시각적으로 동일하다.
2. **AI 패널 폭 붕괴** — 300px 레일에 카드 3개를 가로로 넣어 "배포 요청서"가 2~4글자씩 잘려 내려간다.
3. **화면이 자기 기능을 해설** — 카드 3개 + 버튼 6개 + 설명 두 단락이 같은 진입점을 세 번 반복한다.

재디자인의 원칙: **파랑은 화면당 주 동작 1개에만**, **상태상 가능한 동작만 렌더**, **AI는 조작을 대체하지 않고 진단을 맡는다**.

## About the Design Files

이 번들의 `Cloud Platform Console Redesign.dc.html`은 **HTML로 만든 디자인 레퍼런스**다 — 의도한 외형과 동작을 보여주는 프로토타입이며, 그대로 복사해 넣을 프로덕션 코드가 아니다.

작업은 이 HTML 디자인을 **대상 코드베이스(`cloud_platform/frontend`, React 19 + Vite + TypeScript)의 기존 환경과 패턴으로 재구현**하는 것이다. 해당 레포는 이미 순수 CSS(`src/styles.css`)와 `lucide-react` 아이콘을 쓰고 있으므로 CSS 프레임워크를 새로 도입하지 말고 기존 방식을 따른다.

HTML 파일은 인라인 스타일로 작성돼 있다 — **값을 읽는 용도**이지 구조를 그대로 옮기라는 뜻이 아니다. 실제 구현은 `styles.css`의 토큰 + 클래스로 옮긴다.

## Fidelity

**High-fidelity (hifi)** — 최종 색상, 타이포그래피, 간격, 상태 표현이 모두 확정된 값이다. 픽셀 단위로 재현한다.

단, 다음은 hifi가 아니다:
- **아이콘**: HTML에서 유니코드 문자(`···`, `↗`, `⤢`, `✕`)로 대체했다. 구현 시 기존 `lucide-react`에서 대응 아이콘을 쓴다 (`MoreHorizontal`, `ArrowUpRight`, `Maximize2`, `X`).
- **데이터**: 표시된 프로젝트명·수치는 실제 서버 응답 예시다. API에서 받아온다.

## Screens / Views

디자인 파일은 두 개 턴으로 구성된다. **아래쪽 턴 1은 현재 상태 재현(비교용, 구현 대상 아님)**, **위쪽 턴 2가 구현 대상**이다.

---

### 2a · Design tokens

구현 대상 화면이 아니라 값 명세서다. 아래 "Design Tokens" 절 참조.

---

### 2b · 프로젝트 인덱스 (홈)

**Purpose** — 로그인 후 첫 화면. 어느 프로젝트에 문제가 있는지 즉시 판별하고 진입한다.

**Layout**
- 폭 1320px 기준 (max-width 없이 유동, 콘텐츠 좌우 패딩 26px)
- 헤더: `height:52px`, `background:#fff`, `border-bottom:1px solid #e2e6ea`, 좌우 패딩 26px
- 본문: `padding:28px 26px 34px`, `background:#f6f7f8`

**Components**

1. **헤더**
   - 브랜드: 22×22 로고(`background:#0f1419`, `border-radius:5px`) + `Cloud Platform` (600/14px, `#0f1419`, `letter-spacing:-.01em`), gap 11px
   - 우측: 사용자명(600/12.5px `#1c242d`) + ADMIN 배지 + 로그아웃(500/12.5px `#6b7785`), gap 16px
   - ADMIN 배지: `height:19px`, `padding:0 6px`, `background:#f4f2fb`, `border:1px solid #ddd7f0`, `border-radius:4px`, 600/10.5px mono, `#5b4bb8`

2. **타이틀 행** — `display:flex; align-items:center; justify-content:space-between; margin-bottom:16px`
   - `프로젝트` 600/24px `#0f1419` `letter-spacing:-.015em`
   - 필터 세그먼트(gap 14px): `border:1px solid #cdd4dc; border-radius:6px; overflow:hidden`
     - **`전체 프로젝트`가 기본 선택이며 앞에 온다** — `height:30px; padding:0 12px; background:#1c242d; color:#fff; 600/12.5px`, 카운트는 `11.5px mono; opacity:.7`
     - `내 프로젝트` — 비활성, `color:#6b7785`, 카운트 `#a3aab4`, `border-left:1px solid #cdd4dc`
   - 우측 `새 프로젝트` — primary 버튼, `height:34px; padding:0 14px`

3. **서버 스트립** — 한 줄로 압축. `padding:13px 18px`, `background:#fff`, `border:1px solid #e2e6ea`, `border-radius:8px 8px 0 0`, `border-bottom:none`, 항목 간 gap 22px
   - 라벨 `서버`: 600/10.5px mono, `letter-spacing:.08em`, `#8a929c`
   - 각 지표: 라벨(500/12.5px `#6b7785`) + 막대(88×5px, `background:#e8ebee`, `border-radius:3px`, 채움 `#6b7785`) + 값(600/12.5px mono, tabular-nums)
   - 디스크가 임계치 초과 시 채움과 값 모두 `#b42318`
   - 우측 끝: `가용 포트 9002–9100`

4. **경고 배너** (조건부) — `padding:12px 18px`, `background:#fef3f2`, `border:1px solid #f3c4c0`, radius 없음(스트립과 표 사이에 끼움)
   - 아이콘 15×15 원 `#b42318`, 흰 `!`
   - 본문 13px/1.5 `#7f1d1a`, 수치는 600
   - 우측 `정리 대상 보기` — danger secondary, `height:28px`

5. **프로젝트 표** — `background:#fff`, `border:1px solid #e2e6ea`, `border-top:none`, `border-radius:0 0 8px 8px`
   - 그리드: `1fr 96px 168px 150px 82px`, gap 16px
   - 헤더 행: `padding:9px 18px`, `background:#fafbfc`, `border-bottom:1px solid #e2e6ea`, 600/10.5px mono `letter-spacing:.07em` `#8a929c`
   - 데이터 행: `padding:15px 18px 15px 16px`, `border-bottom:1px solid #eef0f2`
   - **좌측 상태 바**: `border-left:2px solid` — 정상 `transparent`, 주의 `#f3dfa2`, 위험 `#b42318`. 위험 행은 `background:#fffdfd`
   - 프로젝트명 600/15px `#0f1419` + 상태 배지, 그 아래 12.5px/1.4 보조 줄(정상이면 서비스명 나열 `#6b7785`, 문제면 원인 요약 `#b42318`/`#b45309`)
   - 실행: 600/13px mono tabular-nums. `0/0`이면 `#949daa`
   - 메모리: 막대 56×4px + 값. 값 없으면 `—` (`#949daa`)
   - 행동: `열기` secondary `height:30px`, 우측 정렬

**States** — 로딩 시 스켈레톤(2k), 프로젝트 0개면 빈 상태.

---

### 2c · 프로젝트 워크스페이스

**Purpose** — 한 프로젝트의 서비스를 보고 조작한다. 재디자인의 중심 화면.

**Layout** — `display:grid; grid-template-columns:1fr 420px`
- 좌: `padding:26px 26px 40px`
- 우(AI 레일): `border-left:1px solid #e2e6ea`, `background:#fff`, flex column

**Components**

1. **Breadcrumb** — 뒤로가기 버튼 대신 헤더에 경로로. `Cloud Platform / 프로젝트 / demoa`
   - 구분자 `/` `#cdd4dc`, 링크 500/13px `#6b7785`, 현재 위치 600/13px `#1c242d`
   - **별도의 `← 프로젝트` 버튼, `프로젝트 목록` 버튼, `새로고침` 버튼을 두지 않는다**

2. **페이지 헤더** — 3개 요약 카드를 **한 줄 메타**로 압축
   - 제목 600/26px `#0f1419` `letter-spacing:-.02em`
   - 메타 줄(margin-top 9px, gap 14px, 12.5px `#6b7785`, 구분자 `·` `#dfe3e7`):
     `● 서비스 2개 모두 실행 중` · `메모리 12.8MB / 961.6MB (1.3%)` · `마지막 배포 기록 없음`
   - 점: 6×6 원 `#067647`
   - 우측: `새 서비스 배포` primary `height:34px`

3. **서비스 표** — 그리드 `1fr 122px 116px 172px 186px`, gap 14px
   - 헤더/행 스타일은 2b와 동일
   - **포트**: `9000→3000` (호스트→컨테이너). 공개 URL이 없으면 `3000`만. **"내부 통신" 같은 채움 텍스트를 쓰지 않는다**
   - **메모리**: 막대 52×4px + `9.3MB · 1%`
   - 문제 행은 `background:#fffdfd`, 서비스명 옆에 `재시작 13회` (500/11.5px `#b42318`)

4. **행 액션 — 상태 기반 (핵심)**
   
   | 상태 | primary | secondary | `···` 메뉴 |
   |---|---|---|---|
   | 실행 중 | `로그` (quiet) | `재시작` | 중지, 재배포, 포트 변경, 환경변수 |
   | 중지됨 | `시작` (primary blue) | `로그` | 재배포, 포트 변경, 환경변수 |
   | 재시작 반복(≥5) | `로그 보기` (primary blue) | `중지` | 재시작, 재배포, 포트 변경, 환경변수 |
   
   - 버튼 높이 30px, gap 7px, 우측 정렬
   - **실행 중인 서비스에 `시작`을 렌더하지 않는다** — disabled로도 두지 않는다
   - `···` 버튼: 30×30, secondary. 열리면 `background:#1c242d; color:#fff`

5. **오버플로 메뉴** — `width:196px`, `padding:5px`, `background:#fff`, `border:1px solid #d3d8de`, `border-radius:8px`, `box-shadow:0 8px 24px rgba(15,20,25,.12)`
   - 섹션 헤더: `padding:6px 9px 4px`, 600/10.5px mono `letter-spacing:.07em` `#949daa` — `설정`, `중단·교체`
   - 항목: `padding:7px 9px`, `border-radius:5px`, 500/13px `#33404d`. hover `background:#f6f7f8`
   - 항목 우측에 위험도 힌트: `가역` / `승인 필요` (11px mono `#949daa`)
   - `재배포`는 600/13px `#b42318`, 힌트 `#c98d87`
   - 구분선 `height:1px; background:#eef0f2; margin:5px 0`

6. **AI 레일** — 아래 2d~2h 참조. 좌측 가장자리에 `width:5px; cursor:col-resize` 드래그 핸들.

---

### 2d · AI 패널 · 빈 상태

**Purpose** — 첫 진입. 무엇을 물어볼 수 있는지만 보여준다.

- 패널 헤더 `padding:14px 16px`, `border-bottom:1px solid #eef0f2`
  - AI 뱃지 20×20 `background:#f4f2fb; border:1px solid #ddd7f0; border-radius:5px`, 700/10px `#5b4bb8`
  - 제목 600/13px `운영 AI`, 부제 11.5px `#6b7785` `demoa 범위 · 변경은 승인 후 실행`
  - 우측 아이콘 버튼 26×26 `border:1px solid #e2e6ea; border-radius:5px` — 확장, 닫기
- 본문: `justify-content:flex-end` — 제안이 입력창 바로 위에 붙는다
  - 라벨 `시작해볼 것` 600/10.5px mono `letter-spacing:.08em` `#a3aab4`, margin-bottom 12px
  - 제안 3줄: `padding:11px 2px`, `border-top:1px solid #eef0f2`, 14px `#33404d`, 우측 `↗` `#c4cad1`. 마지막 줄 아래에도 border-top div 하나
  - 카드도 버튼도 아니다 — **목록**이다
- 입력창: `border:1px solid #cdd4dc; border-radius:8px; padding:10px 11px`, placeholder 14px `#a3aab4`, 전송 28×28 `border-radius:6px` (빈 상태에서는 `#eef0f2`/`#a3aab4` 비활성)
- 입력창 아래 각주 11.5px `#a3aab4`: `시작·중지·로그는 서비스 표에서 바로 누르는 게 빠릅니다.`

**구 디자인에서 제거된 것**: 상단 카드 3개(배포 요청서/상태 요약/운영 확인), 하단 카테고리 버튼 6개, 설명 두 단락.

---

### 2e · AI 패널 · 진행 표시 → 도구 사용 → 스트리밍

**메시지 스타일**
- 사용자: `align-self:flex-end`, `max-width:82%`, `padding:9px 12px`, `background:#f1f3f5`, `border-radius:8px 8px 3px 8px`, 14px/1.55 `#1c242d`
- 에이전트: 말풍선 없음. 본문 14px/1.6 `#33404d`, 폭 제한 없음
- 메시지 간 gap 16px

**도구 사용 블록 (접힘)** — `display:inline-flex`, `padding:5px 9px`, `border:1px solid #e6e9ec`, `border-radius:6px`, `background:#fafbfc`, 11.5px `#6b7785`
- 도구명은 11px mono `#5b4bb8`, 그 뒤 `실행함 · collector · 80줄`
- 우측 `▾` `#b0b7c0`

**도구 사용 블록 (펼침)** — `border-radius:7px`, 헤더 `padding:7px 10px` + `▴`, 본문 `border-top:1px solid #eef0f2`, `padding:9px 11px`, `background:#fff`
- `근거 3줄` 라벨 600/10.5px mono `#a3aab4`
- 로그 라인 12px/1.7 mono `#4b5565`, 타임스탬프 `#b0b7c0`
- **`JSON.stringify(preview)`를 그대로 노출하지 않는다** — 정제된 3줄만

**진행 표시** — 응답이 들어올 자리에 먼저 나타나고 결과로 교체된다
- 스피너 13×13, `border:1.6px solid #dfe3e7`, `border-top-color:#5b4bb8`, `border-radius:50%`, `animation: spin .8s linear infinite`
- 텍스트 13px `#6b7785` — `로그 80줄 읽는 중…` (무엇을 하는지 명시)

**스트리밍 커서** — `display:inline-block; width:7px; height:15px; background:#33404d; vertical-align:-3px; margin-left:2px`, `animation: cur 1s step-end infinite` (`0,49%{opacity:1} 50%,100%{opacity:0}`)

**인라인 코드** — 12.5px mono, `background:#f1f3f5`, `padding:1px 4px`, `border-radius:3px`. 오류 관련 값은 `color:#b42318`

**전송 버튼** — 응답 중에는 **중지**로 바뀐다: `background:#1c242d`, 안에 9×9 흰 사각형(`border-radius:1.5px`)

---

### 2f · AI 패널 · 승인 카드

**Purpose** — 파괴적 동작 실행 전 확인. **대화 흐름 안의 카드**이며 모달로 튀어나오지 않는다.

- 컨테이너: `border:1px solid #e6c9c5`, `border-radius:8px`, `overflow:hidden`
- 헤더: `padding:10px 13px`, `background:#fef7f6`, `border-bottom:1px solid #f3dedb`
  - 좌: `파괴적 · 승인 필요` 600/10.5px mono `letter-spacing:.07em` `#b42318`
  - 우: `승인 대기` 600/11.5px `#8a929c`
- 본문 `padding:13px 14px 15px`
  - 제목 600/15px `#0f1419` — `demo-b 재배포`
  - 명세 그리드 `66px 1fr`, gap `7px 12px`, 12.5px/1.45. 라벨 `#8a929c`, 값 `#1c242d`
    - `대상` / `저장소`(mono, `word-break:break-all`) / `유지`(포트·환경변수)
  - 구분선 `height:1px; background:#f0e5e3; margin:13px 0`
  - 2열 그리드 gap 14px:
    - `위험` 600/11px `#b42318` + 12.5px/1.55 `#4b5565` — 다운타임, 롤백 가능 여부
    - `예상 결과` 600/11px `#4b5565` + 동일 본문 — 단계, 디스크 사용량
  - 액션(margin-top 15px, gap 9px): `승인하고 재배포` **danger primary** (`background:#b42318`, 흰 글자, height 32px) / `취소` secondary / 우측 끝 컨텍스트 11.5px `#a3aab4` (`디스크 여유 394.8MB`)

**Rule** — 파괴적 동작은 표의 `···` 메뉴에서 바로 실행되지 않고 항상 이 카드를 거친다. 백엔드 `/api/projects/:name/execute`가 이미 `approved:true`를 요구하므로 API 계약 변경 없음.

---

### 2g · AI 패널 · 배포 되묻기

**Purpose** — 대화로 배포 정보를 수집. 폼이 대화를 가로막지 않는다.

- 헤더 부제가 진행률로: `demoa 범위 · 3/4 단계`
- **답변 완료 요약** — `padding:8px 11px`, `border:1px solid #eef0f2`, `border-radius:7px`, `background:#fafbfc`, 12.5px `#4b5565`
  - 좌측 체크 14×14 원 `#067647` 흰 `✓`
  - 값은 600 `#1c242d`, 우측 끝 `수정` 11.5px `#8a929c`
- **제안 카드** — `border:1px solid #dbe3f2; border-radius:8px`
  - 헤더 `padding:8px 12px`, `background:#f5f8fe`, `border-bottom:1px solid #e4ebf7`, 라벨 `제안 · 확인 필요` 600/10.5px mono `#2563eb`
  - 본문: 선택된 프레임워크 박스 `border:1.5px solid #2563eb`, `padding:9px 11px` — 이름 600/13.5px + 런타임/포트 11.5px `#6b7785`
  - 우측 `맞아요` primary `height:32px`
  - 아래 대안 칩: `아니면` 라벨 + 칩 3개 + `전체 11종 ▾`. 칩 `height:26px; padding:0 10px; border:1px solid #cdd4dc; border-radius:5px; 500/12px`
- **한 번에 하나만 묻는다** — 서버가 주는 `ui.missing[0]`만 렌더
- 입력창은 활성 상태 표현: `border:1px solid #2563eb`, 입력 텍스트 `#1c242d`, 전송 버튼 `#2563eb`
- 각주: `이름만 보냅니다. 실제 값은 배포 후 환경변수 화면에서 입력합니다.`

---

### 2h · AI 패널 폭 3단계

**Purpose** — 420px에서 잘리는 텍스트 문제의 구조적 해결.

**모드**
1. `rail` — 420px, 워크스페이스 그리드의 두 번째 트랙 (기본)
2. `wide` — 좌측 핸들 드래그로 420~720px, `localStorage` 저장
3. `full` — **오버레이**

**전체화면 오버레이 명세**
- **뒤 화면을 언마운트하지 않는다.** 워크스페이스가 그대로 살아 있고 `Esc`/닫기로 돌아가면 스크롤 위치까지 유지된다
- 백드롭: 헤더 아래 영역에 `background:rgba(15,20,25,.32)`. 뒤 콘텐츠는 `opacity:.5`로 비쳐 보인다
- 패널: `position:fixed; left:26px; right:26px; top:76px; bottom:26px`, `background:#fff`, `border:1px solid #d3d8de`, `border-radius:10px`, `box-shadow:0 18px 48px rgba(15,20,25,.22)`
- 패널 헤더 `height:48px`, `padding:0 18px`:
  - AI 뱃지 + `운영 AI` 600/13.5px + 범위 배지(`demoa`, `height:21px`, `background:#f6f7f8`, `border:1px solid #e2e6ea`, `border-radius:4px`, 600/11.5px `#4b5565`)
  - 우측: **`실행한 변경 0건` 칩** (`height:24px; padding:0 9px; border:1px solid #e2e6ea; border-radius:5px; 500/11.5px #6b7785` + `▾`) / `축소 ⤡` / `닫기 ESC`
- **사이드바 없음.** 범위 설명·도구 목록을 좌측 칼럼으로 두지 않는다 — 범위는 배지 하나로 충분하고 도구 실행 내역은 대화 안 인라인 블록에 이미 있다
- `실행한 변경 N건`은 **승인해서 실제로 실행된 것만** 센다. 조회는 기록하지 않는다
- 대화 컬럼: `width:640px; margin:0 auto`. 본문 14.5px/1.7, 사용자 말풍선 `max-width:74%`
- 번호 목록: 18×18 사각 뱃지(`border-radius:4px`), 위험도 색 배경(`#fef3f2`/`#fffbeb`), 700/10px

**A11y** — `role="dialog" aria-modal="true"`, 열 때 포커스 이동/닫을 때 복귀, `Esc` 닫기.

---

### 2i · 새 서비스 배포 (직접 경로)

**Purpose** — AI를 거치지 않는 폼 경로. 안전한 동작이므로 승인 절차 없음.

**Layout** — `display:grid; grid-template-columns:1fr 296px; gap:24px`, `padding:26px 24px 32px`

**좌측 폼** — `background:#fff; border:1px solid #e2e6ea; border-radius:8px; padding:20px 20px 22px`
- 필드 라벨 600/12px `#33404d`, margin-bottom 6px
- 입력 `height:36px; border:1px solid #cdd4dc; border-radius:6px; padding:0 11px`, 값은 13.5px (URL·포트는 mono)
- 헬프 텍스트 11.5px `#949daa` (성공은 `#067647`)
- 검증 성공 아이콘: 14×14 원 `#067647` 흰 `✓`
- 구분선 `height:1px; background:#eef0f2; margin:20px 0`

**프레임워크 선택** — 11종을 카테고리로 그룹화
- 라벨 옆 제안 배지: `저장소 분석 결과 FastAPI 제안 · 확인 필요`, `height:19px`, `background:#f5f8fe`, `border:1px solid #dbe3f2`, 600/10.5px `#2563eb`
- 카테고리 헤더 `BACKEND` / `FRONTEND · CUSTOM`: 600/10.5px mono `letter-spacing:.07em` `#a3aab4`
- 칩 `height:30px; padding:0 12px; border:1px solid #cdd4dc; border-radius:6px; 500/12.5px #33404d`, gap 8px, wrap
- 선택된 칩: `border:1.5px solid #2563eb; background:#f5f8fe; 600 #1e3a8a` + `제안` 라벨(10.5px mono `#2563eb`)
- **카테고리는 프론트에 하드코딩하지 말고 `deployment_presets.py`의 `category` 값을 API로 받는다**

**외부 접속** — 세그먼트 컨트롤 `웹 공개` / `내부 전용`. 선택 `background:#1c242d; color:#fff`
**호스트 포트** — 자동 추천값 + 우측 힌트 `자동 추천 · 9000–9100`
**환경변수 이름** — 칩 입력. 칩 `height:22px; padding:0 8px; background:#f1f3f5; border-radius:4px; 11.5px mono` + `✕`. 각주: `값은 배포 후 환경변수 화면에서 입력합니다. 요청에 비밀값을 담지 않습니다.`

**우측 요약 (sticky)** — `position:sticky; top:0`
- `실행 계획` 라벨 → 명세 그리드 `60px 1fr`
- `진행 순서` 3줄 12.5px/1.4 `#6b7785`
- 디스크 경고 `padding:10px 11px; background:#fffbeb; border:1px solid #f3dfa2; border-radius:6px; 12px/1.5 #8a5a08`
- `배포 실행` primary `width:100%; height:36px`

---

### 2j · 로그인 · 비회원 홈

**Purpose** — 로그인 퍼널을 늘리지 않는다.

**핵심 결정**
- **별도 로그인 페이지(라우트)를 만들지 않는다.** 진입점은 항상 홈이다
- 로그인 안 한 사람에게는 **같은 홈이 공개 범위로** 보인다 — 공개 URL이 있는 프로젝트의 이름과 바로가기, 서버 가용량까지만
- 로그인은 헤더 버튼 → **같은 화면 위 모달**. 성공하면 페이지 이동 없이 그 자리에서 목록이 채워진다

**비회원 홈**
- 헤더 우측: `로그인` 버튼 `background:#1c242d; color:#fff; height:30px`
- 타이틀 옆 `공개 범위` 배지 `height:22px; background:#f1f3f5; border:1px solid #e2e6ea; border-radius:4px; 600/11px mono #6b7785`
- 서버 스트립은 그대로 (메모리·디스크만)
- 목록 행: 프로젝트명 600/15px + `공개 서비스 1개` 12.5px `#6b7785` + 우측 바로가기 링크
- **서비스 상태·메모리·조작·AI는 목록에 존재하지 않는다** — 잠긴 버튼을 보여주고 누른 뒤에 막지 않는다

**로그인 모달**
- 백드롭 `rgba(15,20,25,.34)`
- 모달 `width:352px; top:78px`, `background:#fff; border:1px solid #d3d8de; border-radius:10px; box-shadow:0 20px 52px rgba(15,20,25,.26); padding:22px 22px 20px`
- 제목 600/15.5px + 우측 `✕`
- 입력 `height:36px`, 오류 시 `border:1.5px solid #b42318`
- 오류 메시지: 14×14 원 아이콘 + 12.5px/1.5 `#b42318`. **잠금 정책을 미리 알린다** — `5회 실패하면 10분 잠깁니다. (2/5)`
- `로그인` primary `width:100%; height:38px`
- 각주 11.5px `#949daa` 중앙: `닫으면 지금 보던 공개 목록으로 돌아갑니다.`

---

### 2k · 상태 (로딩/빈/오류/권한/긴 텍스트/좁은 화면)

**로딩 스켈레톤** — 실제 행 높이와 동일하게. 막대 `border-radius:3px`, 강한 `#eef0f2` / 약한 `#f3f5f6`
- 각주로 무엇을 기다리는지: `Docker stats를 읽는 중입니다 · 3초 넘으면 캐시된 값을 먼저 보여줍니다`
- **200ms 이내 응답이면 스켈레톤을 띄우지 않는다** (플래시 방지)

**빈 상태** — `padding:34px 0 30px; text-align:center`
- 34×34 `border:1.5px dashed #cdd4dc; border-radius:7px`
- 제목 600/15px, 설명 13px/1.6 `#6b7785`, 주 동작 하나만

**오류 · AI 무응답** — `padding:13px 14px; background:#fef7f6; border:1px solid #f3c4c0; border-radius:7px`
- 제목 600/13.5px `#7f1d1a`, 본문 12.5px/1.6 `#8a4441`
- **AI 실패가 조작을 막지 않음을 명시**: `서비스 상태와 조작 버튼은 정상 동작합니다.`
- `다시 시도` danger secondary / `AI 없이 계속` quiet

**연결 끊김** — `background:#fffbeb; border:1px solid #f3dfa2`, 12.5px/1.55 `#8a5a08`. **마지막 확인 시각을 명시**

**권한 거부** — 누를 수 있는 버튼을 만들고 403을 받는 구조를 금지. 목록 응답의 멤버십 정보로 **렌더 시점에** 결정
- 비멤버 행: 보조 줄 `멤버가 아닙니다`, 우측 `접근 요청` 링크 + disabled `열기` (`background:#f1f3f5; border:1px solid #e2e6ea; color:#a3aab4`)

**긴 이름 · URL** — 부모에 `min-width:0`, 자식에 `white-space:nowrap; overflow:hidden; text-overflow:ellipsis`, `title` 속성으로 전체값
- `min-width:0`이 빠지면 flex/grid 자식이 축소되지 않아 잘리지 않는다 — 필수

**좁은 화면 (`@media (max-width:820px)`)** — 서비스 표 → 카드
- 카드 `padding:13px 14px; border:1px solid #e2e6ea; border-radius:8px`, 간격 10px
- 액션은 `flex:1` 풀폭 버튼 `height:34px` (터치 타겟), `···`만 44px 고정폭
- AI는 하단 고정 버튼 → 열면 `full` 모드

---

### 2l · 관리자 (= 같은 홈의 넓은 범위)

**Purpose** — 관리자 전용 화면을 새로 만들지 않는다. **권한은 같은 UI의 범위 스위치**다.

2b와 **동일한 구조**이며 admin일 때 세 가지만 달라진다:

1. **소유자 열 추가** — 그리드가 `1fr 108px 88px 158px 140px 82px`로 바뀌고 `소유자` 열(12.5px `#1c242d`)이 들어간다
2. **서버 스트립이 상세로 펼쳐진다** — 스트립 우측에 `상세 접기 ▴`, 아래에 4열 그리드(`border-top:1px solid #eef0f2; background:#fafbfc`)
   - 각 칸 `padding:11px 18px`, `border-right:1px solid #eef0f2`
   - 라벨 600/10.5px mono `#a3aab4`, 값 600/14px mono
   - `디스크 여유 394.8MB` / `스왑 534.6MB`(`#b45309`) / `가용 포트 9002–9100` / `Docker 연결됨`(`#067647`)
3. **AI 범위 선택에 `전체 서버` 추가** — 목록 하단 한 줄 카드
   - `padding:12px 16px; background:#fff; border:1px solid #e2e6ea; border-radius:8px`, gap 12px
   - AI 뱃지 + `운영 AI` 600/13px + 세그먼트(`프로젝트 선택` / `전체 서버`) + 우측 `열기`
   - `전체 서버` 선택 시 `background:#f4f2fb; color:#5b4bb8`

**제거 대상** — 기존 `AdminConsole` 컴포넌트. `ProjectIndex`의 `scope==='all'` 분기로 흡수한다.

**하지 말 것** — "admin 권한으로 남의 프로젝트까지 표시" 같은 해설 배지, "타인 소유" 배지. 소유자 열 하나로 충분하다.

---

### 2m · 새 프로젝트

**Purpose** — 화면을 이동하지 않는다. 프로젝트는 껍데기이므로 만든 직후 할 일은 항상 첫 서비스 배포다.

**모달** — `width:360px; top:70px`, 2j와 동일한 모달 스타일
- 이름 입력 + 검증 체크 아이콘
- 헬프: `소문자·숫자·밑줄 · 나중에 바꿀 수 없습니다`
- **주 버튼 `만들고 서비스 배포`** primary `height:38px` → 생성 후 곧바로 2i 폼을 연다
- 보조 `만들기만` secondary `height:34px` → 빈 프로젝트 워크스페이스

**생성 직후 상태** — 빈 상태(2k) + `방금 만들어짐` 12.5px `#6b7785`

---

## Interactions & Behavior

**네비게이션**
- 프로젝트 진입/이탈은 breadcrumb으로. 뒤로가기 버튼을 화면에 두지 않는다
- 모달(로그인, 새 프로젝트)은 라우트를 만들지 않는다 — 배경 화면이 유지된다
- AI 전체화면도 라우트가 아니다 — 오버레이

**애니메이션** — 최소한으로
- 스피너: `spin .8s linear infinite`
- 스트리밍 커서: `cur 1s step-end infinite`
- 그 외 transition은 `120ms ease` 이내 (hover 색상 변화 정도)
- `@media (prefers-reduced-motion: reduce)`에서 스피너·커서 애니메이션을 정적 표시로 대체

**Hover**
- secondary 버튼: `border-color:#b0b7c0`, `background:#fafbfc`
- quiet 버튼: `background:#f1f3f5`
- 표 행: hover 배경 없음 (행 자체는 클릭 대상이 아니다 — `열기` 버튼이 진입점)
- 메뉴 항목: `background:#f6f7f8`

**폼 검증**
- 서비스/프로젝트 이름: 소문자·숫자·밑줄. blur 시 검증, 성공하면 `✓`
- GitHub URL: blur 시 접근 가능 여부 확인 → `공개 저장소 확인됨` 또는 오류
- 포트: 9000–9100 범위, 충돌 검사. 자동 추천값을 미리 채운다
- 오류는 필드 아래 12.5px `#b42318` + 아이콘. 폼 상단 요약 배너를 쓰지 않는다

**파괴적 동작 게이트**
- `재배포`는 언제나 승인 카드(2f)를 거친다
- `중지`는 가역이므로 인라인 확인(`정말 중지할까요?` 토스트 수준)으로 충분
- 메뉴 항목에 위험도를 `가역` / `승인 필요`로 표기

## State Management

```ts
// 세션
session: {user, role: 'admin'|'member', token} | null

// 목록
scope: 'all' | 'mine'              // 기본 'all'
projects: Project[]
serverSummary: {containers, memory, disk, swap, portRange}
serverDetailOpen: boolean          // admin만

// 워크스페이스
currentProject: string | null
services: Service[]                // status, restartCount, ports, memory
openMenuFor: string | null         // 열린 ··· 메뉴의 서비스 id

// AI 패널
panelMode: 'rail' | 'wide' | 'full'
railWidth: number                  // 420~720, localStorage 저장
messages: Message[]                // {from, text, tools?: ToolCall[]}
isStreaming: boolean
progressLabel: string | null       // "로그 80줄 읽는 중…"
pendingApproval: ApprovalPlan | null
deployGuide: DeployGuideState | null

// 모달
modal: 'login' | 'newProject' | null
```

**전환**
- `panelMode: 'full'` 진입 시 `document.body`의 스크롤을 잠그되 **워크스페이스 컴포넌트는 언마운트하지 않는다**
- 스트리밍 중 전송 버튼 → 중지. `AbortController`로 취소
- 승인 카드 확정 → `POST /api/projects/:name/execute {approved:true}` → 성공 시 카드가 결과 요약으로 교체되고 `실행한 변경 N건` 증가

**데이터 페칭**
- 목록 진입 시 `/api/projects` + `/api/system/summary` 병렬
- 워크스페이스는 `/api/projects/:name` (서비스 목록 포함)
- 서비스 상태는 폴링보다 조작 직후 리페치 우선. 폴링한다면 10초 이상 간격

## Design Tokens

### Color

| 역할 | 값 | 용도 |
|---|---|---|
| ink | `#0f1419` | 제목 |
| text | `#33404d` | 본문 |
| muted | `#6b7785` | 보조·라벨 |
| faint | `#949daa` | 각주·비활성 텍스트 |
| line | `#e2e6ea` | 기본 경계 |
| line-strong | `#cdd4dc` | 입력·버튼 경계 |
| line-soft | `#eef0f2` | 행 구분선 |
| bg | `#f6f7f8` | 페이지 배경 |
| surface | `#ffffff` | 카드·표 |
| surface-sunk | `#fafbfc` | 표 헤더·보조 블록 |
| primary | `#2563eb` | **화면당 주 동작 1개** |
| primary-soft | `#f5f8fe` | 제안 배경 |
| ok | `#067647` / bg `#ecfdf3` / line `#b7e4c7` | 정상 |
| warn | `#b45309` / bg `#fffbeb` / line `#f3dfa2` | 주의 |
| danger | `#b42318` / bg `#fef3f2` / line `#f3c4c0` | 위험·파괴적 |
| agent | `#5b4bb8` / bg `#f4f2fb` / line `#ddd7f0` | **AI 범위 표시에만** |

### Typography

Pretendard, "Noto Sans KR", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif

| 이름 | 값 |
|---|---|
| display | 600 / 32px / 1.1 / `-.02em` |
| title | 600 / 21~26px / 1.2 / `-.015em` |
| strong | 600 / 15px / 1.35 — 행 제목·서비스명 |
| body | 400 / 14px / 1.55 — 본문·대화 |
| meta | 500 / 12.5px / 1.4 — 라벨·보조 |
| micro | 600 / 10.5px mono / `+.08em` / uppercase — eyebrow·열 머리 |
| numeric | 500 / 13px mono + `tabular-nums` — **숫자·포트·URL은 항상** |

전체화면 대화는 본문 14.5px / 1.7.

### Spacing

4px 기반: `4 · 8 · 12 · 16 · 24 · 32 · 48`

### Radius

`4px` (배지·칩) / `6px` (버튼·입력) / `8px` (카드·표) / `10px` (모달·오버레이)
**12px 이상 라운드와 pill(999px)을 쓰지 않는다.**

### Shadow

| 이름 | 값 |
|---|---|
| shadow | `0 1px 2px rgba(15,20,25,.05)` |
| shadow-pop | `0 8px 24px rgba(15,20,25,.12)` — 드롭다운 |
| shadow-modal | `0 20px 52px rgba(15,20,25,.26)` — 모달 |
| shadow-overlay | `0 18px 48px rgba(15,20,25,.22)` — 전체화면 패널 |

### Button

| 종류 | 스타일 | 용도 |
|---|---|---|
| primary | `bg #2563eb`, 흰 글자, `border 1px solid #2563eb` | 화면당 1개 |
| secondary | `bg #fff`, `#1c242d`, `border 1px solid #cdd4dc` | 가역적 동작 |
| quiet | 투명, `#4b5565`, 테두리 없음 | 안전·조회 |
| danger | `bg #fff`, `#b42318`, `border 1px solid #e6c9c5` | 파괴적 (확인 필수) |
| danger-solid | `bg #b42318`, 흰 글자 | 승인 카드의 확정 버튼 |
| overflow | 30×30 정사각, secondary. 열리면 `bg #1c242d` | 나머지 전부 |
| disabled | `bg #f1f3f5`, `#a3aab4`, `border 1px solid #e2e6ea` | 상태상 불가 |

높이: 표 행 30px / 페이지 헤더 34px / 폼 36~40px / 좁은 화면 34px 이상
폰트: 600 / 12.5~13.5px

**위계 규칙**: 로그(안전) < 재시작 < 중지 < 재배포(파괴적) — 시각적 무게가 이 순서를 따른다.

### Status Badge

`height:23px; padding:0 9px 0 8px; border-radius:4px`, 600/11.5px, 좌측에 6px 도형 + gap 6px

| 상태 | 색 | 도형 |
|---|---|---|
| 실행 중 | `#067647` / `#ecfdf3` / `#b7e4c7` | 원 |
| 재시작 반복 | `#b45309` / `#fffbeb` / `#f3dfa2` | 45° 회전 사각 |
| 중지됨 | `#b42318` / `#fef3f2` / `#f3c4c0` | 가로 막대 7×2 |
| 헬스체크 없음 | `#6b7785` / `#f6f7f8` / `#e2e6ea` | 빈 원(테두리) |

**색 단독으로 상태를 표현하지 않는다** — 도형과 텍스트를 함께 쓴다.
배지는 **컨테이너 상태 하나만** 담는다. 헬스는 정상 범위를 벗어날 때만 별도 표시.

### 값이 없을 때

**칸을 비우거나 `—`(`#949daa`)를 쓴다.** "내부 통신" 같은 채움 텍스트를 넣지 않는다 — 공개 URL 없음은 그 자체로 정보다.

## Assets

외부 이미지 없음. 아이콘은 유니코드 문자로 대체돼 있으므로 **기존 `lucide-react`로 교체**한다:

| 디자인 | lucide-react |
|---|---|
| `···` | `MoreHorizontal` |
| `↗` | `ArrowUpRight` |
| `⤢` / `⤡` | `Maximize2` / `Minimize2` |
| `✕` | `X` |
| `↑` (전송) | `ArrowUp` |
| `▾` / `▴` | `ChevronDown` / `ChevronUp` |
| `!` (경고) | `AlertCircle` |
| `✓` | `Check` |

폰트: Pretendard (CDN `jsdelivr`). 기존 `styles.css`가 이미 Pretendard를 쓰고 있다.

## Files

| 파일 | 내용 |
|---|---|
| `Cloud Platform Console Redesign.dc.html` | 전체 디자인. 브라우저에서 바로 열린다. 턴 2가 구현 대상, 턴 1은 현재 상태 재현(비교용) |
| `support.js` | 위 HTML 렌더링에 필요한 런타임. 같은 폴더에 있어야 한다 |
| `IMPLEMENTATION.md` | 레포 기준 단계별 구현 순서 — 토큰 교체 → main.tsx 분리 → 버튼 위계 → AI 패널 → 나머지 화면 → 상태 |

**대상 레포 참고 파일**
- `frontend/src/main.tsx` (2,747줄) — 전체 UI. `ProjectAgentPanel`과 `AdminConsole`이 거의 동일한 코드를 중복 보유 → 하나로 합칠 것
- `frontend/src/styles.css` (2,418줄) — `:root` 토큰 교체가 0단계
- `deployment_presets.py` — 프레임워크 11종의 정본. 프론트 하드코딩(`frameworkOptions`)과 라벨이 어긋나 있으므로 API로 내려받도록 통일

## 구현 시 하지 말 것

- `styles.css` 한 파일에 새 클래스를 계속 append — 컴포넌트 분리와 함께 co-locate
- AI가 조작 버튼을 대체하는 방향 — 안전한 동작은 표에서 바로 처리된다
- 화면이 자기 기능을 설명하는 문장 추가 — 현재 코드의 `subtitle`/`description` prop 상당수가 삭제 대상
- 렌더한 뒤 disabled로 막기 — 상태상 가능한 동작만 렌더한다
- 전역 `button{}`에 `background:var(--primary)` — 위계를 만들 수 없다
