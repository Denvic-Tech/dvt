# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS base-builder

COPY docker/apt/configure-debian-mirrors.sh /usr/local/bin/configure-debian-mirrors
RUN sh /usr/local/bin/configure-debian-mirrors

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates g++ libpq-dev git build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN python -m pip install build wheel setuptools

# All public DVT runtime dependencies must resolve anonymously from public
# package indexes. Do not add Git credentials or private index rewrites here.
ENV PIP_INDEX_URL="https://pypi.org/simple"

COPY services/gateway/requirements.txt /app/requirements.gateway.txt
COPY services/task_worker/requirements.txt /app/requirements.task_worker.txt
COPY services/orchestrator/requirements.txt /app/requirements.orchestrator.txt
COPY services/tester/requirements.txt /app/requirements.tester.txt
COPY requirements.txt /app/requirements.project.txt

RUN mkdir -p /wheelhouse

RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-py3.13 set -eux; \
    for f in /app/requirements.*.txt; do \
        echo ">>> Downloading wheels/sdists for $f"; \
        python -m pip download -r "$f" -d /wheelhouse; \
    done

RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-py3.13 set -eux; \
    find /wheelhouse -type f \( -name '*.tar.*' -o -name '*.zip' \) -print0 \
      | xargs -0 -I{} python -m pip wheel {} -w /wheelhouse; \
    find /wheelhouse -type f ! -name '*.whl' -delete

RUN rm -rf ~/.cache/pip
RUN ls -lh /wheelhouse | sort

FROM python:3.13-slim AS base

COPY --from=base-builder /wheelhouse /wheelhouse
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
RUN uv --version
