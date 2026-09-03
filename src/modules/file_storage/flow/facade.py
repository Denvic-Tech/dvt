from __future__ import annotations

from ..domain.entities import DeleteResult, DownloadedFile, PresignedUpload, StorageTree
from .providers import FileStorageProvider
from .use_cases import (
    CreateFolderUseCase,
    DeleteFilesUseCase,
    DeleteFolderUseCase,
    DownloadFileUseCase,
    GenerateDownloadPresignUseCase,
    GenerateUploadPresignUseCase,
    ListNodesUseCase,
    MovePathUseCase,
    RenamePathUseCase,
    UploadFileUseCase,
)


class FileStorageFacade:
    def __init__(
        self,
        provider: FileStorageProvider,
        *,
        presign_expire_seconds: int,
        max_upload_size_bytes: int,
    ) -> None:
        self._list_nodes = ListNodesUseCase(provider)
        self._create_folder = CreateFolderUseCase(provider)
        self._rename_path = RenamePathUseCase(provider)
        self._move_path = MovePathUseCase(provider)
        self._delete_files = DeleteFilesUseCase(provider)
        self._delete_folder = DeleteFolderUseCase(provider)
        self._generate_upload_presign = GenerateUploadPresignUseCase(
            provider,
            expires_seconds=presign_expire_seconds,
            max_upload_size_bytes=max_upload_size_bytes,
        )
        self._generate_download_presign = GenerateDownloadPresignUseCase(
            provider,
            expires_seconds=presign_expire_seconds,
        )
        self._upload_file = UploadFileUseCase(
            provider,
            max_upload_size_bytes=max_upload_size_bytes,
        )
        self._download_file = DownloadFileUseCase(provider)

    async def list_nodes(self, *, path: str = "", max_items: int = 1000) -> StorageTree:
        return await self._list_nodes.execute(
            path=path,
            max_items=max_items,
        )

    async def create_folder(self, *, path: str = "", folder_name: str) -> None:
        await self._create_folder.execute(
            path=path,
            folder_name=folder_name,
        )

    async def rename_path(self, *, path: str, new_name: str) -> None:
        await self._rename_path.execute(
            path=path,
            new_name=new_name,
        )

    async def move_path(self, *, path: str, target_path: str) -> None:
        await self._move_path.execute(
            path=path,
            target_path=target_path,
        )

    async def delete_files(self, *, paths: list[str]) -> DeleteResult:
        return await self._delete_files.execute(
            paths=paths,
        )

    async def delete_folder(self, *, path: str) -> DeleteResult:
        return await self._delete_folder.execute(
            path=path,
        )

    async def generate_upload_presign(
        self,
        *,
        path: str,
        filename: str,
        content_type_prefix: str,
    ) -> PresignedUpload:
        return await self._generate_upload_presign.execute(
            path=path,
            filename=filename,
            content_type_prefix=content_type_prefix,
        )

    async def generate_download_presign(self, *, path: str, filename: str) -> str:
        return await self._generate_download_presign.execute(
            path=path,
            filename=filename,
        )

    async def upload_file(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        await self._upload_file.execute(
            path=path,
            filename=filename,
            content=content,
            content_type=content_type,
        )

    async def download_file(self, *, path: str, filename: str) -> DownloadedFile:
        return await self._download_file.execute(
            path=path,
            filename=filename,
        )
