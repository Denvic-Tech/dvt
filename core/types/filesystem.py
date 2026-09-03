from dataclasses import dataclass
from typing import Optional

import fsspec


@dataclass
class FsCtx:
    fs: fsspec.AbstractFileSystem
    protocol: str  # "s3", "ftp", "sftp" или "smb"
    path: str  # Полный URL (s3://..., ftp://..., sftp://... или smb://...)
    storage_options: dict
    # Дополнительные поля для восстановления URL после glob
    host: Optional[str] = None
    port: Optional[int] = None
    url_root: Optional[str] = None
