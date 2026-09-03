from __future__ import annotations

import anyio

from ...domain.entities import PresignedUpload
from ..providers import FileStorageProvider


class GenerateUploadPresignUseCase:
    def __init__(
        self,
        provider: FileStorageProvider,
        *,
        expires_seconds: int,
        max_upload_size_bytes: int,
    ) -> None:
        self._provider = provider
        self._expires_seconds = expires_seconds
        self._max_upload_size_bytes = max_upload_size_bytes

    async def execute(
        self,
        *,
        path: str,
        filename: str,
        content_type_prefix: str,
    ) -> PresignedUpload:
        gateway = await self._provider.get_gateway()
        return await anyio.to_thread.run_sync(
            lambda: gateway.generate_upload_presign(
                path=path,
                filename=filename,
                content_type_prefix=content_type_prefix,
                expires_seconds=self._expires_seconds,
                max_upload_size_bytes=self._max_upload_size_bytes,
            )
        )
