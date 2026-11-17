"""Gateway connection to the enrolled manager and browser mutation guard."""

import os
import ssl
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

import config

from .client import (
    InstallationManagerClient,
    InstallationManagerHTTPError,
    InstallationManagerUnavailable,
)


def manager_origin() -> str | None:
    return os.getenv("DVT_OPERATOR_MANAGER_ORIGIN")


def require_browser_origin(request: Request) -> None:
    if (
        request.headers.get("origin") not in config.GATEWAY.GATEWAY_ORIGINS
        or request.headers.get("x-dvt-csrf") != "1"
        or request.headers.get("content-type", "").split(";", 1)[0] != "application/json"
    ):
        raise HTTPException(403, "Origin or CSRF check failed")


@lru_cache
def get_operator_manager() -> InstallationManagerClient | None:
    if not (origin := manager_origin()):
        return None
    directory = Path("/run/dvt-operator")
    token = (directory / "gateway-token").read_text(encoding="ascii").strip()
    ca = ssl.create_default_context(cafile=directory / "ca.pem")
    return InstallationManagerClient(
        base_url="https://installation_manager:8000",
        request_timeout_sec=max(config.INSTALLATION_MANAGER.REQUEST_TIMEOUT_SEC, 30),
        summary_timeout_sec=config.SYSTEM_STATE.STATUS_REQUEST_TIMEOUT_SEC,
        operator_journal=True,
        verify=ca, trust_env=False, headers={
            "Host": urlsplit(origin).netloc, "Authorization": f"Bearer {token}",
        },
        request_extensions={"sni_hostname": "localhost"},
    )


async def operator_request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    try:
        client = get_operator_manager()
    except (OSError, ValueError):
        client = None
    if client is None:
        raise HTTPException(503, "The protected update manager is not enrolled")
    try:
        return await client.request(method, path, **kwargs)
    except InstallationManagerUnavailable:
        raise HTTPException(503, "The protected manager is temporarily unreachable") from None
    except InstallationManagerHTTPError as error:
        raise HTTPException(error.status_code, error.detail) from None
