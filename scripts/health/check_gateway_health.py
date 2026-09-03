"""Health-check helper for the Gateway service.

This script is meant to be executed inside the gateway container by Docker's
healthcheck. It issues a GET request against the FastAPI ``/health`` endpoint
and exits with code 0 only when the service responds with HTTP 200.

Environment variables:
    GATEWAY_HEALTHCHECK_URL: Optional absolute URL overriding the request URL.
    GATEWAY_HEALTHCHECK_HOST: Hostname for the health endpoint (default ``localhost``).
    GATEWAY_PORT: Gateway port (default ``8000``).
    GATEWAY_HEALTHCHECK_TIMEOUT: Request timeout in seconds (default ``5``).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _build_url() -> str:
    override = os.environ.get("GATEWAY_HEALTHCHECK_URL")
    if override:
        return override

    host = os.environ.get("GATEWAY_HEALTHCHECK_HOST", "localhost").strip() or "localhost"
    port = os.environ.get("GATEWAY_PORT", "8000").strip() or "8000"
    return f"http://{host}:{port}/health"


def _read_timeout() -> float:
    raw_timeout = os.environ.get("GATEWAY_HEALTHCHECK_TIMEOUT", "5")
    try:
        return max(0.5, float(raw_timeout))
    except ValueError:
        return 5.0


def main() -> int:
    url = _build_url()
    timeout = _read_timeout()

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                print(f"Gateway health endpoint returned status {response.status}", file=sys.stderr)
                return 1

            payload = response.read().decode("utf-8", errors="ignore").strip()
    except urllib.error.URLError as exc:  # Includes timeouts and HTTP errors.
        print(f"Gateway health endpoint is unreachable: {exc}", file=sys.stderr)
        return 1

    if not payload:
        return 0

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return 0

    status = data if isinstance(data, str) else data.get("status") if isinstance(data, dict) else None
    if isinstance(status, str) and status.lower() not in {"ok", "healthy", "pass"}:
        print(f"Gateway health endpoint returned unexpected status payload: {status}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
