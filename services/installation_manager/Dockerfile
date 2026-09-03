# syntax=docker/dockerfile:1.9

# ---------- Сборка фронтенда ----------
FROM node:20-alpine AS frontend

WORKDIR /frontend
COPY services/installation_manager/frontend/package.json ./
RUN npm install
COPY services/installation_manager/frontend/ ./
RUN npm run build

# ---------- Бэкенд ----------
FROM python:3.13-slim AS runner

COPY docker/apt/configure-debian-mirrors.sh /usr/local/bin/configure-debian-mirrors
RUN sh /usr/local/bin/configure-debian-mirrors

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Docker CLI + Compose plugin
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin docker-buildx-plugin \
    && apt-get purge -y curl gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY services/installation_manager/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/installation_manager /app/services/installation_manager
RUN rm -rf /app/services/installation_manager/frontend

# Статика вне /app: в dev-режиме репозиторий монтируется поверх /app
# (./:/app в docker-compose.dev.yaml) и скрыл бы собранный фронтенд
COPY --from=frontend /frontend/dist /static

ENV PYTHONPATH=/app
ENV UPDATE_SERVICE_STATIC_DIR=/static

EXPOSE 8000

ENTRYPOINT ["python", "-m", "services.installation_manager"]
