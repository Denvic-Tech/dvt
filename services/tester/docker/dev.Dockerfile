# syntax=docker/dockerfile:1.7

FROM dvt_deps_image AS deps-builder

COPY requirements.txt /tmp/requirements.project.txt
COPY services/gateway/requirements.txt /tmp/requirements.gateway.txt
COPY services/orchestrator/requirements.txt /tmp/requirements.orchestrator.txt
COPY services/task_benchmarking/requirements.txt /tmp/requirements.task_benchmarking.txt
COPY services/project_scheduler/requirements.txt /tmp/requirements.project_scheduler.txt
COPY services/task_worker/requirements.txt /tmp/requirements.task_worker.txt
COPY services/tester/requirements.txt /tmp/requirements.tester.txt

RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache-py3.13,sharing=locked \
    set -euo pipefail; \
    req=/tmp/all-requirements.txt; \
    printf '%s\n' \
      '-r /tmp/requirements.project.txt' \
      '-r /tmp/requirements.gateway.txt' \
      '-r /tmp/requirements.orchestrator.txt' \
      '-r /tmp/requirements.task_benchmarking.txt' \
      '-r /tmp/requirements.project_scheduler.txt' \
      '-r /tmp/requirements.task_worker.txt' \
      '-r /tmp/requirements.tester.txt' \
      > "$req"; \
    uv pip install --no-index --system --find-links=/wheelhouse -r "$req"

FROM dvt_dev_builder_image AS base-builder

FROM dvt_base_odbc_image AS base

COPY --from=deps-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=deps-builder /usr/local/bin /usr/local/bin
COPY --from=deps-builder /usr/lib /usr/lib
COPY --from=deps-builder /usr/include /usr/include
COPY --from=deps-builder /lib /lib
COPY --from=deps-builder /lib64 /lib64

COPY --from=base-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base-builder /app /app

COPY . /app

CMD ["bash", "-lc", "python -V"]

