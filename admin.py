import streamlit as st
import subprocess
from pathlib import Path
import os
import time
import urllib.request
import yaml
import docker
import shutil
import psutil
import requests
from deployment_presets import (
    DEFAULT_CONTAINER_PORT,
    FRAMEWORK_PRESETS,
    framework_manual,
)

# --- 설정값 ---
PROJECTS_ROOT = Path("/srv/projects")
START_PORT = 9000
END_PORT = 9100
SKILL_AGENT_URL = os.getenv("SKILL_AGENT_URL", "http://skill-agent:8080").rstrip("/")


# --- Dockerfile 템플릿 (설명을 위한 용도) ---
def get_general_build_tips():
    return """
    ### 📘 Core Principles
    1. **모든 Git 저장소는 Public**으로 설정되어 있어야 합니다. (자동 클론/빌드를 위해)
    2. **매뉴얼을 참고하여 각자의 언어(React, python...)에 맞는** 세팅을 깃헙 레포지토리에 추가해주세요.
    (배포하려는 서비스의 Git 저장소 최상위(루트) 디렉토리에 Dockerfile과 (필요하다면) nginx.conf 같은 설정 파일들이 위치해야 합니다.)
    3. **모든 컨테이너의 내부 포트 번호를 일치**시켜야 합니다. (Default : 모두 3000)
    4. 생성 후 서비스별 **환경변수 관리** 버튼을 통해 각 서비스마다 환경변수 값을 설정해주세요.
    """


def get_react_build_tips():
    return """
    ### 💡 Build Tips for React/Frontend (Nginx)
    React, Vue, Svelte 등 **컴파일이 필요한 프론트엔드** 프로젝트의 표준 방식입니다. **멀티 스테이지 빌드**를 사용하여 최종 이미지 크기를 획기적으로 줄입니다.

    #### 1. `Dockerfile`
    ```dockerfile
    # --- 1. 빌드 스테이지 ---
    FROM node:20-alpine AS builder
    WORKDIR /app
    COPY package.json package-lock.json* ./

    # --- 환경변수 설정 예시 ---
    # ARG REACT_APP_API_KEY
    # ENV REACT_APP_API_KEY=$REACT_APP_API_KEY

    ENV NODE_OPTIONS="--max-old-space-size=4096"
    RUN npm install --omit=dev
    COPY . .
    RUN npm run build

    # --- 2. 프로덕션 스테이지 ---
    FROM nginx:stable-alpine
    COPY --from=builder /app/build /usr/share/nginx/html
    COPY nginx.conf /etc/nginx/conf.d/default.conf
    # 모든파일의 컨테이너 내부포트를 반드시 일치시켜야해요(default : 3000)
    EXPOSE 3000
    CMD ["nginx", "-g", "daemon off;"]
    ```

    #### 2. `nginx.conf`
    React Router와 백엔드 API 프록시를 위한 필수 설정입니다. 프론트엔드에서 백엔드와 통신하고 싶은 경우 이 파일을 반드시 당신의 Git 저장소 최상단에 포함시켜야 합니다.

    **[설정 설명]**
    *   `location /`: 사용자가 웹사이트에 접속했을 때 React 앱을 보여주는 설정입니다. `try_files`는 React Router가 새로고침 시에도 '404 Not Found' 오류 없이 정상 작동하도록 해줍니다.
    *   `location /api/`: **가장 중요한 부분입니다.** React 앱에서 `/api/`로 시작하는 모든 네트워크 요청을 가로채, `docker-compose.yml`에 정의된 `backend` 서비스로 전달해줍니다. 이를 통해 CORS 오류를 완벽하게 해결할 수 있습니다.
    *   `location /healthz`: 로드 밸런서나 모니터링 시스템이 이 컨테이너가 살아있는지 쉽게 확인할 수 있도록 간단한 `OK` 응답을 반환하는 엔드포인트입니다. (운영 환경 권장 사항)
    ```nginx
    server {
      listen 3000; # 컨테이너 내부에서 사용할 포트

      # 1. React 앱 라우팅 (메인 페이지 및 기타 경로)
      location / {
        root   /usr/share/nginx/html;
        index  index.html;
        # 이 설정은 어떤 경로로 접속하든 index.html을 먼저 보여주게 하여
        # React Router가 클라이언트 사이드 라우팅을 할 수 있게 해줍니다.
        try_files $uri /index.html;
      }

      # 2. 백엔드 API 프록시 설정 (CORS 해결)
      # React 코드에서는 fetch('/api/users') 와 같이 요청을 보내면 됩니다.
      location /api/ {
        # 'backend'는 docker-compose.yml에 정의된 백엔드 서비스의 이름이어야 합니다.
        # 백엔드 컨테이너의 내부 포트가 3000번이라면 'http://backend:3000/' 으로 수정하세요.
        proxy_pass http://backend:3000/;
        
        # 실제 요청 정보를 백엔드 서버로 전달하기 위한 헤더 설정
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
      }
      
      # 3. 헬스 체크 엔드포인트 (운영 환경 권장)
      location /healthz {
        # 항상 '200 OK'를 반환하여 서비스가 살아있음을 알림
        return 200 'OK';
        add_header Content-Type text/plain;
      }
    }
    ```
    """


def get_backend_build_tips():
    return """
    ### 💡 Build Tips for Python/Backend (Django, FastAPI)
    Python과 같은 **인터프리터 언어** 프로젝트의 표준 방식입니다. 프로덕션용 WSGI/ASGI 서버(Gunicorn, Uvicorn)를 사용합니다.

    #### 1. `Dockerfile`
    **_`your_project.wsgi`와 `requirements.txt` 부분을 당신의 프로젝트에 맞게 수정해야 합니다._**
    ```dockerfile
    FROM python:3.11-slim
    WORKDIR /app

    # --- 환경변수 설정 예시 ---
    # ARG DATABASE_URL
    # ENV DATABASE_URL=$DATABASE_URL

    COPY requirements.txt .
    RUN pip install --no-cache-dir -r requirements.txt
    COPY . .
    # 모든파일의 컨테이너 내부포트를 반드시 일치시켜야해요(default : 3000)
    EXPOSE 3000
    # 모든파일의 컨테이너 내부포트를 반드시 일치시켜야해요(default : 0.0.0.0:3000)
    CMD ["gunicorn", "--bind", "0.0.0.0:3000", "your_project.wsgi:application"]
    ```

    #### 2. `requirements.txt`
    `gunicorn`을 반드시 포함해야 합니다.
    ```txt
    django
    gunicorn
    # ... other libraries
    ```
    """


def get_other_build_tips():
    return """
    ### 📘 Tips for Dockerfile
    모든 `Dockerfile`은 두 가지 원칙 중 하나를 따릅니다.

    ---

    #### 1. 컴파일 언어 (React, Vue, Java, Go, Rust 등)
    **"무거운 도구로 빌드하고, 가벼운 결과물만 실행한다" (Multi-stage Build)**

    *   **1단계 (Builder):** Java의 `maven`이나 Go의 `golang`처럼 개발 도구가 모두 포함된 무거운 이미지를 사용합니다. 여기서 코드를 컴파일하여 `.jar` 파일이나 실행 파일을 만듭니다.
    *   **2단계 (Runner):** `openjdk:jre-slim`이나 `alpine`처럼 실행에 필요한 최소한의 환경만 있는 가벼운 이미지를 사용합니다. `COPY --from=builder` 명령으로 1단계에서 만든 결과물만 복사
  해와서 실행합니다.

    ---

    #### 2. 인터프리터 언어 (Python, Node.js, Ruby 등)
    **"의존성을 설치하고, 프로덕션용 서버로 실행한다"**

    *   `pip`, `npm`, `bundle` 등으로 필요한 라이브러리를 설치합니다.
    *   가장 중요한 것은, 개발용 명령어가 아닌 **`gunicorn`, `pm2`, `puma`** 와 같은 프로덕션용 프로세스 매니저/웹 서버로 앱을 실행해야 안정적입니다.
    """


# --- Helper 함수들
def get_public_ip() -> str:
    if 'public_ip' in st.session_state and st.session_state.public_ip:
        return st.session_state.public_ip
    configured_ip = os.getenv("PUBLIC_IP", "").strip()
    if configured_ip:
        st.session_state.public_ip = configured_ip
        return configured_ip

    for url in (
        "http://169.254.169.254/latest/meta-data/public-ipv4",
        "https://ifconfig.me/ip",
    ):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                ip = response.read().decode().strip()
            if ip and '.' in ip:
                st.session_state.public_ip = ip
                return ip
        except Exception:
            continue
    return None


def get_projects() -> list:
    if not PROJECTS_ROOT.exists(): PROJECTS_ROOT.mkdir(parents=True)
    return sorted([
        d.name
        for d in PROJECTS_ROOT.iterdir()
        if d.is_dir() and (d / "docker-compose.yml").is_file()
    ])


def get_incomplete_projects() -> list:
    if not PROJECTS_ROOT.exists():
        return []
    return sorted([
        d.name
        for d in PROJECTS_ROOT.iterdir()
        if d.is_dir() and not (d / "docker-compose.yml").is_file()
    ])


def get_project_services(project_name: str) -> (dict, dict):
    project_path = PROJECTS_ROOT / project_name
    compose_file = project_path / "docker-compose.yml"
    service_metadata = {}
    if compose_file.exists():
        with open(compose_file, 'r') as f:
            try:
                data = yaml.safe_load(f)
                if data and 'services' in data:
                    for s_name, s_config in data['services'].items():
                        build_info = s_config.get('build', {})
                        context = build_info.get('context', '.') if isinstance(build_info, dict) else build_info
                        folder = context.replace('./', '')
                        is_web = "is_web_service=true" in s_config.get('labels', [])
                        service_metadata[s_name] = {'folder': folder, 'is_web': is_web}
            except yaml.YAMLError:
                pass
    docker_status = {}
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"label": f"com.docker.compose.project={project_name}"})
        for container in containers:
            service_name = container.labels.get('com.docker.compose.service')
            if service_name:
                ports = container.ports;
                port_num = "N/A"
                for host_ports in ports.values():
                    if host_ports: port_num = host_ports[0]['HostPort']; break
                docker_status[service_name] = {'port': port_num, 'status': container.status.capitalize(),
                                               'id': container.short_id}
    except docker.errors.DockerException:
        st.error("Docker is not running.")
    return service_metadata, docker_status


def get_published_ports(port_config) -> set:
    if isinstance(port_config, dict):
        published = port_config.get('published')
        if published is None:
            return set()
        published = str(published)
        if '-' in published:
            start, end = published.split('-', 1)
            if start.isdigit() and end.isdigit():
                return set(range(int(start), int(end) + 1))
            return set()
        return {int(published)} if published.isdigit() else set()
    elif not isinstance(port_config, str):
        return set()

    value = port_config.split('/')[0]
    parts = value.rsplit(':', 2)
    if len(parts) < 2:
        return set()

    published = parts[-2]
    if '-' in published:
        start, end = published.split('-', 1)
        if start.isdigit() and end.isdigit():
            return set(range(int(start), int(end) + 1))
        return set()
    return {int(published)} if published.isdigit() else set()


def get_reserved_host_ports() -> set:
    reserved_ports = set()

    if PROJECTS_ROOT.exists():
        for compose_file in PROJECTS_ROOT.glob("*/docker-compose.yml"):
            try:
                with open(compose_file, 'r') as f:
                    compose_data = yaml.safe_load(f) or {}
                for service in compose_data.get('services', {}).values():
                    for port_config in service.get('ports', []):
                        reserved_ports.update(get_published_ports(port_config))
            except (OSError, yaml.YAMLError, AttributeError):
                continue

    try:
        client = docker.from_env()
        for container in client.containers.list(all=True):
            port_bindings = container.attrs.get('HostConfig', {}).get('PortBindings', {}) or {}
            for bindings in port_bindings.values():
                for binding in bindings or []:
                    host_port = str(binding.get('HostPort', ''))
                    if host_port.isdigit():
                        reserved_ports.add(int(host_port))
    except docker.errors.DockerException:
        pass

    return reserved_ports


def find_next_available_port() -> int:
    reserved_ports = get_reserved_host_ports()
    for port in range(START_PORT, END_PORT + 1):
        if port not in reserved_ports:
            return port
    raise RuntimeError(f"No available host ports between {START_PORT} and {END_PORT}.")


def start_service(project_name: str, project_path: Path, service_name: str) -> None:
    subprocess.run(
        ["docker-compose", "-p", project_name, "up", "-d", "--no-build", service_name],
        cwd=project_path,
        check=True,
        capture_output=True,
    )

    client = docker.from_env()
    filters = {
        "label": [
            f"com.docker.compose.project={project_name}",
            f"com.docker.compose.service={service_name}",
        ]
    }
    containers = client.containers.list(all=True, filters=filters)
    if not containers:
        raise RuntimeError(f"Container for '{service_name}' was not created.")

    container = containers[0]
    container.reload()
    initial_restart_count = container.attrs.get("RestartCount", 0)
    time.sleep(4)
    container.reload()
    restart_count = container.attrs.get("RestartCount", 0)

    if container.status != "running" or restart_count > initial_restart_count:
        logs = container.logs(tail=20).decode(errors="replace").strip()
        detail = logs or f"Container status: {container.status}"
        raise RuntimeError(f"Service '{service_name}' failed to stay running.\n\n{detail}")


def skill_agent_request(path: str, payload: dict | None = None) -> dict:
    url = f"{SKILL_AGENT_URL}{path}"
    if payload is None:
        response = requests.get(url, timeout=10)
    else:
        response = requests.post(url, json=payload, timeout=320)
    if response.ok:
        return response.json()
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    raise RuntimeError(f"Skill Agent error ({response.status_code}): {detail}")


def render_assistant_message(message: dict) -> None:
    st.markdown(message["text"])
    if message.get("data") is not None:
        with st.expander("Result", expanded=False):
            st.json(message["data"])


# --- UI 및 메인 로직 ---
st.set_page_config(layout="wide")
st.title("자동 배포 시스템")

if 'last_action_message' in st.session_state:
    message = st.session_state.last_action_message
    st.toast(message)
    del st.session_state.last_action_message

# IP 주소는 백그라운드에서만 가져오고, UI에는 직접 표시하지 않습니다.
public_ip = get_public_ip()

with st.sidebar:
    st.toggle("AI Assistant", key="assistant_visible", value=False)
    st.markdown("---")
    st.header("Server Monitor")
    cpu_usage = psutil.cpu_percent()
    st.progress(int(cpu_usage), text=f"CPU Usage: {cpu_usage}%")
    mem_info = psutil.virtual_memory()
    mem_usage = mem_info.percent
    st.progress(int(mem_usage),
                text=f"Memory: {mem_usage}% ({mem_info.used / 1024 ** 3:.1f}GB / {mem_info.total / 1024 ** 3:.1f}GB)")
    disk_info = psutil.disk_usage('/')
    disk_usage = disk_info.percent
    st.progress(int(disk_usage),
                text=f"Disk: {disk_usage}% ({disk_info.used / 1024 ** 3:.1f}GB / {disk_info.total / 1024 ** 3:.1f}GB)")
    st.markdown("---")

    st.header("Project Management")
    projects = get_projects()
    selected_project = st.selectbox("관리할 프로젝트 선택", options=projects, key="project_selector")
    incomplete_projects = get_incomplete_projects()
    if incomplete_projects:
        st.warning(
            "Compose 파일이 없어 복구가 필요한 프로젝트: "
            + ", ".join(incomplete_projects)
        )

      # --- [추가된 부분] 프로젝트 선택이 변경되면 모달 관련 상태를 모두 초기화 ---
      # 이전에 선택된 프로젝트를 session_state에 저장하여 변경 여부를 감지
    if 'last_project' not in st.session_state:
                st.session_state.last_project = selected_project


    if st.session_state.last_project != selected_project:
        for key in ['show_env_modal', 'show_env_folder', 'env_vars']:
            if key in st.session_state:
                del st.session_state[key]
        st.session_state.last_project = selected_project


    with st.expander("📁 신규 프로젝트 추가"):
        with st.form("new_project_form"):
            new_project_name = st.text_input("새 프로젝트 이름")
            if st.form_submit_button("생성"):
                try:
                    result = skill_agent_request(
                        "/preview",
                        {
                            "skill": "project.create",
                            "arguments": {"project": new_project_name},
                        },
                    )
                    st.session_state.assistant_pending = {
                        "skill": "project.create",
                        "arguments": {"project": new_project_name},
                        "preview": result["preview"],
                    }
                    st.session_state.assistant_visible = True
                    st.rerun()
                except (requests.RequestException, RuntimeError) as exc:
                    st.error(f"프로젝트 생성 계획 실패: {exc}")

if st.session_state.get("assistant_visible"):
    if "assistant_messages" not in st.session_state:
        st.session_state.assistant_messages = [
            {
                "role": "assistant",
                "text": (
                    "Docker 배포 작업을 자연어로 요청할 수 있습니다.\n\n"
                    "- `서버 상태를 확인해줘`\n"
                    "- `프로젝트와 서비스 목록 보여줘`\n"
                    "- `새 프로젝트를 만들고 싶어`\n"
                    "- `demoa의 demo-a 상태를 확인해줘`\n"
                    "- `GitHub 저장소를 새 서비스로 배포해줘`\n"
                    "- `기존 서비스를 최신 코드로 재배포해줘`\n"
                    "- `사용 가능한 포트를 추천해줘`\n\n"
                    "전체 기능과 예시는 `도움말`을 입력해 확인하세요. "
                    "서버를 변경하는 작업은 실행 전에 승인을 요청합니다."
                ),
            }
        ]

    with st.container(border=True):
        header_col, status_col = st.columns((4, 1))
        header_col.subheader("Deployment Assistant")
        try:
            agent_health = skill_agent_request("/health")
            status_col.success("LLM" if agent_health["llm_configured"] else "Skill mode")
        except (requests.RequestException, RuntimeError):
            status_col.error("Offline")

        for chat_message in st.session_state.assistant_messages:
            with st.chat_message(chat_message["role"]):
                render_assistant_message(chat_message)

        pending = st.session_state.get("assistant_pending")
        if pending:
            st.warning("This action changes the server and requires approval.")
            st.json(pending["preview"])
            approve_col, cancel_col = st.columns(2)
            if approve_col.button("Approve", type="primary", use_container_width=True):
                try:
                    with st.spinner("Executing and verifying..."):
                        executed = skill_agent_request(
                            "/execute",
                            {
                                "skill": pending["skill"],
                                "arguments": pending["arguments"],
                                "approved": True,
                            },
                        )
                    st.session_state.assistant_messages.append(
                        {
                            "role": "assistant",
                            "text": (
                                f"`{pending['skill']}` 실행과 검증이 완료됐습니다.\n\n"
                                + (
                                    "프로젝트가 준비됐습니다. 이제 `서비스를 새로 배포하고 싶어`라고 "
                                    "입력하면 저장소와 포트 정보를 이어서 안내받을 수 있습니다."
                                    if pending["skill"] == "project.create"
                                    else ""
                                )
                            ),
                            "data": executed["result"],
                        }
                    )
                    if pending["skill"] == "project.create" and pending.get("resume"):
                        resume = pending["resume"]
                        resume.setdefault("arguments", {})["project"] = pending["arguments"]["project"]
                        st.session_state.assistant_clarification = resume
                    else:
                        st.session_state.pop("assistant_clarification", None)
                except (requests.RequestException, RuntimeError) as exc:
                    st.session_state.assistant_messages.append(
                        {"role": "assistant", "text": f"실행에 실패했습니다: {exc}"}
                    )
                del st.session_state["assistant_pending"]
                st.rerun()
            if cancel_col.button("Cancel", use_container_width=True):
                st.session_state.assistant_messages.append(
                    {"role": "assistant", "text": "요청한 변경을 취소했습니다."}
                )
                del st.session_state["assistant_pending"]
                st.rerun()

        if prompt := st.chat_input("명령 또는 질문 입력 · 전체 기능은 '도움말'"):
            st.session_state.assistant_messages.append({"role": "user", "text": prompt})
            try:
                with st.spinner("Selecting and running a skill..."):
                    payload = {"message": prompt}
                    clarification = st.session_state.get("assistant_clarification")
                    if clarification:
                        payload["context"] = clarification
                    answer = skill_agent_request("/chat", payload)
                if answer.get("requires_approval"):
                    st.session_state.pop("assistant_clarification", None)
                    st.session_state.assistant_pending = {
                        "skill": answer["skill"],
                        "arguments": answer["arguments"],
                        "preview": answer["preview"],
                        "resume": answer.get("resume"),
                    }
                    assistant_text = (
                        f"{answer['message']} `{answer['skill']}` 실행 전 검증이 통과했습니다. "
                        "아래 계획을 확인하고 승인해주세요."
                    )
                    assistant_data = answer["preview"]
                elif answer.get("kind") == "clarification":
                    st.session_state.assistant_clarification = answer["context"]
                    assistant_text = answer["message"]
                    assistant_data = {
                        "필요한 정보": [
                            item["label"] for item in answer.get("missing", [])
                        ],
                        "현재까지 파악한 값": answer.get("arguments", {}),
                    }
                    if answer.get("choices"):
                        assistant_data["선택 가능한 작업"] = [
                            item["label"] for item in answer["choices"]
                        ]
                else:
                    st.session_state.pop("assistant_clarification", None)
                    if answer.get("kind") in {"help", "guide"}:
                        assistant_text = answer["message"]
                    else:
                        assistant_text = f"{answer['message']} 사용한 Skill: `{answer['skill']}`"
                    assistant_data = answer.get("result")
                st.session_state.assistant_messages.append(
                    {"role": "assistant", "text": assistant_text, "data": assistant_data}
                )
            except (requests.RequestException, RuntimeError) as exc:
                st.session_state.assistant_messages.append(
                    {"role": "assistant", "text": f"요청 처리에 실패했습니다: {exc}"}
                )
            st.rerun()

if selected_project:
    st.header(f"Dashboard: [{selected_project}]")
    project_path = PROJECTS_ROOT / selected_project
    compose_file = project_path / "docker-compose.yml"
    service_metadata, docker_status = get_project_services(selected_project)

    with st.sidebar.expander("Live Container Stats", expanded=True):
        if not any(s.get('status') == 'Running' for s in docker_status.values()):
            st.write("No running containers for this project.")
        else:
            try:
                client = docker.from_env()
                for service_name, status_info in sorted(docker_status.items()):
                    if status_info.get('status') == 'Running':
                        container = client.containers.get(status_info['id'])
                        stats = container.stats(stream=False)
                        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage'][
                            'total_usage']
                        system_cpu_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats'][
                            'system_cpu_usage']
                        number_cpus = stats['cpu_stats']['online_cpus']
                        cpu_percent = (
                                              cpu_delta / system_cpu_delta) * number_cpus * 100.0 if system_cpu_delta > 0 else 0
                        mem_usage = stats['memory_stats']['usage'] / (1024 * 1024)
                        mem_limit = stats['memory_stats']['limit'] / (1024 * 1024)
                        st.write(f"**{service_name}** (`{status_info['id']}`)")
                        st.progress(int(cpu_percent), text=f"CPU: {cpu_percent:.1f}%")
                        st.progress(int(mem_usage / mem_limit * 100), text=f"MEM: {mem_usage:.1f}MB")
            except (docker.errors.DockerException, KeyError):
                st.write("Could not retrieve container stats.")

    if st.button(f"Update Entire Project(모든 서비스 최신화): [{selected_project}]", type="primary", use_container_width=True):
        with st.spinner(f"Updating all services in '{selected_project}'..."):
            try:
                for service_info in service_metadata.values():
                    service_path = project_path / service_info['folder']
                    if service_path.exists() and (service_path / ".git").is_dir():
                        subprocess.run(["git", "fetch", "origin"], cwd=service_path, check=True, capture_output=True)
                        subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=service_path, check=True,
                                       capture_output=True)

                if compose_file.exists():
                    # 1. 먼저 새로 빌드합니다.
                    subprocess.run(["docker-compose", "-p", selected_project, "build", "--no-cache"],
                                   cwd=project_path, check=True, capture_output=True)

                    # 2. 기존의 손상되었을 수 있는 컨테이너를 'down'으로 확실하게 제거합니다. (핵심 수정)
                    subprocess.run(["docker-compose", "-p", selected_project, "down"],
                                   cwd=project_path, check=True, capture_output=True)

                    # 3. 깨끗한 상태에서 새로 빌드된 이미지로 컨테이너를 올립니다.
                    subprocess.run(["docker-compose", "-p", selected_project, "up", "-d"],
                                   cwd=project_path, check=True, capture_output=True)

                st.session_state.last_action_message = (f"✅ Project '{selected_project}' updated!");
                st.rerun()
            except subprocess.CalledProcessError as e:
                st.error("Update failed:")
                st.code(e.stderr.decode(), language='bash')

    st.markdown("---")

    if not service_metadata:
        st.info("이 프로젝트에 추가된 서비스가 없습니다.")
    else:
        # Adjusted columns to make more space for action buttons
        cols = st.columns((3, 3, 2, 2, 1, 4))
        cols[0].write("**Service Name**");
        cols[1].write("**Folder**");
        cols[2].write("**Status**")
        cols[3].write("**Port**");
        cols[4].write("**URL**");
        cols[5].write("**Actions**")
        st.markdown("---")

        for service_name, meta in sorted(service_metadata.items()):
            status_info = docker_status.get(service_name, {});
            cols = st.columns((3, 3, 2, 2, 1, 4))
            cols[0].write(service_name);
            cols[1].write(meta['folder'])
            status = status_info.get('status', 'Stopped')
            if status == 'Running':
                cols[2].success(status)
            else:
                cols[2].error(status)
            port = status_info.get('port', '-');
            cols[3].write(port)
            if meta['is_web'] and str(port).isdigit() and public_ip:
                cols[4].link_button("Open", f"http://{public_ip}:{port}")
            else:
                cols[4].write("-")

            with cols[5]:
                # Using 3 columns for 3 action buttons
                action_cols = st.columns(3)
                if status == 'Running':
                    if action_cols[0].button("🟥", key=f"stop_{service_name}", help="Stop", use_container_width=True):
                        try:
                            subprocess.run(["docker-compose", "-p", selected_project, "stop", service_name],
                                           cwd=project_path, check=True, capture_output=True)
                            st.session_state.last_action_message = (f"🛑 Service '{service_name}' stopped.");
                            st.rerun()
                        except subprocess.CalledProcessError as e:
                            st.error(e.stderr.decode())
                else:
                    if action_cols[0].button("🟩", key=f"start_{service_name}", help="Start", use_container_width=True):
                        try:
                            start_service(selected_project, project_path, service_name)
                            st.session_state.last_action_message = (f"✅ Service '{service_name}' started!");
                            st.rerun()
                        except subprocess.CalledProcessError as e:
                            st.error(e.stderr.decode())
                        except (docker.errors.DockerException, RuntimeError) as e:
                            st.error(str(e))

                # Environment Variable Button
                if action_cols[1].button("⚙️", key=f"env_{service_name}", help="Environment Variables",
                                         use_container_width=True):
                    st.session_state.show_env_modal = service_name
                    st.session_state.show_env_folder = meta['folder']
                    st.session_state.env_vars = []
                    try:
                        with open(compose_file, "r") as f:
                            compose_data = yaml.safe_load(f) or {}
                        current_environment = (
                            compose_data.get("services", {})
                            .get(service_name, {})
                            .get("environment", {})
                        )
                        if isinstance(current_environment, dict):
                            st.session_state.env_vars = [
                                {"key": key, "value": value or ""}
                                for key, value in current_environment.items()
                            ]
                    except Exception as e:
                        st.error(f"환경변수 로드 오류: {e}")

                # Delete Button
                if action_cols[2].button("🗑️", key=f"delete_{service_name}", help="Delete", use_container_width=True):
                    st.session_state[f"confirm_delete_{service_name}"] = True

            if st.session_state.get(f"confirm_delete_{service_name}"):
                st.warning(f"**WARNING:** '{service_name}'의 모든 것을 영구적으로 삭제하시겠습니까?")
                confirm_cols = st.columns(2)
                if confirm_cols[0].button("✅ Confirm Delete", key=f"confirm_delete_btn_{service_name}",
                                          use_container_width=True, type="primary"):
                    with st.spinner(f"Deleting service '{service_name}'..."):
                        try:
                            subprocess.run(["docker-compose", "-p", selected_project, "rm", "-sfv", service_name],
                                           cwd=project_path, check=True, capture_output=True)
                            with open(compose_file, 'r') as f:
                                compose_data = yaml.safe_load(f)
                            if service_name in compose_data['services']: del compose_data['services'][service_name]
                            with open(compose_file, 'w') as f:
                                yaml.dump(compose_data, f, sort_keys=False)
                            shutil.rmtree(project_path / meta['folder'])
                            st.session_state.last_action_message = (f"🗑️ Service '{service_name}' has been deleted.");
                            del st.session_state[f"confirm_delete_{service_name}"];
                            st.rerun()
                        except Exception as e:
                            st.error(f"Deletion failed: {e}")
                if confirm_cols[1].button("Cancel", key=f"cancel_delete_{service_name}", use_container_width=True):
                    del st.session_state[f"confirm_delete_{service_name}"];
                    st.rerun()
            st.markdown("---")

    if 'show_env_modal' in st.session_state and st.session_state.show_env_modal:
        # 이 블록의 변수들은 dialog 제목 표시에만 사용합니다.
        service_name_in_title = st.session_state.show_env_modal
        service_folder_for_modal = st.session_state.show_env_folder


        @st.dialog(f"Environment Variables for {service_name_in_title}", width="large")
        def show_env_modal():
            # 함수 안에서는 session_state에서 직접 값을 가져와 사용합니다.
            current_service_name = st.session_state.show_env_modal
            st.info(
                "값은 LLM이나 채팅으로 전송되지 않고 Compose 서비스의 런타임 환경변수로 저장됩니다. "
                "저장 후 해당 서비스만 재생성합니다."
            )

            if 'env_vars' not in st.session_state:
                st.session_state.env_vars = []

            # --- [수정된 부분 1] ---
            # 삭제할 인덱스를 임시로 저장할 변수
            index_to_delete = None

            # Display current variables
            for i in range(len(st.session_state.env_vars)):
                var = st.session_state.env_vars[i]
                # --- [수정된 부분 2] ---
                # vertical_alignment를 추가하여 UI 정렬 개선
                cols = st.columns([5, 5, 1], vertical_alignment="bottom")

                new_key = cols[0].text_input("Variable Name", value=var.get('key', ''), key=f"key_{i}")
                new_value = cols[1].text_input(
                    "Variable Value",
                    value=var.get('value', ''),
                    key=f"value_{i}",
                    type="password",
                )
                st.session_state.env_vars[i] = {'key': new_key, 'value': new_value}

                if cols[2].button("➖", key=f"del_var_{i}", help="Remove variable"):
                    # --- [수정된 부분 3] ---
                    # 즉시 삭제하는 대신, 삭제할 인덱스를 기록
                    index_to_delete = i

            # --- [수정된 부분 4] ---
            # 루프가 끝난 후, 삭제할 인덱스가 있으면 실제 삭제를 수행
            if index_to_delete is not None:
                st.session_state.env_vars.pop(index_to_delete)
                st.rerun()

            if st.button("➕ Add Variable"):
                st.session_state.env_vars.append({})
                st.rerun()

            st.markdown("---")

            if st.button("환경변수 저장", type="primary"):
                try:
                    with st.spinner(f"'{current_service_name}' 환경변수를 저장 중입니다..."):
                        with open(compose_file, 'r') as f:
                            compose_data = yaml.safe_load(f) or {}

                        service_def = compose_data['services'][current_service_name]
                        service_def['environment'] = {
                            var.get('key', '').strip(): var.get('value', '')
                            for var in st.session_state.env_vars if var.get('key')
                        }
                        with open(compose_file, 'w') as f:
                            yaml.dump(compose_data, f, sort_keys=False)
                        subprocess.run(
                            [
                                "docker-compose",
                                "-p",
                                selected_project,
                                "up",
                                "-d",
                                "--force-recreate",
                                "--no-build",
                                current_service_name,
                            ],
                            cwd=project_path,
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=300,
                        )

                    st.session_state.last_action_message = f"Variables for '{current_service_name}' saved."
                    del st.session_state['show_env_modal']
                    del st.session_state['env_vars']
                    st.rerun()

                except Exception as e:
                    st.error(f"An unexpected error occurred: {e}")

        show_env_modal()

    st.markdown("---")
    with st.expander("🚨 프로젝트 폴더 전체 삭제"):
        st.error(f"**WARNING:** 이 작업은 되돌릴 수 없습니다. '{selected_project}'의 모든 것을 삭제합니다.")
        if st.checkbox(f"위 내용을 이해했으며, '{selected_project}' 프로젝트 삭제를 원합니다.", key="project_delete_confirm"):
            if st.button("🔥 Permanently Delete This Project", type="primary"):
                with st.spinner(f"Deleting project '{selected_project}'..."):
                    try:
                        if compose_file.exists():
                            subprocess.run(["docker-compose", "-p", selected_project, "down", "--volumes"],
                                           cwd=project_path, check=True, capture_output=True)
                        shutil.rmtree(project_path)
                        st.session_state.last_action_message = (
                            f"🗑️  Project '{selected_project}' has been permanently deleted.");
                        st.rerun()
                    except Exception as e:
                        st.error(f"Project deletion failed: {e}")

    st.markdown("---")
    st.subheader(f"✚ Add New Service to [{selected_project}]")
    with st.expander("📘 Show Build Manual & Tips", expanded=False):
        manual_options = ["Core Principles", *FRAMEWORK_PRESETS.keys()]
        tip_selection = st.selectbox("Framework manual", manual_options, index=0)
        if tip_selection == "Core Principles":
            st.markdown(get_general_build_tips())
        else:
            st.markdown(framework_manual(tip_selection))

    with st.form("new_service_form"):
        st.write(
            "GitHub 저장소와 프레임워크만 선택하면 기본 Dockerfile과 컨테이너 포트 "
            f"`{DEFAULT_CONTAINER_PORT}`을 자동 적용합니다."
        )
        service_name = st.text_input("새 서비스 이름 (예: frontend)")
        git_url = st.text_input("Public GitHub Repository URL")
        framework = st.selectbox(
            "Framework preset",
            options=list(FRAMEWORK_PRESETS),
            format_func=lambda key: FRAMEWORK_PRESETS[key]["label"],
            index=1,
        )
        is_web_service = st.checkbox("사용자 화면(프론트엔드) 서비스인가요? (바로가기 링크 생성)", value=True)
        suggested_env = FRAMEWORK_PRESETS[framework]["environment"]
        env_names_text = st.text_input(
            "환경변수 이름 (선택, 쉼표로 구분)",
            value=", ".join(suggested_env),
            help="이름만 등록합니다. 실제 값은 배포 후 서비스의 ⚙️ 버튼에서 안전하게 입력하세요.",
        )

        if st.form_submit_button("배포 계획 확인"):
            if not all([service_name, git_url]):
                st.warning("모든 필드를 입력하세요.")
            elif service_name in service_metadata:
                st.error("이미 존재하는 서비스 이름입니다.")
            else:
                arguments = {
                    "project": selected_project,
                    "service": service_name,
                    "repo_url": git_url,
                    "framework": framework,
                    "is_web": is_web_service,
                    "environment_names": [
                        item.strip()
                        for item in env_names_text.split(",")
                        if item.strip()
                    ],
                }
                try:
                    result = skill_agent_request(
                        "/preview",
                        {"skill": "service.deploy", "arguments": arguments},
                    )
                    st.session_state.service_deploy_preview = {
                        "arguments": arguments,
                        "preview": result["preview"],
                    }
                    st.rerun()
                except (requests.RequestException, RuntimeError) as exc:
                    st.error(f"배포 계획 생성 실패: {exc}")

    deploy_preview = st.session_state.get("service_deploy_preview")
    if deploy_preview:
        st.info("아래 설정과 실행 단계를 확인한 뒤 승인해주세요.")
        preview = deploy_preview["preview"]
        st.markdown(
            f"""
- **프로젝트:** `{preview['project']}`
- **서비스:** `{preview['service']}`
- **프레임워크:** `{FRAMEWORK_PRESETS[preview['framework']]['label']}`
- **Dockerfile:** {preview['dockerfile']}
- **포트:** `{preview['host_port']} → {preview['container_port']}`
- **환경변수 이름:** `{', '.join(preview['environment_names']) or '없음'}`
- **프리셋 권장 환경변수:** `{', '.join(preview['suggested_environment_names']) or '없음'}`

실제 환경변수 값은 LLM에 전송되지 않으며 배포 후 ⚙️ 버튼에서 입력합니다.
"""
        )
        with st.expander("실행 단계 및 프레임워크 매뉴얼", expanded=False):
            for number, step in enumerate(preview["steps"], start=1):
                st.write(f"{number}. {step}")
            st.markdown(preview["framework_manual"])
        approve_col, cancel_col = st.columns(2)
        if approve_col.button("이 설정으로 배포", type="primary", use_container_width=True):
            try:
                with st.spinner(f"Deploying '{preview['service']}'..."):
                    result = skill_agent_request(
                        "/execute",
                        {
                            "skill": "service.deploy",
                            "arguments": deploy_preview["arguments"],
                            "approved": True,
                        },
                    )
                st.session_state.last_action_message = (
                    f"✅ Service '{preview['service']}' deployed on port "
                    f"{result['result']['host_port']}!"
                )
                del st.session_state["service_deploy_preview"]
                st.rerun()
            except (requests.RequestException, RuntimeError) as exc:
                st.error(f"배포 실패: {exc}")
        if cancel_col.button("취소", use_container_width=True):
            del st.session_state["service_deploy_preview"]
            st.rerun()
else:
    st.info("사이드바에서 관리할 프로젝트를 선택하거나 새 프로젝트를 추가하세요.")
