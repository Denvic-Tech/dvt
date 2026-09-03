from __future__ import annotations

import anyio

from ...domain.entities import DeleteResult
from ..providers import FileStorageProvider


class DeleteFolderUseCase:
    def __init__(self, provider: FileStorageProvider) -> None:
        self._provider = provider

    async def execute(self, *, path: str) -> DeleteResult:
        gateway = await self._provider.get_gateway()
        return await anyio.to_thread.run_sync(
            lambda: gateway.delete_folder(path=path)
        )
