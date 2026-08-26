# Cloud Platform Console 기획/아키텍처 브리프

이 문서는 Cloud Platform Console을 피그잼으로 도식화하고, 포트폴리오에 설명하기 위한 기획/설계 정리이다. 핵심은 작은 서버에서 여러 Docker 프로젝트를 안전하게 아카이빙하고 운영하며, AI 에이전트는 프로젝트 권한 안에서만 배포와 운영을 보조하도록 제한하는 구조이다.

2026년 7월 17일 기준으로 이 문서는 최종 QA에서 확인된 실제 구현 상태를 반영한다. UI는 프로젝트 아카이빙과 서비스 운영을 우선으로 재정리했고, AI는 네이버/카나나 계열의 제안형 액션과 Claude/Codex 계열의 승인형 작업 흐름을 참고해 보조 레이어로 배치했다. 백엔드는 LLM이 있어도 변경 작업은 CLI/API skill 계약을 먼저 통과하도록 수정했으며, project agent의 namespace 격리와 mutation QA까지 검증했다.

## 1. 서비스 정의

### 문제

개인 프로젝트나 실험용 서비스를 하나의 서버에 여러 개 올리다 보면 다음 문제가 반복된다.

- 프로젝트별 Docker Compose 파일, 포트, 실행 상태, 로그 위치를 사람이 기억해야 한다.
- 서버 용량과 메모리가 제한되어 있어 모든 서비스를 항상 켜두기 어렵다.
- 오래된 프로젝트를 보관하고 싶지만, 다시 실행하거나 재배포하려면 매번 명령어를 다시 찾아야 한다.
- AI를 붙이면 편해질 수 있지만, AI가 임의 명령을 실행하거나 다른 프로젝트를 건드릴 위험이 생긴다.

### 목표

Cloud Platform Console은 여러 프로젝트를 하나의 서버에서 관리하는 프로젝트 아카이빙 및 운영 콘솔이다. 사용자는 Docker 명령어를 직접 입력하지 않고도 프로젝트를 만들고, 서비스를 배포하고, 실행 상태를 확인하고, 필요할 때만 켜고 끌 수 있다.

### 핵심 사용자

- 개인 개발자 또는 프로젝트 관리자
- 여러 포트폴리오/실험 프로젝트를 작은 서버에 보관하려는 사용자
- Docker와 서버 운영 명령을 매번 직접 다루기보다 안전한 콘솔과 AI 보조 흐름을 원하는 사용자

### 핵심 기능 정의

| 기능 | 목적 | 우선순위 |
| --- | --- | --- |
| 프로젝트 생성 | 여러 서비스를 묶을 독립 관리 단위를 만든다. | 높음 |
| 프로젝트 목록 | 어떤 프로젝트가 있는지, 어떤 서비스가 실행 중인지 한눈에 본다. | 높음 |
| 프론트 URL 바로가기 | 배포된 웹 서비스를 바로 확인한다. | 높음 |
| 서비스 배포 | GitHub 저장소를 프로젝트 안의 서비스로 등록하고 Docker Compose로 실행한다. | 높음 |
| 시작/중지/재시작 | 사용하지 않는 서비스는 꺼서 자원을 아끼고, 필요할 때 다시 켠다. | 높음 |
| 재배포 | Git 저장소 기준으로 서비스를 새로 빌드하고 교체한다. | 높음 |
| 서버 자원 확인 | 디스크, 메모리, swap, 컨테이너 상태를 확인해 작은 서버의 한계를 관리한다. | 높음 |
| 로그 확인 | 장애가 났을 때 bounded tail 방식으로 필요한 만큼만 확인한다. | 중간 |
| AI 에이전트 | 배포 입력 수집, 누락 정보 확인, 승인 전 계획 정리, 운영 요청 보조를 담당한다. | 높음 |
| 배포 요청서 | 서비스명, GitHub URL, 프레임워크, 웹 공개 여부, 포트/환경변수를 폼으로 수집한다. | 높음 |
| 기술 스택 기록 | 배포 성공 시 프레임워크와 배포 시각을 저장해 프로젝트 목록에 합산 표시한다. | 높음 |

### 설계 원칙

- 프로젝트가 가장 중요한 단위이다.
- 서비스는 프로젝트 안에 속한다.
- 직접 조작 가능한 버튼과 폼이 기본이고, AI는 보조 수단이다.
- 변경 작업은 미리보기와 최종 승인을 거친다.
- AI는 shell을 실행하지 않고, 허용된 API/CLI 기능만 호출한다.
- 일반 사용자는 자기 프로젝트만 볼 수 있고, 다른 프로젝트에는 접근할 수 없다.
- 목록 화면은 아카이빙과 운영 판단을 위한 요약 화면이다.
- 로그는 보조 정보이고, 시작/중지/재시작/재배포가 주요 액션이다.
- AI는 눈에 띄되, 직접 조작 버튼보다 앞서지 않는다.

### 현재 구현 반영 요약

| 영역 | 반영 내용 |
| --- | --- |
| 프로젝트 목록 | 실행 중 서비스 수, 메모리 사용량, 프론트 바로가기, 기술 스택, 최근 배포 정보를 표시한다. |
| 프로젝트 상세 | 서비스 카드에서 상태, 공개 URL, 포트, 메모리, 시작/중지/재시작/재배포, 로그를 확인한다. |
| 서버 용량 | 메모리와 디스크 상태를 상단에서 노출하고, `disk_low`, `swap_active` 같은 경고를 제공한다. |
| 배포 폼 | GitHub URL과 framework 선택이 유효해야 `검증 요청` 버튼이 활성화된다. |
| AI 승인 | 재시작/중지/재배포/배포 같은 변경 작업은 승인 카드에서 최종 확인 후 실행한다. |
| 응답 속도 | `server.health` agent endpoint는 0.3초 내외, Web API `/api/system/summary`는 캐시 적용 후 0.1초대 응답을 확인했다. |

## 2. 권한 및 API 설계

### 사용자 권한 모델

| 권한 | 볼 수 있는 범위 | 가능한 작업 | 제한 |
| --- | --- | --- | --- |
| 비로그인 | 공개 허용된 서비스 표면 | 공개 URL 확인 정도 | AI, 배포, 운영 작업 불가 |
| User | 자신이 멤버인 프로젝트 | 프로젝트 생성, 서비스 배포, 시작/중지/재시작/재배포, 로그 확인 | 다른 사용자 프로젝트 접근 불가 |
| Root/Admin | 전체 프로젝트와 서버 상태 | 전체 조회, 서버 상태 확인, root agent, 유지보수 작업 | 민감 작업은 승인 흐름 유지 |

### AI 권한 분리

| AI 종류 | 귀속 범위 | 역할 |
| --- | --- | --- |
| Root AI | 서버 전체 | 프로젝트 목록, 서버 상태, 프로젝트 agent 보장, 전체 운영 진단 |
| Project AI | 특정 프로젝트 namespace | 해당 프로젝트의 서비스 배포, 재배포, 상태 조회, 로그 확인, 시작/중지/재시작 |

AI를 하나로 두지 않고 root AI와 project AI로 나눈 이유는 프로젝트별 권한 경계를 명확히 하기 위해서이다. Project AI는 자기 namespace의 프로젝트 이름을 기본값으로 갖고, 다른 프로젝트를 대상으로 하는 요청은 API 계층에서 차단된다.

최종 QA에서 project agent가 자기 namespace 밖의 프로젝트를 조회하거나 제어할 수 없도록 검증했다. `PLATFORM_NAMESPACE_TOKENS`가 설정된 Platform API는 namespace token 인증을 요구하며, `project.list` 결과는 현재 namespace로 필터링된다. 다른 프로젝트에 대한 `service.control` 요청은 403 계층에서 차단된다.

### API 계층 구조

```text
Browser
  -> Web API
      -> Root Skill Agent
      -> Project Agent
          -> Platform API
              -> Docker / Compose / /srv/projects
```

### API 설계 의도

- **Web API**
  - 로그인/권한 판단, 프로젝트 접근 검증, 프론트 정적 파일 제공, API 캐싱을 담당한다.
  - 사용자의 요청을 root agent 또는 project agent로 라우팅한다.

- **Root Skill Agent**
  - 서버 전체 상태와 프로젝트 목록 같은 root 범위 작업을 담당한다.
  - project agent 생성/보장 같은 인프라 관리 작업을 수행한다.

- **Project Agent**
  - 특정 프로젝트에 귀속된다.
  - 배포, 재배포, 로그, 상태, 시작/중지/재시작 같은 프로젝트 내부 작업만 수행한다.

- **Platform API**
  - Docker socket과 `/srv/projects`에 접근하는 실제 제어면이다.
  - project agent가 직접 무제한 Docker 권한을 갖는 대신, namespace token과 allowlisted skill을 통해 제어한다.

### 백엔드 데이터 계약

프로젝트 목록과 상세 화면은 단순 이름 목록이 아니라 운영 요약 데이터를 받는다.

```text
Project summary
  - name
  - service_summaries
  - frameworks
  - running_count / service_count
  - attention_count
  - memory_total_mb
  - public_urls
  - last_deployed_at
```

서비스 배포/재배포가 성공하면 `.cloud-platform/services.json`에 framework, repo URL, frontend 여부, 포트, last_deployed_at을 저장한다. 프론트는 런타임 API의 Docker stats를 우선 사용하고, 아직 stats가 없으면 프로젝트 요약값을 fallback으로 사용한다. 값이 없을 때 `0`처럼 오해되는 숫자를 보여주지 않고 `확인 전`, `없음`으로 구분한다.

### API 흐름 예시

#### 프로젝트 목록 조회

```text
User Browser
  -> GET /api/projects
  -> Web API: user role/membership 확인
  -> Root Agent: project summaries 조회
  -> Web API: 사용자가 볼 수 있는 프로젝트만 필터링
  -> Browser: 프로젝트, 서비스, 상태, 자원, URL 응답
```

#### 서비스 배포

```text
User Browser
  -> 프로젝트 페이지에서 배포 요청
  -> Project AI: 누락 정보 확인(repo, framework, service name)
  -> Project Agent: service.deploy preview 생성
  -> Browser: 배포 계획과 위험 요소 표시
  -> User: 최종 승인
  -> Project Agent -> Platform API -> Docker Compose build/up
  -> 검증 후 결과와 감사 로그 기록
```

#### 서비스 제어

```text
User Browser
  -> start / stop / restart / redeploy
  -> Web API: 프로젝트 접근 검증
  -> Project Agent: namespace 고정
  -> Platform API: Compose 명령 실행
  -> Web API: 프로젝트/서비스 캐시 무효화
  -> Browser: 최신 상태 표시
```

## 3. Docker 및 인프라 구조

### 서버 구조

```text
/opt/cloud_platform
  - Web API, frontend, Skill Agent source

/srv/projects
  /<project-name>
    - docker-compose.yml
    - service source directories
    - .cloud-platform/services.json
```

### 컨테이너 역할

| 컨테이너 | 역할 |
| --- | --- |
| cloud-platform-web-api | 사용자 API, 권한 확인, 프론트 정적 파일 제공 |
| cloud-platform-skill-agent | root 범위 agent |
| cloud-platform-platform-api | Docker/Compose 제어를 받는 내부 API |
| `<project>-agent-1` | 특정 프로젝트에 귀속된 project agent |
| `<project>-<service>-1` | 실제 사용자 서비스 컨테이너 |

### 네트워크 구조

```text
cloud-platform-internal
  - web-api
  - root skill-agent
  - platform-api
  - project-agent aliases

cp_<project>_control_net
  - project-agent
  - platform-api
  - 일반 서비스는 접근하지 않음

cp_<project>_app_net
  - project-agent
  - project services
  - 서비스 간 내부 통신

host ports 9000-9100
  - 외부 공개가 필요한 frontend service만 publish
```

### 왜 API 서버와 Agent를 분리했는가

Web API와 Agent를 분리한 이유는 사용자 요청 처리와 인프라 실행 권한을 같은 계층에 두지 않기 위해서이다. Web API는 권한과 라우팅을 담당하고, Agent는 정해진 skill만 실행한다. 실제 Docker 제어는 Platform API와 Docker socket 접근이 가능한 제한된 컨테이너에서 수행한다.

이 구조는 다음 위험을 줄인다.

- AI가 임의 shell 명령을 실행하는 위험
- project agent가 다른 프로젝트를 조작하는 위험
- 일반 서비스 컨테이너가 control API에 접근하는 위험
- 사용자 권한 검증 없이 Docker 작업이 실행되는 위험

### 작은 서버를 위한 운영 전략

- 여러 프로젝트를 한 서버에 보관하되, 필요 없는 서비스는 중지해 메모리와 CPU를 아낀다.
- 프론트 URL, 실행 상태, 메모리 사용량, 마지막 배포 정보를 목록에 노출해 운영 판단을 빠르게 한다.
- Docker image/build cache와 정적 asset cache를 관리해 디스크와 응답 시간을 안정화한다.
- 서버 상태 API는 disk, memory, swap 경고를 제공해 작은 서버 한계를 UI에서 드러낸다.
- Web API는 project summary, catalog, system summary, service status에 짧은 TTL 캐시를 둔다.
- 정적 asset은 hash 파일명 기반으로 캐싱하고, HTML fallback은 짧게 갱신한다.

### 현재 운영 경고

최종 QA 시점의 서버는 루트 디스크 사용률이 약 92-93%이며 `disk_low`, `swap_active` 경고가 남아 있다. 기능 검증은 통과했지만, 장기 운영에서는 Docker image 정리, 오래된 build cache 삭제, 프로젝트 소스/이미지 보존 정책이 필요하다. 이 제약은 서비스 기획의 핵심 배경이기도 하다.

## 4. AI Agent 설계 방향

### 초기 한계

AI를 단순히 프롬프트나 RAG 중심으로 붙이면 다음 문제가 생긴다.

- 사용자가 배포에 필요한 정보를 빠뜨렸을 때 AI가 임의로 값을 만들어낼 수 있다.
- RAG로 문서를 잘 찾아도 실제 실행 권한과 실패 복구는 보장되지 않는다.
- 자연어 요청이 Docker 명령이나 shell 실행으로 바로 연결되면 보안 경계가 약해진다.
- 프로젝트가 여러 개일 때 AI가 어느 프로젝트를 대상으로 해야 하는지 혼동할 수 있다.

### 설계 전환

LLM을 실행자가 아니라 planner로 제한했다. LLM은 사용자의 의도를 해석하고 필요한 정보를 정리하지만, 실제 변경은 schema가 정해진 CLI/API skill만 수행한다.

```text
Natural language
  -> Intent parsing
  -> Missing field check
  -> Skill schema validation
  -> Preview
  -> Explicit approval
  -> Allowlisted API/CLI execution
  -> Verification
  -> Audit log
```

### 핵심 원칙

- **Allowlisted skills only**: 등록된 skill만 실행한다.
- **Schema-bound arguments**: project, service, repo_url, framework 같은 입력은 schema로 검증한다.
- **No arbitrary shell**: LLM이 shell 명령, Docker flag, 파일 경로를 직접 만들 수 없다.
- **Project namespace**: project agent는 자기 프로젝트만 대상으로 한다.
- **Preview before mutation**: 배포/재배포/중지 같은 변경 작업은 계획을 먼저 보여준다.
- **Explicit approval**: 사용자가 승인해야 실행된다.
- **Verification and rollback**: 배포/포트 변경은 실행 후 검증하고 실패 시 복구한다.
- **Audit**: 실행 결과를 기록해 AI가 무엇을 했는지 추적 가능하게 한다.
- **CLI-first mutation funnel**: LLM API key가 있어도 프로젝트 생성, 배포, 재배포, 서비스 제어, 포트 변경은 CLI 검증 경로가 최종 authority이다.
- **Field-level correction**: 잘못된 GitHub URL, framework, host port는 전체 대화를 리셋하지 않고 해당 필드만 다시 확인한다.

### 사용자 경험

AI는 채팅 UI만으로 모든 작업을 처리하지 않는다. 배포처럼 정보가 필요한 작업은 repo URL, framework, service name, port 같은 항목을 폼으로 수집한다. 입력이 잘못되면 전체를 다시 묻지 않고 잘못된 필드만 재확인한다. 최종 실행 전에는 사람이 읽을 수 있는 계획을 보여주고 승인받는다.

Project AI UI는 공통 모듈로 구성된다.

- 상단: 현재 scope와 권한 표시
- 제안 액션: 상태 요약, 문제 찾기, 배포 요청서, 프레임워크 도움, 재시작 전 확인, 로그 확인
- 대화 입력: 자유 자연어를 받되 실행은 skill 계약으로 제한
- 승인 카드: 변경 대상, 작업, 위험, 최종 승인 버튼을 명확히 표시

이 구조는 “AI가 모든 것을 대신하는 화면”이 아니라 “사용자가 운영 판단을 하고, AI가 안전한 다음 행동을 제안하는 화면”을 목표로 한다.

## 5. 피그잼 도식화 프레임

### Frame 1. 문제 정의

제목: 여러 프로젝트를 작은 서버에서 운영할 때 생기는 문제

노드:

- 프로젝트가 여러 개로 늘어남
- Docker Compose/포트/로그를 수동 관리
- 서버 용량과 메모리 부족
- 오래된 프로젝트를 다시 켜기 어려움
- AI를 붙이면 편하지만 권한 위험 발생

중앙 메시지:

```text
여러 프로젝트를 보관하고 실행하려면
아카이빙, 운영, 권한, AI 제어가 동시에 필요하다.
```

### Frame 2. 서비스 정의

제목: Cloud Platform Console

중앙 노드:

```text
Project Archive & Operation Console
```

주변 노드:

- N개 프로젝트 관리
- 프로젝트별 서비스 묶음
- 프론트 URL 바로가기
- 실행 상태/자원 확인
- 시작/중지/재시작/재배포
- 로그 확인
- 프로젝트 귀속 AI agent

### Frame 3. 사용자 권한

제목: 사용자 권한과 접근 범위

```text
비로그인
  -> 공개 서비스 표면만 조회
  -> 운영 작업 불가

User
  -> 내 프로젝트만 조회
  -> 내 프로젝트 서비스만 배포/운영

Root/Admin
  -> 전체 프로젝트와 서버 상태 조회
  -> root agent / maintenance
```

강조 문구:

```text
권한의 기준은 "사용자"가 아니라
"프로젝트 namespace"까지 내려간다.
```

### Frame 4. API 중간층

제목: 사용자 요청이 실행 권한으로 바뀌는 과정

```text
Browser
  -> Web API
      - 로그인/권한
      - membership filter
      - cache
      - static frontend

  -> Root Agent
      - server health
      - project summaries
      - project agent ensure

  -> Project Agent
      - service deploy
      - service status/logs
      - service control

  -> Platform API
      - Docker / Compose control
```

강조 문구:

```text
AI가 직접 서버를 조작하지 않는다.
권한 검증을 통과한 API/CLI skill만 실행된다.
```

### Frame 5. Docker 인프라

제목: 프로젝트별 격리와 네트워크 분리

```text
Host
  /opt/cloud_platform
  /srv/projects

cloud-platform-internal
  web-api
  root-agent
  platform-api
  project-agent alias

cp_project_control_net
  project-agent
  platform-api

cp_project_app_net
  service containers
  project-agent

public ports
  9000-9100
```

강조 문구:

```text
일반 서비스는 control API에 접근하지 못하고,
project-agent만 자기 namespace를 통해 제어한다.
```

### Frame 6. AI Agent 구조

제목: LLM을 실행자가 아니라 planner로 제한

```text
사용자 자연어
  -> 의도 파악
  -> 누락 정보 질문
  -> schema 검증
  -> preview 생성
  -> 사용자 승인
  -> API/CLI skill 실행
  -> 검증/rollback/audit
```

비교 노드:

```text
프롬프트/RAG 중심
  - 설명은 가능
  - 실행 제어가 약함
  - 권한 경계가 불안정

CLI/API skill 중심
  - 실행 가능한 행동이 제한됨
  - 검증과 승인 가능
  - 프로젝트별 권한 통제 가능
```

### Frame 7. 포트폴리오 요약

제목: 설계 선택의 핵심

3줄 요약:

```text
작은 서버에서 여러 Docker 프로젝트를 보관/운영하는 콘솔을 만들었다.
AI Agent는 편의성을 주지만, 실행 권한은 API/CLI skill로 제한했다.
프로젝트별 namespace와 네트워크 분리로 다른 프로젝트를 건드리지 못하게 설계했다.
```

### Frame 8. 최종 QA 증거

제목: 설계가 실제로 동작하는지 검증

```text
Design QA
  - impeccable detector []
  - mobile/tablet/desktop/wide screenshot
  - 프로젝트 목록, 상세, AI, 배포 폼, 승인 카드 검증

Browser QA
  - visitor / admin root / project detail
  - service action buttons
  - log output
  - deploy form invalid/valid
  - AI approval card

Platform QA
  - server_qa_all --fast PASS 11/11
  - mutation QA PASS
  - project create/deploy/redeploy/start/stop/port change
```

강조 문구:

```text
포트폴리오에서 중요한 것은 "AI가 된다"가 아니라
AI가 실패해도 API 계약과 QA로 운영 경계가 보장된다는 점이다.
```

## 6. 포트폴리오용 서술 초안

여러 개인 프로젝트와 실험 서비스를 하나의 작은 서버에 보관하면서 필요할 때 다시 실행하고 보여줄 수 있는 환경이 필요했습니다. 하지만 Docker Compose 파일, 포트 매핑, 실행 상태, 로그 확인, 재배포 과정을 매번 수작업으로 관리하는 방식은 반복적이고 실수 가능성이 높았습니다. 특히 서버 용량과 메모리가 제한되어 있어 모든 서비스를 항상 켜둘 수 없었고, 사용하지 않는 프로젝트는 중지했다가 필요할 때 다시 켤 수 있는 운영 콘솔이 필요했습니다.

이를 해결하기 위해 Cloud Platform Console을 설계했습니다. 이 서비스는 프로젝트를 최상위 관리 단위로 두고, 각 프로젝트 안에 여러 서비스를 배포하고 운영할 수 있도록 구성했습니다. 사용자는 프로젝트 목록에서 실행 중인 서비스 수, 프론트 URL, 기술 스택, 메모리 사용량, 서버 자원 상태를 확인할 수 있고, 각 서비스는 시작, 중지, 재시작, 재배포 같은 핵심 운영 액션을 버튼과 승인 흐름을 통해 수행할 수 있습니다.

AI 에이전트 도입 과정에서는 단순한 프롬프트 엔지니어링이나 RAG만으로는 운영 자동화를 안정적으로 제어하기 어렵다는 한계를 느꼈습니다. AI가 배포 정보를 임의로 추론하거나, shell 명령을 생성하거나, 다른 프로젝트를 대상으로 작업할 가능성을 막아야 했습니다. 그래서 LLM을 직접 실행자가 아니라 의도 해석과 계획 생성자로 제한하고, 실제 실행은 schema가 정의된 CLI/API skill만 수행하도록 구조를 바꿨습니다. 특히 LLM API가 켜져 있어도 변경 작업은 CLI dry-run, schema 검증, 미리보기, 승인 단계를 먼저 통과하도록 설계했습니다.

권한 분리를 위해 root agent와 project agent를 나누었습니다. root agent는 전체 프로젝트 목록과 서버 상태처럼 루트 범위 작업을 담당하고, project agent는 특정 프로젝트 namespace에 귀속되어 해당 프로젝트의 서비스만 조작할 수 있습니다. 또한 project agent가 직접 Docker 권한을 무제한으로 갖지 않도록 Platform API를 중간에 두고, namespace token과 allowlisted skill을 통해서만 Docker Compose 작업이 실행되도록 설계했습니다.

인프라 구조는 Docker Compose와 네트워크 분리를 기반으로 구성했습니다. Web API는 사용자 인증, 권한 확인, API 캐싱, 프론트 정적 파일 제공을 담당하고, Agent 계층은 배포와 운영 요청을 처리합니다. 프로젝트마다 app network와 control network를 분리해 일반 서비스 컨테이너가 제어 API에 접근하지 못하도록 했고, 공개가 필요한 프론트 서비스만 `9000-9100` 범위의 host port로 노출했습니다.

이 과정을 통해 단순한 Docker 대시보드가 아니라, 작은 서버의 자원 제약, 사용자 권한, AI 실행 제어, 프로젝트별 격리를 함께 고려한 운영 콘솔을 구현했습니다. 최종 QA에서는 Playwright 기반 브라우저 검증, impeccable 디자인 검증, server QA 11/11, disposable 프로젝트 기반 mutation QA를 통과했습니다. 결과적으로 사용자는 여러 프로젝트를 안전하게 보관하고 필요할 때 실행할 수 있으며, AI는 편의성을 제공하되 정해진 API 경계 안에서만 동작하도록 제한됩니다.

## 7. 발표용 30초 요약

Cloud Platform Console은 작은 서버에서 여러 Docker 프로젝트를 보관하고 운영하기 위한 콘솔입니다. 프로젝트별로 서비스를 묶고, 프론트 URL, 실행 상태, 기술 스택, 자원 사용량을 확인하며, 시작/중지/재시작/재배포를 승인 흐름 안에서 수행할 수 있습니다. AI Agent를 도입했지만 AI가 직접 shell을 실행하지 않도록 제한했고, root agent와 project agent를 분리해 프로젝트별 namespace 안에서만 작업하도록 설계했습니다. 핵심은 AI 편의성과 서버 운영 자동화를 결합하되, 실제 실행 권한은 API와 CLI skill로 통제하고 QA로 검증했다는 점입니다.

## 8. 최종 구현/QA 결과

### 스킬 기반 QA 진행 방식

최종 QA는 단순히 화면을 눈으로 확인하는 방식이 아니라, Codex skill을 역할별로 나눠 사용했다.

| 단계 | 사용한 skill/도구 | 목적 |
| --- | --- | --- |
| 디자인 기준 수립 | `$impeccable` | 시각 위계, 정보 밀도, 모바일/데스크톱 레이아웃, 한국식 운영 UI 톤을 점검 |
| 정적 UI 검사 | `impeccable detect` | anti-pattern, 디자인 시스템 위반, 구조적 UI 문제를 자동 탐지 |
| 실제 브라우저 검증 | `$playwright` | 모바일/데스크톱 화면, 버튼 클릭, 폼 입력, 승인 카드, AI 응답을 실제 DOM 기준으로 검증 |
| 서버 baseline QA | `server_qa_all --fast` | 라우터, CLI 계약, 승인 가드, namespace 네트워크, runtime QA를 검증 |
| 자연어 mutation QA | `server_skill_mutation_test.sh` | disposable `skill-qa` 프로젝트에서 생성/배포/재배포/시작/중지/포트 변경을 실제 실행 |
| 정리 | cache/prune/df | Playwright 브라우저 캐시와 빌드 부산물을 삭제하고 작은 디스크 환경을 복구 |

이 과정에서 `$impeccable`은 “좋아 보이는가”보다 “사용자가 운영 판단을 빠르게 할 수 있는가”를 보는 기준으로 사용했다. `$playwright`는 스크린샷 증거와 실제 interaction 검증을 담당했고, 내부 QA 스크립트는 AI가 자연어를 받아도 최종 실행이 CLI/API 계약 안에서만 이루어지는지 확인하는 역할을 맡았다.

### 디자인 QA

- `$impeccable` detector: `[]`
- 모바일/태블릿/데스크톱/wide 스크린샷 검증 완료
- 프로젝트 목록, 프로젝트 상세, 서비스 액션, AI 패널, 배포 요청서, 승인 카드 검증
- `메모리 0MB`, `외부 URL 0`처럼 데이터 없음과 실제 0을 혼동시키는 표시를 수정
- 배포 요청서의 유효 입력 상태에서 `검증 요청` 버튼 활성화 확인

### 브라우저 QA

검증 산출물 위치:

```text
output/playwright/final-qa
```

확인한 상태:

- Visitor home
- Admin root mobile/desktop/tablet/wide
- Project detail mobile
- Service restart confirmation
- Log output
- Deploy form empty/invalid/valid
- AI approval card
- Root AI response

### 서버/AI QA

```text
./scripts/server_qa_all.sh --fast
RESULT: PASS 11 / 11

./scripts/server_skill_mutation_test.sh
OK natural_language_project_create
OK natural_language_deploy
OK natural_language_redeploy
OK natural_language_stop
OK natural_language_start
OK natural_language_port_change
OK post_mutation_qa
```

검증된 자연어 동작:

- 신규 프로젝트 생성
- GitHub 저장소 기반 서비스 배포
- 최신 코드 재배포
- 서비스 중지/시작
- host port 변경
- 사후 deterministic QA

### QA 중 발견한 실패와 수정

최종 QA에서는 단순 PASS만 확인하지 않고, 실패를 설계 개선 항목으로 환원했다.

| 발견된 문제 | 원인 | 수정 |
| --- | --- | --- |
| 프로젝트 상세 상단에 `메모리 0MB`, `외부 URL 0` 표시 | 데이터 없음과 실제 0을 구분하지 않음 | 런타임 값이 없으면 프로젝트 요약값을 fallback으로 쓰고, 없을 때는 `확인 전`, `없음`으로 표시 |
| 배포 폼 valid screenshot이 실제로는 framework 미선택 상태 | QA 스크립트가 필수 선택값까지 채우지 않음 | Playwright QA에서 framework 선택과 `검증 요청` 버튼 enabled 상태를 assertion으로 추가 |
| Project agent가 다른 프로젝트 목록을 보고 제어 가능 | namespace token 매핑이 있어도 auth required가 자동 활성화되지 않음 | `PLATFORM_NAMESPACE_TOKENS`가 있으면 namespace 인증을 요구하도록 수정 |
| 배포 문맥에서 짧은 응답이 project create로 튀거나 planner가 값을 과추론 | fallback router와 strict argument 정책이 느슨함 | context 유지 조건과 bare slot 처리 범위를 조정하고, 다중 필드 누락 시 planner 추론을 제한 |
| LLM이 `서비스를 새로 배포하고 싶어`를 일반 help로 응답 | LLM 응답이 CLI mutation funnel보다 앞섬 | LLM API key가 있어도 생성/배포/재배포는 CLI dry-run과 schema 검증을 먼저 타도록 변경 |
| GitHub 저장소 검증이 timeout | 실제 `git ls-remote`가 서버에서 약 12초 가까이 걸림 | repository validate timeout 기본값을 30초로 완화 |
| 포트 변경 QA에서 허용 범위 밖 포트가 실행 인자로 들어감 | LLM/planner 인자를 그대로 신뢰하는 경로가 남아 있음 | `port.manage`, `service.control` 등 운영 작업도 `strict_arguments`로 재검증 |

이 실패들은 포트폴리오에서 중요한 설계 근거가 된다. AI 기능을 추가하는 것보다 중요한 것은, AI가 잘못 이해하거나 네트워크가 느리거나 UI QA가 불완전할 때도 시스템이 어디서 막히고 어떻게 수정되는지 추적 가능한 구조를 갖추는 것이다.

### 운영상 남은 리스크

- 최종 QA 시점 디스크 사용률은 약 92-93%로 `disk_low` 경고가 남아 있다.
- swap 사용 경고가 남아 있어, 장기 운영 시 이미지/캐시 정리 정책과 서비스 중지 전략이 중요하다.
- mutation QA는 disposable `skill-qa` 프로젝트에서만 수행해야 하며 실제 포트폴리오 프로젝트에는 직접 적용하지 않는다.

## 9. 키워드

- Docker Compose
- Project namespace
- Web API
- Root Agent / Project Agent
- Platform API
- Permission boundary
- AI planner
- Allowlisted CLI/API skill
- Preview and approval
- Audit log
- Small server operation
- Project archive
