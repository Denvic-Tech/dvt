# syntax=docker/dockerfile:1.7

FROM dvt_deps_image AS deps-builder

COPY services/project_scheduler/requirements.txt /app/requirements.txt

RUN  --mount=type=cache,target=/root/.cache/uv,id=uv-cache-py3.13,sharing=locked \
    uv pip install --no-index --system --find-links=/wheelhouse \
    -r /app/requirements.txt

FROM dvt_dev_builder_image AS base-builder

FROM dvt_base_image AS project_scheduler

COPY --from=deps-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=deps-builder /usr/local/bin /usr/local/bin
COPY --from=deps-builder /usr/lib /usr/lib
COPY --from=deps-builder /usr/include /usr/include
COPY --from=deps-builder /lib /lib
COPY --from=deps-builder /lib64 /lib64

COPY --from=base-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base-builder /build /build
COPY --from=base-builder /app /app

EXPOSE ${PROJECT_SCHEDULER_PORT}

COPY services/__init__.py /app/services/__init__.py
COPY services/project_scheduler /app/services/project_scheduler

ENV SERVICE_NAME=project_scheduler

CMD python3 -m uvicorn --host ${PROJECT_SCHEDULER_HOST} --port ${PROJECT_SCHEDULER_PORT} services.project_scheduler.main:app
