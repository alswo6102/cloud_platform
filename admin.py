import streamlit as st
import subprocess
from pathlib import Path
import json
import socket
import pandas as pd
import yaml
import docker
import shutil
import psutil
from dockerfile_parse import DockerfileParser

# --- 설정값 ---
PROJECTS_ROOT = Path("/srv/projects")
START_PORT = 9001


# --- Dockerfile 템플릿 (설명을 위한 용도) ---
def get_general_build_tips():
    return """
    ### 📘 Core Principles
    1. **모든 Git 저장소는 Public**으로 설정되어 있어야 합니다. (자동 클론/빌드를 위해)
    2. **매뉴얼을 참고하여 각자의 언어(React, python...)에 맞는** 세팅을 깃헙 레포지토리에 추가해주세요.
    3. **모든 컨테이너의 내부 포트 번호를 일치**시켜야 합니다. (Default : 모두 3000)
    4. 배포하려는 서비스의 Git 저장소 최상위(루트) 디렉토리에 Dockerfile과 (필요하다면) nginx.conf 같은 설정 파일들이 위치해야 합니다.
    5. (필요하다면) 서비스별 **환경변수 관리** 버튼을 통해 ARG/ENV 값을 설정해주세요.
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
    React Router 사용 시 새로고침해도 404 에러가 나지 않도록 하는 필수 설정입니다.
    ```nginx
    server {
      # 모든파일의 컨테이너 내부포트를 반드시 일치시켜야해요(default : 3000)
      listen 3000;
      location / {
        root   /usr/share/nginx/html;
        index  index.html index.htm;
        try_files $uri $uri/ /index.html;
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
    try:
        cmd = ["curl", "-s", "http://169.254.169.254/latest/meta-data/public-ipv4", "--connect-timeout", "2"]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        ip = result.stdout.strip()
        if ip and '.' in ip: st.session_state.public_ip = ip; return ip
    except:
        pass
    try:
        cmd = ["curl", "-s", "ifconfig.me", "--connect-timeout", "2"]
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        ip = result.stdout.strip()
        if ip and '.' in ip: st.session_state.public_ip = ip; return ip
    except:
        pass
    return None


def get_projects() -> list:
    if not PROJECTS_ROOT.exists(): PROJECTS_ROOT.mkdir(parents=True)
    return sorted([d.name for d in PROJECTS_ROOT.iterdir() if d.is_dir()])


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


def find_next_available_port() -> int:
    port = START_PORT
    while is_port_in_use(port): port += 1
    return port


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


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

    with st.expander("📁 신규 프로젝트 추가"):
        with st.form("new_project_form"):
            new_project_name = st.text_input("새 프로젝트 이름")
            if st.form_submit_button("생성"):
                if new_project_name and new_project_name.isalnum():
                    (PROJECTS_ROOT / new_project_name).mkdir(exist_ok=True)
                    st.session_state.last_action_message = (f"✅ Project '{new_project_name}' created!");
                    st.rerun()
                else:
                    st.warning("프로젝트 이름을 영문/숫자로 입력하세요.")

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
        st.warning("모든 서비스의 원격 Git 저장소 코드를 pull 합니다. 로컬에서 수정한 Dockerfile이 덮어씌워질 수 있습니다. 계속하시겠습니까?")
        if st.button("Confirm Update"):
            with st.spinner(f"Updating all services in '{selected_project}'..."):
                try:
                    for service_info in service_metadata.values():
                        service_path = project_path / service_info['folder']
                        if service_path.exists() and (service_path / ".git").is_dir():
                            # Stash local changes, pull, and then pop. This is safer.
                            subprocess.run(["git", "stash"], cwd=service_path, check=True, capture_output=True)
                            subprocess.run(["git","pull", "origin", "main"], cwd=service_path, check=True,
                                           capture_output=True)
                            subprocess.run(["git", "reset", "--hard", "origin", "main"], cwd=service_path, check=True,
                                           capture_output=True)
                    if compose_file.exists():
                        subprocess.run(["docker-compose", "-p", selected_project, "build", "--no-cache"],
                                       cwd=project_path, check=True, capture_output=True)
                        subprocess.run(["docker-compose", "-p", selected_project, "up", "-d", "--force-recreate"],
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
                cols[4].markdown(f"[🔗 Link](http://{public_ip}:{port})", unsafe_allow_html=True)
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
                            subprocess.run(["docker-compose", "-p", selected_project, "start", service_name],
                                           cwd=project_path, check=True, capture_output=True)
                            st.session_state.last_action_message = (f"✅ Service '{service_name}' started!");
                            st.rerun()
                        except subprocess.CalledProcessError as e:
                            st.error(e.stderr.decode())

                # Environment Variable Button
                if action_cols[1].button("⚙️", key=f"env_{service_name}", help="Environment Variables",
                                         use_container_width=True):
                    st.session_state.show_env_modal = service_name
                    st.session_state.show_env_folder = meta['folder']
                    # Initialize env_vars in session state when the button is clicked
                    st.session_state.env_vars = []
                    dockerfile_path = project_path / meta['folder'] / "Dockerfile"
                    if dockerfile_path.exists():
                        try:
                            dfp = DockerfileParser(path=str(dockerfile_path))
                            # Find all ARG keys first, this is safe
                            args = {inst['value'].split('=')[0].strip(): None for inst in dfp.structure if
                                    inst['instruction'].upper() == 'ARG'}

                            for inst in dfp.structure:
                                if inst['instruction'].upper() == 'ENV':
                                    env_line = inst['value']
                                    parts = []
                                    # Safely parse both "KEY=VALUE" and "KEY VALUE" formats
                                    if '=' in env_line:
                                        parts = env_line.split('=', 1)
                                    else:
                                        parts = env_line.split(None, 1)

                                    # Only proceed if we successfully unpacked into two parts
                                    if len(parts) == 2:
                                        key, val = parts
                                        key = key.strip()
                                        # Only show variables in the UI that are paired with an ARG
                                        if key in args:
                                            val = val.strip().replace(f'${{{key}}}', '').replace(f'${key}', '')
                                            st.session_state.env_vars.append({'key': key, 'value': val})
                        except Exception as e:
                            st.error(f"Dockerfile 파싱 오류: {e}")

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

    # --- Environment Variable Modal Logic ---
    if 'show_env_modal' in st.session_state and st.session_state.show_env_modal:
        service_name = st.session_state.show_env_modal
        service_folder_for_modal = st.session_state.show_env_folder


        @st.dialog(f"Environment Variables for {service_name}", width="large")
        def show_env_modal():
            service_path = project_path / service_folder_for_modal
            dockerfile_path = service_path / "Dockerfile"

            st.info("Dockerfile에 `ARG VAR_NAME`과 `ENV VAR_NAME=$VAR_NAME` 형식으로 추가/수정됩니다.")

            if 'env_vars' not in st.session_state:
                st.session_state.env_vars = []

            # Display current variables
            for i in range(len(st.session_state.env_vars)):
                var = st.session_state.env_vars[i]
                cols = st.columns([5, 5, 1])
                new_key = cols[0].text_input("Variable Name", value=var.get('key', ''), key=f"key_{i}")
                new_value = cols[1].text_input("Variable Value", value=var.get('value', ''), key=f"value_{i}")
                st.session_state.env_vars[i] = {'key': new_key, 'value': new_value}
                if cols[2].button("➖", key=f"del_var_{i}", help="Remove variable"):
                    st.session_state.env_vars.pop(i)
                    st.rerun()

            if st.button("➕ Add Variable"):
                st.session_state.env_vars.append({})
                st.rerun()

            st.markdown("---")

            if st.button("환경변수 저장", type="primary"):
                with st.spinner(f"'{service_name}' 환경변수를 저장 중입니다..."):
                    try:
                        if not dockerfile_path.exists():
                            st.error(f"Dockerfile not found at {dockerfile_path}")
                            st.stop()

                        dfp = DockerfileParser(path=str(dockerfile_path))

                        # Get the keys of variables we are managing from the UI state
                        managed_keys = {var.get('key', '').strip() for var in st.session_state.env_vars if
                                        var.get('key')}

                        # Preserve ARG/ENV instructions that are NOT managed by our UI
                        other_instructions = []
                        for inst in dfp.structure:
                            inst_type = inst['instruction'].upper()
                            if inst_type in ('ARG', 'ENV'):
                                # Extract key. Handles "KEY=VALUE" and "KEY VALUE"
                                key = inst['value'].split('=', 1)[0].split(None, 1)[0].strip()
                                if key not in managed_keys:
                                    other_instructions.append(inst['content'])
                            else:
                                other_instructions.append(inst['content'])

                        # Create new ARG/ENV instructions
                        new_env_instructions = []
                        for var in st.session_state.env_vars:
                            key = var.get('key', '').strip()
                            value = var.get('value', '').strip()
                            if key:  # Only add if key is not empty
                                new_env_instructions.append(f"ARG {key}")
                                new_env_instructions.append(f"ENV {key}={value}")

                        # Find a good place to insert them (e.g., after the first FROM)
                        insert_pos = 1
                        for i, inst in enumerate(dfp.structure):
                            if inst['instruction'].upper() == 'FROM':
                                insert_pos = i + 1
                                break

                        final_instructions = other_instructions[
                                                 :insert_pos] + new_env_instructions + other_instructions[insert_pos:]

                        with open(dockerfile_path, "w") as f:
                            f.write("\n".join(final_instructions))

                        st.session_state.last_action_message = (f"✅ '{service_name}' 환경변수를 저장했습니다.")
                        del st.session_state['show_env_modal']
                        del st.session_state['env_vars']
                        st.rerun()

                    except subprocess.CalledProcessError as e:
                        st.error(f"An error occurred: {e.stderr}")
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
        tip_selection = st.selectbox(
            "Select a service type for build tips:",
            ["Core Principles", "React/Frontend (Nginx)", "Python/Backend", "Other Languages"],
            index=0
        )

        if tip_selection == "Core Principles":
            st.markdown(get_general_build_tips())
        elif tip_selection == "React/Frontend (Nginx)":
            st.markdown(get_react_build_tips())
        elif tip_selection == "Python/Backend":
            st.markdown(get_backend_build_tips())
        elif tip_selection == "Other Languages":
            st.markdown(get_other_build_tips())

    with st.form("new_service_form"):
        st.write("위 **Build Manual을 반드시 참고**하여 당신의 Git Repository에 필요한 파일들을 준비해주세요.")
        service_name = st.text_input("새 서비스 이름 (예: frontend)")
        git_url = st.text_input("Git Repository URL")
        container_port = st.number_input("컨테이너 내부 포트 (Dockerfile의 EXPOSE 또는 CMD에서 사용하는 포트)", value=3000)
        is_web_service = st.checkbox("사용자 화면(프론트엔드) 서비스인가요? (바로가기 링크 생성)", value=True)

        if st.form_submit_button("추가 및 배포"):
            if not all([service_name, git_url]):
                st.warning("모든 필드를 입력하세요.")
            elif service_name in service_metadata:
                st.error("이미 존재하는 서비스 이름입니다.")
            else:
                with st.spinner(f"Adding service '{service_name}'..."):
                    service_path = project_path / service_name
                    try:
                        subprocess.run(["git", "clone", git_url, str(service_path)], check=True, capture_output=True)
                        if not (service_path / "Dockerfile").exists():
                            st.error(f"배포 실패: '{service_path}' 폴더 안에 Dockerfile이 없습니다. 위 매뉴얼을 확인해주세요.");
                            shutil.rmtree(service_path)  # Clean up failed clone
                            st.stop()

                        compose_data = {'version': '3.8', 'services': {}}
                        if compose_file.exists():
                            with open(compose_file, 'r') as f:
                                loaded = yaml.safe_load(f)
                                if loaded: compose_data = loaded

                        new_port = find_next_available_port()
                        service_definition = {
                            'build': {'context': f'./{service_name}'}, 'restart': 'always',
                            'ports': [f"{new_port}:{container_port}"], 'mem_limit': '1g', 'memswap_limit': '3g'
                        }
                        if is_web_service:
                            service_definition['labels'] = ["is_web_service=true"]

                        compose_data.setdefault('services', {})[service_name] = service_definition

                        with open(compose_file, 'w') as f:
                            yaml.dump(compose_data, f, default_flow_style=False, sort_keys=False)

                        # Build and start the newly added service
                        subprocess.run(["docker-compose", "-p", selected_project, "up", "-d", "--build", service_name],
                                       cwd=project_path, check=True, capture_output=True)

                        st.session_state.last_action_message = (
                            f"✅ Service '{service_name}' deployed on port {new_port}!")
                        st.rerun()

                    except subprocess.CalledProcessError as e:
                        st.error(f"Failed: {e.stderr.decode()}")
                    except Exception as e:
                        st.error(f"An error occurred: {e}")
else:
    st.info("사이드바에서 관리할 프로젝트를 선택하거나 새 프로젝트를 추가하세요.")
