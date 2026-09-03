from __future__ import annotations

import anyio

from ..providers import FileStorageProvider


class CreateFolderUseCase:
    def __init__(self, provider: FileStorageProvider) -> None:
        self._provider = provider

    async def execute(self, *, path: str = "", folder_name: str) -> None:
        gateway = await self._provider.get_gateway()
        await anyio.to_thread.run_sync(
            lambda: gateway.create_folder(path=path, folder_name=folder_name)
        )
