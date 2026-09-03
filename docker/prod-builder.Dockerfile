# syntax=docker/dockerfile:1.7

# Public production builder: DVT ships and runs as ordinary Python source.
FROM dvt_base_image AS prod-builder

WORKDIR /app

COPY docker/requirements.txt /app/docker/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache-py3.13 \
    python -m pip install -r /app/docker/requirements.txt

# Generate and install local gRPC contracts used by runtime services.
COPY contracts/pyproject.toml /app/contracts/pyproject.toml
COPY contracts/protos /app/contracts/protos
RUN mkdir -p /app/contracts/src && \
    python -m grpc_tools.protoc \
      -I /app/contracts/protos \
      --python_out /app/contracts/src \
      --grpc_python_out /app/contracts/src \
      $(find /app/contracts/protos -name "*.proto") && \
    pip install -e /app/contracts --force-reinstall

COPY core /app/core
COPY src /app/src
COPY dvt_extension_api /app/dvt_extension_api
COPY config.py /app/config.py
COPY RELEASE /app/RELEASE
COPY pyproject.toml /app/pyproject.toml
COPY logging.yaml /app/logging.yaml

RUN xargs pip uninstall -y < /app/docker/requirements.txt
