from __future__ import annotations

import anyio

from ..exceptions import FileTooLargeError
from ..providers import FileStorageProvider


class UploadFileUseCase:
    def __init__(self, provider: FileStorageProvider, *, max_upload_size_bytes: int) -> None:
        self._provider = provider
        self._max_upload_size_bytes = max_upload_size_bytes

    async def execute(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        if len(content) > self._max_upload_size_bytes:
            raise FileTooLargeError(max_size_bytes=self._max_upload_size_bytes)

        gateway = await self._provider.get_gateway()
        await anyio.to_thread.run_sync(
            lambda: gateway.upload_file(
                path=path,
                filename=filename,
                content=content,
                content_type=content_type,
            )
        )
