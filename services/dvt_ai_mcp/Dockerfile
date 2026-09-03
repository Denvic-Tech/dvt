FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY services/dvt_ai_mcp/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/dvt_ai_mcp /app/services/dvt_ai_mcp
COPY scripts/services/run_dvt_ai_mcp.py /app/scripts/services/run_dvt_ai_mcp.py
RUN touch /app/services/__init__.py /app/scripts/__init__.py /app/scripts/services/__init__.py \
    && useradd --create-home --uid 10001 dvt \
    && chown -R dvt:dvt /app

USER dvt

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"

CMD ["python", "-m", "scripts.services.run_dvt_ai_mcp"]
