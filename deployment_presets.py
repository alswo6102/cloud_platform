from __future__ import annotations

from typing import Any

DEFAULT_CONTAINER_PORT = 3000

FRAMEWORK_PRESETS: dict[str, dict[str, Any]] = {
    "existing": {
        "label": "기존 Dockerfile 사용",
        "category": "Custom",
        "description": "저장소 루트의 Dockerfile을 그대로 사용합니다.",
        "environment": [],
    },
    "static": {
        "label": "Static HTML / JavaScript",
        "category": "Frontend",
        "description": "빌드 없이 HTML, CSS, JavaScript 파일을 Nginx가 3000번 포트로 제공합니다.",
        "environment": [],
    },
    "vite": {
        "label": "Vite (React/Vue/Svelte)",
        "category": "Frontend",
        "description": "Node에서 빌드하고 Nginx가 3000번 포트로 dist를 제공합니다.",
        "environment": ["VITE_API_URL"],
    },
    "react": {
        "label": "Create React App",
        "category": "Frontend",
        "description": "Node에서 빌드하고 Nginx가 3000번 포트로 build를 제공합니다.",
        "environment": ["REACT_APP_API_URL"],
    },
    "nextjs": {
        "label": "Next.js",
        "category": "Fullstack",
        "description": "패키지 잠금 파일을 감지해 설치하고 next start를 3000번에서 실행합니다.",
        "environment": ["NEXT_PUBLIC_API_URL"],
    },
    "express": {
        "label": "Express / NestJS",
        "category": "Backend",
        "description": "Node 애플리케이션을 PORT=3000으로 실행합니다.",
        "environment": ["NODE_ENV", "DATABASE_URL"],
    },
    "fastapi": {
        "label": "FastAPI",
        "category": "Backend",
        "description": "main.py 또는 app.py의 app 객체를 Uvicorn으로 3000번에서 실행합니다.",
        "environment": ["DATABASE_URL", "SECRET_KEY"],
    },
    "flask": {
        "label": "Flask",
        "category": "Backend",
        "description": "app.py의 app 객체를 Gunicorn으로 3000번에서 실행합니다.",
        "environment": ["FLASK_ENV", "SECRET_KEY"],
    },
    "django": {
        "label": "Django",
        "category": "Backend",
        "description": "manage.py에서 Django 프로젝트 모듈을 감지해 Gunicorn으로 실행합니다.",
        "environment": ["DJANGO_SETTINGS_MODULE", "SECRET_KEY", "DATABASE_URL"],
    },
    "spring-maven": {
        "label": "Spring Boot (Maven)",
        "category": "Backend",
        "description": "Maven으로 JAR을 빌드하고 SERVER_PORT=3000으로 실행합니다.",
        "environment": ["SPRING_PROFILES_ACTIVE", "SPRING_DATASOURCE_URL"],
    },
    "spring-gradle": {
        "label": "Spring Boot (Gradle)",
        "category": "Backend",
        "description": "Gradle로 JAR을 빌드하고 SERVER_PORT=3000으로 실행합니다.",
        "environment": ["SPRING_PROFILES_ACTIVE", "SPRING_DATASOURCE_URL"],
    },
    "go": {
        "label": "Go HTTP",
        "category": "Backend",
        "description": "Go 모듈을 빌드하고 PORT=3000을 기본 환경변수로 제공합니다.",
        "environment": ["PORT"],
    },
}


def preset_catalog() -> list[dict[str, Any]]:
    return [
        {"id": key, **value, "container_port": DEFAULT_CONTAINER_PORT}
        for key, value in FRAMEWORK_PRESETS.items()
    ]


def validate_framework(framework: str) -> str:
    if framework not in FRAMEWORK_PRESETS:
        raise ValueError(f"Unsupported framework preset: {framework}")
    return framework


def framework_manual(framework: str) -> str:
    preset = FRAMEWORK_PRESETS[validate_framework(framework)]
    env_names = ", ".join(preset["environment"]) or "없음"
    return (
        f"### {preset['label']}\n\n"
        f"{preset['description']}\n\n"
        f"- 기본 컨테이너 포트: `{DEFAULT_CONTAINER_PORT}`\n"
        f"- 권장 환경변수 이름: `{env_names}`\n"
        "- 고급 설정이 필요한 저장소는 기존 Dockerfile 사용을 선택하세요.\n"
        "- 생성되는 Dockerfile은 서버의 clone에만 적용되며 원본 GitHub 저장소는 변경하지 않습니다."
    )


def render_dockerfile(framework: str) -> str:
    framework = validate_framework(framework)
    if framework == "existing":
        raise ValueError("The existing preset does not generate a Dockerfile")

    templates = {
        "static": """FROM nginx:stable-alpine
COPY . /usr/share/nginx/html
RUN printf 'server { listen 3000; location / { root /usr/share/nginx/html; index index.html main.html; try_files $uri $uri/ /index.html /main.html; } location /healthz { return 200 "OK"; } }' > /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
""",
        "vite": """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build

FROM nginx:stable-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
RUN printf 'server { listen 3000; location / { root /usr/share/nginx/html; try_files $uri /index.html; } location /healthz { return 200 "OK"; } }' > /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
""",
        "react": """FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build

FROM nginx:stable-alpine
COPY --from=builder /app/build /usr/share/nginx/html
RUN printf 'server { listen 3000; location / { root /usr/share/nginx/html; try_files $uri /index.html; } location /healthz { return 200 "OK"; } }' > /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
""",
        "nextjs": """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build
ENV NODE_ENV=production
ENV PORT=3000
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-p", "3000"]
""",
        "express": """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build --if-present
ENV NODE_ENV=production
ENV PORT=3000
EXPOSE 3000
CMD ["npm", "start"]
""",
        "fastapi": """FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; else pip install --no-cache-dir .; fi
RUN pip install --no-cache-dir uvicorn
EXPOSE 3000
CMD ["sh", "-c", "if [ -f main.py ]; then exec uvicorn main:app --host 0.0.0.0 --port 3000; else exec uvicorn app:app --host 0.0.0.0 --port 3000; fi"]
""",
        "flask": """FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; else pip install --no-cache-dir .; fi
RUN pip install --no-cache-dir gunicorn
EXPOSE 3000
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "app:app"]
""",
        "django": """FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; else pip install --no-cache-dir .; fi
RUN pip install --no-cache-dir gunicorn
EXPOSE 3000
CMD ["sh", "-c", "MODULE=${DJANGO_SETTINGS_MODULE%%.settings}; if [ -z \\"$MODULE\\" ]; then MODULE=$(find . -mindepth 2 -maxdepth 2 -name wsgi.py | head -1 | cut -d/ -f2); fi; exec gunicorn --bind 0.0.0.0:3000 ${MODULE}.wsgi:application"]
""",
        "spring-maven": """FROM maven:3.9-eclipse-temurin-21 AS builder
WORKDIR /app
COPY pom.xml .
RUN mvn -q -DskipTests dependency:go-offline
COPY . .
RUN mvn -q -DskipTests package

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=builder /app/target/*.jar app.jar
ENV SERVER_PORT=3000
EXPOSE 3000
CMD ["java", "-jar", "app.jar"]
""",
        "spring-gradle": """FROM gradle:8-jdk21 AS builder
WORKDIR /app
COPY . .
RUN gradle bootJar --no-daemon

FROM eclipse-temurin:21-jre
WORKDIR /app
COPY --from=builder /app/build/libs/*.jar app.jar
ENV SERVER_PORT=3000
EXPOSE 3000
CMD ["java", "-jar", "app.jar"]
""",
        "go": """FROM golang:1.24-alpine AS builder
WORKDIR /app
COPY . .
RUN go mod download
RUN CGO_ENABLED=0 go build -o /out/app .

FROM alpine:3.21
WORKDIR /app
COPY --from=builder /out/app /app/app
ENV PORT=3000
EXPOSE 3000
CMD ["/app/app"]
""",
    }
    return templates[framework]
