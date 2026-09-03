from __future__ import annotations

import anyio

from ...domain.entities import StorageTree
from ..providers import FileStorageProvider


class ListNodesUseCase:
    def __init__(self, provider: FileStorageProvider) -> None:
        self._provider = provider

    async def execute(self, *, path: str = "", max_items: int = 1000) -> StorageTree:
        gateway = await self._provider.get_gateway()
        return await anyio.to_thread.run_sync(
            lambda: gateway.list_nodes(path=path, max_items=max_items)
        )
