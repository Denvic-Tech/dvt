from __future__ import annotations

import anyio

from ..providers import FileStorageProvider


class GenerateDownloadPresignUseCase:
    def __init__(self, provider: FileStorageProvider, *, expires_seconds: int) -> None:
        self._provider = provider
        self._expires_seconds = expires_seconds

    async def execute(self, *, path: str, filename: str) -> str:
        gateway = await self._provider.get_gateway()
        return await anyio.to_thread.run_sync(
            lambda: gateway.generate_download_presign(
                path=path,
                filename=filename,
                expires_seconds=self._expires_seconds,
            )
        )
