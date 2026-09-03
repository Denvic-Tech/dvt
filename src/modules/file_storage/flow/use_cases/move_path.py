from __future__ import annotations

import anyio

from ..providers import FileStorageProvider


class MovePathUseCase:
    def __init__(self, provider: FileStorageProvider) -> None:
        self._provider = provider

    async def execute(self, *, path: str, target_path: str) -> None:
        gateway = await self._provider.get_gateway()
        await anyio.to_thread.run_sync(
            lambda: gateway.move_path(path=path, target_path=target_path)
        )
