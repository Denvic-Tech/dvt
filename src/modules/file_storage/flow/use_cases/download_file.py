from __future__ import annotations

import anyio

from ...domain.entities import DownloadedFile
from ..providers import FileStorageProvider


class DownloadFileUseCase:
    def __init__(self, provider: FileStorageProvider) -> None:
        self._provider = provider

    async def execute(self, *, path: str, filename: str) -> DownloadedFile:
        gateway = await self._provider.get_gateway()
        return await anyio.to_thread.run_sync(
            lambda: gateway.download_file(path=path, filename=filename)
        )
