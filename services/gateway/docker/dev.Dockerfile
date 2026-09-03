# syntax=docker/dockerfile:1.7

FROM dvt_deps_image AS deps-builder

COPY services/gateway/requirements.txt /app/requirements.txt

RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache-py3.13,sharing=locked \
    uv pip install --no-index --system --find-links=/wheelhouse \
    -r /app/requirements.txt

FROM dvt_dev_builder_image AS base-builder

FROM dvt_base_odbc_image AS gateway

COPY --from=deps-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=deps-builder /usr/local/bin /usr/local/bin
COPY --from=deps-builder /usr/lib /usr/lib
COPY --from=deps-builder /usr/include /usr/include
COPY --from=deps-builder /lib /lib
COPY --from=deps-builder /lib64 /lib64

COPY --from=base-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base-builder /build /build
COPY --from=base-builder /app /app

EXPOSE ${GATEWAY_PORT}

COPY services/__init__.py /app/services/__init__.py
COPY services/gateway /app/services/gateway
COPY scripts/health/check_gateway_health.py /app/scripts/health/check_gateway_health.py
COPY locales /app/locales
COPY tests /app/tests
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations

ENV SERVICE_NAME=gateway

CMD bash -c "python3 -m services.gateway.migrate && python3 -m uvicorn --host ${GATEWAY_HOST} --port ${GATEWAY_PORT} services.gateway.main:app"
