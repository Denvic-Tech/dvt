import asyncio
from typing import Any

import httpx

from src.logger import logger


class DenvicExtensionsDistributor:
    NAME = "DenvicExtensionsDistributor"

    def __init__(
        self,
        base_url: str,
        *,
        connect_timeout: float = 1.0,
        read_timeout: float = 5.0,
        write_timeout: float = 5.0,
        pool_timeout: float = 3.0,
        retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.retries = max(0, retries)
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=write_timeout,
            pool=pool_timeout,
        )
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if (
            self._client is None
            or self._loop is None
            or self._loop is not loop
            or getattr(self._client, "is_closed", False)
        ):
            if self._client is not None and self._loop is loop:
                try:
                    await self._client.aclose()
                except Exception:
                    logger.exception(f"{self.NAME}: error closing previous client")

            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            )
            self._loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None
                self._loop = None

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        client = await self._ensure_client()
        url = "/" + path.lstrip("/")

        backoff = 0.2
        for attempt in range(self.retries + 1):
            try:
                resp = await client.request(method.upper(), url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout) as exc:
                if attempt >= self.retries:
                    logger.error(f"{self.NAME}: connect/pool error {exc.__class__.__name__} for {self.base_url}{url}")
                    raise
                await asyncio.sleep(backoff)
                backoff *= 2
            except httpx.HTTPStatusError:
                logger.error(f"{self.NAME}: HTTP {resp.status_code} for {self.base_url}{url}")  # type: ignore[name-defined]
                raise
            except Exception:
                logger.exception(f"{self.NAME}: unexpected error during request to {self.base_url}{url}")
                raise

    async def list_extensions(
        self, *, dvt_version: str | None = None, dvt_channel: str | None = None
    ) -> dict:
        params = {}
        if dvt_version:
            params["dvt_version"] = dvt_version
        if dvt_channel:
            params["dvt_channel"] = dvt_channel
        response = await self._request("GET", "/extensions", params=params or None)
        return response.json()

    async def list_extension_versions(
        self, name: str, *, dvt_version: str | None = None, dvt_channel: str | None = None
    ) -> dict:
        params = {}
        if dvt_version:
            params["dvt_version"] = dvt_version
        if dvt_channel:
            params["dvt_channel"] = dvt_channel
        response = await self._request(
            "GET", f"/extensions/{name}/versions", params=params or None
        )
        return response.json()

    async def download_extension_version(
        self, name: str, version: str, *, dvt_channel: str | None = None
    ) -> bytes:
        params = {"dvt_channel": dvt_channel} if dvt_channel else None
        response = await self._request(
            "GET", f"/extensions/{name}/versions/{version}/download", params=params
        )
        return response.content

    async def download_extension_archive(
        self, project_path: str, *, ref: str | None = None
    ) -> bytes:
        params = {"ref": ref} if ref else None
        response = await self._request(
            "GET", f"/extensions/{project_path}/archive", params=params
        )
        return response.content
