# syntax=docker/dockerfile:1.7

FROM dvt_base_image AS base-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY docker/requirements.txt /app/docker/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-py3.13 \
    python -m pip install -r /app/docker/requirements.txt

# Ensure build directory exists for images that expect it
RUN mkdir -p /build

# gRPC
COPY contracts/pyproject.toml /app/contracts/pyproject.toml
COPY contracts/protos /app/contracts/protos
RUN mkdir -p /app/contracts/src && \
    python -m grpc_tools.protoc \
      -I /app/contracts/protos \
      --python_out /app/contracts/src \
      --grpc_python_out /app/contracts/src \
      $(find /app/contracts/protos -name "*.proto")

RUN pip install -e /app/contracts --force-reinstall

# Copy sources
COPY core /app/core
COPY src /app/src
COPY dvt_extension_api /app/dvt_extension_api
COPY docs /app/docs
COPY config.py /app/config.py
COPY RELEASE /app/RELEASE
COPY pyproject.toml /app/pyproject.toml
COPY logging.yaml /app/logging.yaml

# Clear
RUN xargs pip uninstall -y < /app/docker/requirements.txt

FROM dvt_base_image AS buidler

COPY --from=base-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages

COPY --from=base-builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=base-builder /build /build
COPY --from=base-builder /app/contracts /app/contracts
COPY --from=base-builder /app/core /app/core
COPY --from=base-builder /app/src /app/src
COPY --from=base-builder /app/dvt_extension_api /app/dvt_extension_api
COPY --from=base-builder /app/docs /app/docs
COPY --from=base-builder /app/config.py /app/config.py
COPY --from=base-builder /app/RELEASE /app/RELEASE
COPY --from=base-builder /app/pyproject.toml /app/pyproject.toml
COPY --from=base-builder /app/logging.yaml /app/logging.yaml

WORKDIR /app
