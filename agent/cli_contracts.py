from __future__ import annotations

from typing import Any

CONTRACT_VERSION = "2026-07-01"

PLANNER_RULE = (
    "Use this CLI as the only execution surface. Choose one command from the "
    "command contracts, fill only fields supported by that command schema, call "
    "preview for mutation commands, ask the user for missing fields returned by "
    "the CLI, and execute only after explicit approval. The LLM decides natural "
    "language intent and writes user-facing replies; the CLI/API enforces allowed "
    "actions, validation, namespace ownership, and approval. Never call platform "
    "APIs or Docker directly."
)

COMMON_SECURITY = [
    "Do not accept shell commands, arbitrary paths, Docker flags, or raw platform API calls from the user.",
    "Secret values must never be sent through chat/LLM; only environment variable names are accepted.",
    "Namespace/project ownership is enforced by the platform API token, not by LLM promises.",
    "Mutation commands must be previewed and explicitly approved before execution.",
]

COMMAND_FIELD_ORDER: dict[str, dict[str, list[str]]] = {
    "project.create": {
        "required": ["project"],
        "optional": [],
    },
    "service.deploy": {
        "required": ["project", "service", "repo_url", "framework"],
        "optional": ["container_port", "host_port", "is_web", "environment_names"],
    },
    "service.redeploy": {
        "required": ["project", "service"],
        "optional": [],
    },
    "service.control": {
        "required": ["project", "service", "action"],
        "optional": [],
    },
    "service.status": {
        "required": ["project"],
        "optional": ["service"],
    },
    "service.logs": {
        "required": ["project", "service"],
        "optional": ["lines"],
    },
    "help.search": {
        "required": ["query"],
        "optional": [],
    },
    "port.manage": {
        "required": ["project", "service", "operation"],
        "optional": ["host_port", "container_port"],
    },
    "entity.resolve": {
        "required": ["entity", "query"],
        "optional": ["project"],
    },
    "repository.inspect": {
        "required": ["repo_url"],
        "optional": [],
    },
}

COMMAND_HELP: dict[str, dict[str, Any]] = {
    "project.create": {
        "title": "새 프로젝트 생성",
        "role": "서비스들을 묶을 새 관리 프로젝트 namespace를 생성합니다.",
        "use_when": [
            "새 프로젝트를 만들고 싶을 때",
            "서비스를 배포하려는데 기존 프로젝트가 없을 때",
            "프로젝트별 app/control Docker 네트워크와 namespace 토큰이 필요할 때",
        ],
        "not_for": [
            "기존 프로젝트 안에 서비스를 추가하는 작업",
            "이미 존재하는 서비스를 최신 코드로 재배포하는 작업",
        ],
        "ambiguous_with": ["service.deploy"],
        "clarification_question": (
            "새 프로젝트 자체를 먼저 만들까요, 아니면 이미 있는 프로젝트에 서비스를 배포할까요?"
        ),
        "examples": [
            "horse_race 프로젝트 만들어줘",
            "새 프로젝트를 만들고 싶어",
            "기존 프로젝트가 없으니 rea로 새로 만들어줘",
        ],
        "after_success": [
            "service.deploy로 새 서비스를 추가할 수 있습니다.",
        ],
        "security": [
            *COMMON_SECURITY,
            "Project creation is root/admin scoped. Project-scoped agents cannot create projects.",
        ],
    },
    "service.deploy": {
        "title": "새 서비스 처음 배포",
        "role": "기존 프로젝트 안에 공개 GitHub 저장소를 새 서비스로 처음 등록하고 배포합니다.",
        "use_when": [
            "새 GitHub 저장소를 서비스로 올릴 때",
            "기존 프로젝트 안에 새 프론트엔드/백엔드 서비스를 추가할 때",
            "처음 배포, 신규 서비스 등록, add new service 요청일 때",
        ],
        "not_for": [
            "이미 존재하는 서비스를 최신 Git 코드로 다시 빌드하는 작업",
            "새 프로젝트만 만드는 작업",
            "컨테이너를 단순 재시작하는 작업",
        ],
        "ambiguous_with": ["service.redeploy", "project.create"],
        "clarification_question": (
            "새 서비스를 처음 배포하려는 건가요, 기존 서비스를 최신 코드로 재배포하려는 건가요?"
        ),
        "examples": [
            "demoa 프로젝트에 frontend 서비스를 새로 배포해줘",
            "GitHub 저장소를 새 서비스로 등록하고 싶어",
            "horse_race에 backend 서비스를 내부 API로 배포해줘",
        ],
        "flow": [
            "project가 없으면 project.create를 먼저 안내합니다.",
            "repo_url이 있으면 repository.inspect로 프레임워크 후보를 확인할 수 있습니다.",
            "framework가 애매하면 framework.list 또는 schema enum 기준으로 다시 묻습니다.",
            "is_web=false인 백엔드는 외부 host_port를 열지 않고 app-net 내부 통신만 사용합니다.",
        ],
        "ui": {
            "type": "form",
            "form": "service.deploy",
            "show_when_missing": ["service", "repo_url", "framework"],
            "required": ["service", "repo_url", "framework"],
            "optional": ["is_web", "host_port", "environment_names"],
        },
        "security": [
            *COMMON_SECURITY,
            "Only public GitHub HTTPS repositories are accepted.",
            "A project-scoped agent can deploy only into its own namespace.",
        ],
    },
    "service.redeploy": {
        "title": "기존 서비스 최신 코드 재배포",
        "role": "이미 존재하는 서비스를 최신 Git 코드로 다시 빌드하고 성공 시 교체합니다.",
        "use_when": [
            "git push 후 최신 코드 반영",
            "기존 서비스를 새 이미지로 교체",
            "재배포, 최신 코드로 다시 배포, rebuild 요청일 때",
        ],
        "not_for": [
            "새 서비스를 처음 만드는 작업",
            "새 프로젝트를 만드는 작업",
            "현재 이미지를 그대로 재시작하는 작업",
        ],
        "ambiguous_with": ["service.deploy", "service.control"],
        "clarification_question": (
            "새 서비스를 처음 배포하려는 건가요, 기존 서비스를 최신 Git 코드로 재배포하려는 건가요?"
        ),
        "examples": [
            "demoa의 frontend를 최신 코드로 재배포해줘",
            "git push 했으니 demo-a 다시 빌드해서 교체해줘",
            "기존 서비스를 새 이미지로 재배포해줘",
        ],
        "flow": [
            "대상 project/service가 실제 존재하는지 CLI가 검증합니다.",
            "새 소스를 임시 디렉터리에 clone/build하고 검증 성공 시 교체합니다.",
            "검증 실패 시 이전 소스와 컨테이너로 복구합니다.",
        ],
        "security": [
            *COMMON_SECURITY,
            "A project-scoped agent can redeploy only services inside its own namespace.",
            "The existing service origin is used; user-supplied paths or git flags are rejected.",
        ],
    },
    "service.control": {
        "title": "서비스 시작/중지/재시작",
        "role": "이미 배포된 서비스 컨테이너를 start, stop, restart 중 하나로 제어합니다.",
        "use_when": [
            "현재 이미지를 그대로 재시작할 때",
            "서비스를 잠시 중지하거나 다시 시작할 때",
            "코드 변경 없이 런타임 상태만 바꿀 때",
        ],
        "not_for": [
            "GitHub 최신 코드를 새로 반영하는 재배포",
            "새 서비스를 처음 생성하는 작업",
        ],
        "ambiguous_with": ["service.redeploy"],
        "clarification_question": (
            "현재 컨테이너만 재시작할까요, 아니면 Git 최신 코드로 재배포할까요?"
        ),
        "examples": [
            "demoa의 demo-a 재시작해줘",
            "backend 서비스를 중지해줘",
            "frontend를 다시 시작해줘",
        ],
        "security": [
            *COMMON_SECURITY,
            "A project-scoped agent can control only services inside its own namespace.",
        ],
    },
    "port.manage": {
        "title": "서비스 포트 변경",
        "role": "서비스의 host/container 포트 매핑을 변경하거나 사용할 포트를 제안합니다.",
        "use_when": [
            "외부 공개 포트를 바꾸고 싶을 때",
            "컨테이너 내부 리슨 포트와 Compose 매핑을 맞춰야 할 때",
            "9000~9100 범위에서 빈 포트를 추천받고 싶을 때",
        ],
        "not_for": [
            "내부 백엔드 서비스를 외부에 공개하지 않는 일반 배포",
            "프록시/도메인 라우팅 설정",
        ],
        "ambiguous_with": ["port.suggest", "service.deploy"],
        "clarification_question": (
            "호스트 공개 포트를 바꾸려는 건가요, 컨테이너 내부 포트를 바꾸려는 건가요?"
        ),
        "examples": [
            "demoa의 demo-a 호스트 포트를 9003으로 바꿔줘",
            "컨테이너 포트를 8000으로 바꿔줘",
            "사용 가능한 포트 추천해줘",
        ],
        "security": [
            *COMMON_SECURITY,
            "A project-scoped agent can change only ports for services inside its own namespace.",
            "Host ports are constrained to the configured managed range.",
        ],
    },
    "project.list": {
        "title": "프로젝트/서비스 목록",
        "role": "현재 관리 중인 프로젝트와 서비스 목록을 조회합니다.",
        "use_when": ["프로젝트가 뭐가 있는지 확인할 때", "서비스 선택 전 실제 목록을 확인할 때"],
        "not_for": ["프로젝트 생성/삭제 같은 변경 작업"],
        "examples": ["프로젝트 목록 보여줘", "서비스 목록 확인해줘"],
        "security": ["Read-only. Return only managed Compose projects."],
    },
    "service.status": {
        "title": "서비스 상태 확인",
        "role": "프로젝트 전체 또는 특정 서비스의 Compose 설정, Docker 상태, health, 포트를 조회합니다.",
        "use_when": ["서비스가 떠 있는지 확인할 때", "프론트/백엔드 외부 포트 공개 여부를 볼 때"],
        "not_for": ["서비스를 시작/중지/재시작하는 작업"],
        "examples": ["demoa 상태 확인해줘", "demoa의 demo-a 상태 보여줘"],
        "security": ["Read-only. A project-scoped agent can inspect only its own namespace."],
    },
    "service.logs": {
        "title": "서비스 로그 확인",
        "role": "특정 서비스의 Docker 로그 tail을 제한된 줄 수로 조회합니다.",
        "use_when": ["배포 실패 원인 확인", "앱 런타임 오류 확인", "최근 로그 확인"],
        "not_for": ["로그 파일 직접 수정", "전체 로그 무제한 출력"],
        "examples": ["demoa demo-a 로그 40줄 보여줘", "backend 로그 확인해줘"],
        "security": [
            "Read-only bounded log tail.",
            "A project-scoped agent can read logs only for its own namespace.",
            "Do not expose environment variables or secret values.",
        ],
    },
    "server.health": {
        "title": "서버/플랫폼 상태 확인",
        "role": "Docker, 컨테이너, 프로젝트, 디스크, 메모리 상태를 요약합니다.",
        "use_when": ["서버가 느릴 때", "대시보드가 안 뜰 때", "전체 상태 점검"],
        "not_for": ["개별 서비스 변경 작업"],
        "examples": ["서버 상태 확인해줘", "전체 상태 점검해줘"],
        "security": ["Read-only root/admin scoped platform status."],
    },
    "framework.list": {
        "title": "프레임워크 프리셋 목록",
        "role": "배포 가능한 Dockerfile 프리셋과 기본 포트/환경변수 안내를 조회합니다.",
        "use_when": ["프레임워크 선택이 애매할 때", "지원 프리셋 목록을 보여줄 때"],
        "not_for": ["저장소를 실제 배포하는 작업"],
        "examples": ["프레임워크 뭐 있어?", "javascript면 뭘 골라야 해?"],
        "security": ["Read-only preset catalog."],
    },
    "repository.inspect": {
        "title": "GitHub 저장소 구조 확인",
        "role": "공개 GitHub 저장소를 읽어서 프레임워크 후보와 근거를 반환합니다.",
        "use_when": ["사용자가 repo_url만 주고 프레임워크를 모를 때", "static/vite/react/nextjs 등을 구분할 때"],
        "not_for": ["비공개 저장소 접근", "저장소를 실제 배포"],
        "examples": ["이 저장소 프레임워크 확인해줘"],
        "security": [
            "Read-only.",
            "Only public GitHub HTTPS repositories are accepted.",
            "Temporary clones must be removed after inspection.",
        ],
    },
    "entity.resolve": {
        "title": "이름 후보 확인",
        "role": "프로젝트/서비스/프레임워크 이름을 실제 CLI 목록과 비교해 exact/similar 후보를 반환합니다.",
        "use_when": ["대소문자, 하이픈, 언더바 차이가 있을 때", "사용자가 비슷한 이름을 말했을 때"],
        "not_for": ["후보를 사용자 확인 없이 자동 확정하는 작업"],
        "examples": ["horserace가 horse_race 맞는지 확인"],
        "security": [
            "Read-only.",
            "Similar candidates are suggestions only and require user confirmation before mutation.",
        ],
    },
    "port.suggest": {
        "title": "사용 가능한 포트 추천",
        "role": "관리 중인 Compose 파일을 기준으로 9000~9100 범위의 빈 host port를 추천합니다.",
        "use_when": ["새 웹 서비스를 배포하기 전", "포트 충돌이 걱정될 때"],
        "not_for": ["실제 포트 변경 실행"],
        "examples": ["사용 가능한 포트 추천해줘"],
        "security": ["Read-only. Suggest only managed-range host ports."],
    },
    "qa.run": {
        "title": "플랫폼 QA 점검",
        "role": "Docker ping, 재시작 루프, unhealthy, 중복 포트, 디스크 압박을 점검합니다.",
        "use_when": ["작업 후 검증", "서버 이상 여부 확인"],
        "not_for": ["서비스 배포 자체"],
        "examples": ["QA 돌려줘", "플랫폼 검증해줘"],
        "security": ["Read-only compact platform checks."],
    },
    "help.search": {
        "title": "도움말/문서 검색",
        "role": "배포 가이드와 Skill 문서에서 질문과 관련된 문단을 검색합니다.",
        "use_when": ["배포 절차, Dockerfile, 포트, 프록시, QA 설명이 필요할 때"],
        "not_for": ["실제 서버 변경"],
        "examples": ["배포 절차 알려줘", "Dockerfile 매뉴얼 보여줘"],
        "security": ["Read-only local documentation search."],
    },
    "platform.help": {
        "title": "플랫폼 도움말",
        "role": "현재 CLI 명령 catalog와 사용 예시를 반환합니다.",
        "use_when": ["전체 기능을 알고 싶을 때", "무슨 명령이 가능한지 볼 때"],
        "not_for": ["실제 서버 변경"],
        "examples": ["도움말", "뭐 할 수 있어?"],
        "security": ["Read-only command catalog."],
    },
}


def field_contracts(port_start: int, port_end: int) -> dict[str, dict[str, Any]]:
    return {
        "project": {
            "type": "name",
            "label": "프로젝트 이름",
            "rules": "영문, 숫자, 점(.), 밑줄(_), 하이픈(-)만 가능하며 64자 이하입니다.",
            "question": "프로젝트 이름을 알려주세요.",
            "examples": ["demoa", "horse_race", "my-app"],
            "normalization": "사용자가 조사나 짧은 확인 표현을 붙여도 값 후보로 해석할 수 있습니다.",
            "semantic_hint": (
                "관리 namespace 이름입니다. project-scoped CLI에서는 이미 고정되어 있으므로 "
                "사용자에게 다시 묻지 않습니다. root/admin CLI에서만 필요합니다."
            ),
        },
        "service": {
            "type": "name",
            "label": "서비스 이름",
            "rules": "영문, 숫자, 점(.), 밑줄(_), 하이픈(-)만 가능하며 64자 이하입니다.",
            "question": "서비스 이름을 알려주세요.",
            "examples": ["frontend", "backend", "api"],
            "semantic_hint": (
                "Compose service/container 이름입니다. 보통 frontend, front, backend, api처럼 "
                "짧은 식별자입니다. GitHub URL이나 framework 값과 같은 문장에 함께 올 수 있습니다."
            ),
        },
        "repo_url": {
            "type": "github_https_url",
            "label": "공개 GitHub HTTPS 저장소 URL",
            "rules": "https://github.com/<owner>/<repo> 형태만 허용합니다.",
            "question": "배포할 공개 GitHub HTTPS 저장소 URL을 알려주세요.",
            "examples": ["https://github.com/owner/repository"],
            "semantic_hint": (
                "소스 코드 위치입니다. 반드시 GitHub HTTPS URL이어야 하며, 비공개 저장소나 "
                "토큰/비밀번호는 이 필드에 넣지 않습니다."
            ),
        },
        "framework": {
            "type": "enum",
            "label": "프레임워크 프리셋",
            "rules": "framework.list 또는 schema enum에 있는 값만 허용합니다.",
            "question": "프레임워크 프리셋을 선택해주세요.",
            "examples": ["static", "vite", "react", "nextjs", "fastapi"],
            "semantic_hint": (
                "Dockerfile 템플릿 선택값입니다. 사용자가 'javascript'처럼 넓게 말하면 "
                "확정하지 말고 static/vite/react/nextjs/express 후보 차이를 설명합니다."
            ),
        },
        "container_port": {
            "type": "integer",
            "label": "컨테이너 포트",
            "rules": "1~65535 사이 정수입니다. 생략하면 프레임워크 기본값 3000을 사용합니다.",
            "question": "앱이 컨테이너 내부에서 리슨하는 포트를 알려주세요.",
            "examples": [3000, 8000],
        },
        "host_port": {
            "type": "integer",
            "label": "호스트 포트",
            "rules": f"{port_start}~{port_end} 사이 정수입니다. 웹 서비스에서만 사용합니다.",
            "question": "외부에 공개할 호스트 포트를 알려주세요. 생략하면 자동 추천합니다.",
            "examples": [9000, 9001],
        },
        "is_web": {
            "type": "boolean",
            "label": "외부 공개 웹 서비스 여부",
            "rules": "프론트엔드는 true, 내부 백엔드/API는 false입니다.",
            "question": "외부에 공개할 웹 서비스인가요, 내부 통신 전용 서비스인가요?",
            "examples": [True, False],
            "semantic_hint": (
                "true면 host_port를 열어 외부 URL 대상이 됩니다. false면 프로젝트 app network 내부 "
                "통신 전용으로 보고 외부 URL/host_port를 만들지 않습니다."
            ),
        },
        "environment_names": {
            "type": "string_array",
            "label": "환경변수 이름 목록",
            "rules": "비밀값은 받지 않고 변수 이름만 받습니다.",
            "question": "필요한 환경변수 이름이 있으면 이름만 알려주세요.",
            "examples": [["DATABASE_URL", "API_KEY"]],
            "semantic_hint": (
                "변수 이름만 받습니다. 실제 secret 값은 LLM/채팅에 넣지 않고 대시보드 보안 입력에서 설정합니다."
            ),
        },
        "action": {
            "type": "enum",
            "label": "서비스 제어 동작",
            "rules": "start, stop, restart 중 하나입니다.",
            "question": "서비스를 시작, 중지, 재시작 중 무엇으로 제어할까요?",
            "examples": ["start", "stop", "restart"],
        },
        "operation": {
            "type": "enum",
            "label": "포트 변경 작업",
            "rules": "suggest, change_host, change_container 중 하나입니다.",
            "question": "호스트 포트를 바꿀지, 컨테이너 포트를 바꿀지 알려주세요.",
            "examples": ["suggest", "change_host", "change_container"],
        },
        "lines": {
            "type": "integer",
            "label": "로그 줄 수",
            "rules": "1~100 사이 정수입니다. 기본값은 40입니다.",
            "question": "몇 줄의 로그를 볼까요?",
            "examples": [40, 100],
        },
        "entity": {
            "type": "enum",
            "label": "탐색 대상 종류",
            "rules": "project, service, framework 중 하나입니다.",
            "question": "프로젝트, 서비스, 프레임워크 중 무엇을 찾을까요?",
            "examples": ["project", "service", "framework"],
        },
        "query": {
            "type": "string",
            "label": "검색어",
            "rules": "CLI가 실제 목록과 유사도를 비교할 이름입니다.",
            "question": "찾을 이름이나 검색어를 알려주세요.",
            "examples": ["demoa", "frontend", "vite"],
        },
    }


def field_contract(
    field: str,
    *,
    required: bool,
    port_start: int,
    port_end: int,
    label: str | None = None,
) -> dict[str, Any]:
    contract = dict(field_contracts(port_start, port_end).get(field, {}))
    contract.setdefault("type", "string")
    contract.setdefault("label", label or field)
    contract.setdefault("question", f"{contract['label']} 값을 알려주세요.")
    contract["name"] = field
    contract["field"] = field
    contract["required"] = required
    if label:
        contract["label"] = label
    return contract


def build_command_contract(
    skill: str,
    *,
    document: dict[str, Any] | None,
    schema: dict[str, Any],
    read_only: bool,
    port_start: int,
    port_end: int,
) -> dict[str, Any]:
    field_order = COMMAND_FIELD_ORDER.get(skill, {"required": [], "optional": []})
    required = list(field_order.get("required", []))
    optional = list(field_order.get("optional", []))
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    if not required and not optional and properties:
        required = list(schema.get("required") or [])
        optional = [field for field in properties if field not in required]
    fields = [
        field_contract(field, required=True, port_start=port_start, port_end=port_end)
        for field in required
    ] + [
        field_contract(field, required=False, port_start=port_start, port_end=port_end)
        for field in optional
        if field not in required
    ]
    for item in fields:
        prop = properties.get(item["name"], {})
        for key in ("enum", "default", "minimum", "maximum"):
            if key in prop:
                item[key] = prop[key]
        if "description" in prop:
            item["schema_description"] = prop["description"]
    help_info = dict(COMMAND_HELP.get(skill, {}))
    return {
        "skill": skill,
        "title": help_info.get("title", skill),
        "description": (document or {}).get("description", ""),
        "role": help_info.get("role", (document or {}).get("description", "")),
        "use_when": help_info.get("use_when", []),
        "not_for": help_info.get("not_for", []),
        "ambiguous_with": help_info.get("ambiguous_with", []),
        "clarification_question": help_info.get("clarification_question"),
        "examples": help_info.get("examples", []),
        "flow": help_info.get("flow", []),
        "after_success": help_info.get("after_success", []),
        "security": help_info.get("security", COMMON_SECURITY if not read_only else ["Read-only."]),
        "ui": help_info.get("ui", {}),
        "mode": "read" if read_only else "mutation",
        "read_only": read_only,
        "dry_run": not read_only,
        "requires_approval": not read_only,
        "fields": fields,
        "required_fields": required,
        "optional_fields": optional,
        "schema": schema,
        "response_contract": {
            "needs_input": {
                "status": "needs_input",
                "missing": "array of missing field contracts",
                "next_question": "single next user-facing question",
            },
            "ready": {
                "status": "ready",
                "preview": "execution plan returned by dry-run",
                "requires_approval": not read_only,
            },
            "executed": {
                "status": "executed",
                "result": "verified execution result",
            },
            "invalid": {
                "status": "invalid",
                "message": "validation error",
            },
        },
    }


def build_command_contracts(contracts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "commands": contracts,
        "planner_rule": PLANNER_RULE,
    }


def build_command_catalog(skills: list[str], contracts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "machine_readable": True,
        "planner_rule": PLANNER_RULE,
        "commands": {
            "help": "Show the command catalog and human-readable task guide",
            "commands": "Show all machine-readable command contracts",
            "schema <skill>": "Show one machine-readable command contract",
            "skills": "List allowlisted skills and raw JSON schemas",
            "describe <skill>": "Describe one skill document",
            "projects": "List valid and incomplete projects",
            "frameworks": "List framework presets",
            "resolve <entity> <query>": "Resolve a project, service, or framework against live CLI data",
            "inspect-repo <url>": "Inspect a public GitHub repository read-only",
            "status <project> [service]": "Show live Compose and Docker service status",
            "logs <project> <service>": "Show a bounded tail of service logs",
            "preview <skill>": "Validate and preview a mutation",
            "execute <skill>": "Execute a skill; mutations require approval",
        },
        "task_guide": [
            {
                "skill": item["skill"],
                "title": item["title"],
                "role": item["role"],
                "use_when": item["use_when"],
                "not_for": item["not_for"],
                "ambiguous_with": item["ambiguous_with"],
                "clarification_question": item["clarification_question"],
                "required_fields": item["required_fields"],
                "optional_fields": item["optional_fields"],
                "examples": item["examples"],
                "requires_approval": item["requires_approval"],
            }
            for item in contracts
        ],
        "examples": [
            "cloud-platform projects",
            "cloud-platform frameworks",
            "cloud-platform resolve project horserace",
            "cloud-platform inspect-repo https://github.com/owner/repository",
            "cloud-platform status demoa demo-a",
            "cloud-platform logs demoa demo-a --lines 40",
            "cloud-platform schema service.deploy",
            "cloud-platform preview service.deploy --arguments '{...}'",
        ],
        "skills": sorted(skills),
    }
