# syntax=docker/dockerfile:1.7

FROM dvt_deps_image AS deps-builder

COPY services/task_benchmarking/requirements.txt /app/requirements.txt

RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache-py3.13,sharing=locked \
    uv pip install --no-index --system --find-links=/wheelhouse \
    -r /app/requirements.txt

FROM dvt_dev_builder_image AS base-builder

FROM dvt_base_image AS memory-benchmark

RUN if command -v apt-get >/dev/null 2>&1; then \
        apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*; \
    elif command -v apk >/dev/null 2>&1; then \
        apk add --no-cache git; \
    else \
        echo "No known package manager found to install git"; \
        exit 1; \
    fi

COPY --from=deps-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=deps-builder /usr/local/bin /usr/local/bin
COPY --from=deps-builder /usr/lib /usr/lib
COPY --from=deps-builder /usr/include /usr/include
COPY --from=deps-builder /lib /lib
COPY --from=deps-builder /lib64 /lib64

COPY --from=base-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base-builder /build /build
COPY --from=base-builder /app /app

COPY services/__init__.py /app/services/__init__.py
COPY services/task_benchmarking /app/services/task_benchmarking
COPY core /app/core
COPY src /app/src

WORKDIR /app

ENTRYPOINT ["python3", "-m", "services.task_benchmarking.main"]
