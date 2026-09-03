# syntax=docker/dockerfile:1.7

FROM dvt_deps_image AS deps-builder

COPY services/orchestrator/requirements.txt /app/requirements.txt

RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache-py3.13,sharing=locked \
    uv pip install --no-index --system --find-links=/wheelhouse \
    -r /app/requirements.txt

FROM dvt_prod_builder_image AS base-builder

FROM dvt_base_image AS orchestrator

COPY --from=deps-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=deps-builder /usr/local/bin /usr/local/bin
COPY --from=deps-builder /usr/lib /usr/lib
COPY --from=deps-builder /usr/include /usr/include
COPY --from=deps-builder /lib /lib
COPY --from=deps-builder /lib64 /lib64

COPY --from=base-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base-builder /app /app

COPY services/orchestrator /app/services/orchestrator

ENV SERVICE_NAME=orchestrator

CMD bash -c "python3 -m services.orchestrator"
