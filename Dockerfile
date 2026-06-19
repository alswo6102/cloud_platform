FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG DOCKER_VERSION=28.2.2
ARG COMPOSE_VERSION=v2.29.7

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
    && curl -fsSL --retry 3 \
        "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VERSION}.tgz" \
        | tar -xz -C /usr/local/bin --strip-components=1 docker/docker \
    && curl -fsSL --retry 3 \
        "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
        -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker /usr/local/bin/docker-compose \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY admin.py .

EXPOSE 8501

CMD ["streamlit", "run", "admin.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
