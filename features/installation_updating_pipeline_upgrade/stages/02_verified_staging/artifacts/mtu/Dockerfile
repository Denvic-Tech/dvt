FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90
RUN apt-get update && apt-get install --no-install-recommends -y curl openssl && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/testing && /opt/testing/bin/python -m pip install --disable-pip-version-check --no-cache-dir pydantic==2.11.5 cryptography==50.0.1 packaging==25.0 PyYAML==6.0.3
WORKDIR /case
ENV PYTHONPATH=/case PYTHONDONTWRITEBYTECODE=1
COPY core /case/core
COPY services /case/services
COPY mtu_probe.py /case/mtu_probe.py
CMD ["/opt/testing/bin/python", "/case/mtu_probe.py"]
