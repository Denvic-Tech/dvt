from __future__ import annotations

import anyio

from ..providers import FileStorageProvider


class RenamePathUseCase:
    def __init__(self, provider: FileStorageProvider) -> None:
        self._provider = provider

    async def execute(self, *, path: str, new_name: str) -> None:
        gateway = await self._provider.get_gateway()
        await anyio.to_thread.run_sync(
            lambda: gateway.rename_path(path=path, new_name=new_name)
        )
