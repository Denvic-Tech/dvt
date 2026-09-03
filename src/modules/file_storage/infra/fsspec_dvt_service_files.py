from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

import fsspec
from fsspec.spec import AbstractFileSystem

from src.db import engine
from src.modules.db_connection.infra.connectors.dvt_service_files.client import (
    DVTServiceFilesClient,
)


class DVTServiceFilesFileSystem(AbstractFileSystem):
    protocol = "dvtfiles"

    def __init__(
        self,
        *,
        organization_id: str,
        project_id: str,
        root_prefix: str = "",
        **storage_options: Any,
    ) -> None:
        super().__init__(**storage_options)
        self._client = DVTServiceFilesClient(
            engine=engine,
            organization_id=organization_id,
            project_id=project_id,
            root_prefix=root_prefix,
        )

    @classmethod
    def _strip_protocol(cls, path: str) -> str:
        if "://" in path:
            path = path.split("://", 1)[1]
            if "/" in path:
                path = path.split("/", 1)[1]
            else:
                path = ""
        return path.strip("/")

    def _open(
        self,
        path: str,
        mode: str = "rb",
        block_size: int | None = None,
        autocommit: bool = True,
        cache_options: dict | None = None,
        **kwargs: Any,
    ):
        context = self._client.open_file(path=self._strip_protocol(path), mode=mode)
        handle = context.__enter__()
        handle._dvt_open_context = context
        return handle

    def exists(self, path: str, **kwargs: Any) -> bool:
        return self._client.exists(self._strip_protocol(path))

    def info(self, path: str, **kwargs: Any) -> dict[str, Any]:
        stripped = self._strip_protocol(path)
        entry = self._client.info(stripped)
        return {
            "name": stripped,
            "size": entry.size,
            "type": "directory" if entry.is_dir else "file",
            "created": None,
            "mtime": _timestamp(entry.updated_at),
            "content_type": entry.content_type,
            "sha256": entry.sha256,
        }

    def ls(self, path: str, detail: bool = True, **kwargs: Any):
        stripped = self._strip_protocol(path)
        entries = self._client.list_entries(stripped)
        payload = [
            {
                "name": entry.path,
                "size": entry.size,
                "type": "directory" if entry.is_dir else "file",
                "mtime": _timestamp(entry.updated_at),
                "content_type": entry.content_type,
                "sha256": entry.sha256,
            }
            for entry in entries
        ]
        if detail:
            return payload
        return [item["name"] for item in payload]

    def mkdir(self, path: str, create_parents: bool = True, **kwargs: Any) -> None:
        self._client.mkdir(self._strip_protocol(path))

    def rm_file(self, path: str, **kwargs: Any) -> None:
        self._client.remove(self._strip_protocol(path))


def _timestamp(value: datetime | None) -> float | None:
    if value is None:
        return None
    return value.timestamp()


@lru_cache(maxsize=1)
def register_dvt_service_files_filesystem() -> None:
    try:
        fsspec.register_implementation(
            DVTServiceFilesFileSystem.protocol,
            DVTServiceFilesFileSystem,
            clobber=False,
        )
    except ValueError:
        return
