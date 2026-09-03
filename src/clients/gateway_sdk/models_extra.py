from __future__ import annotations

from io import BufferedReader, BytesIO
from pathlib import Path
from typing import BinaryIO, TypeAlias

from pydantic import BaseModel, ConfigDict


class BinaryPayload(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    content: bytes
    content_type: str | None = None
    filename: str | None = None
    headers: dict[str, str]


class SignInResult(BaseModel):
    success: bool
    message: str | None = None
    access_token: str | None = None
    payload: dict | list | None = None


FileUpload: TypeAlias = (
    bytes
    | bytearray
    | memoryview
    | str
    | Path
    | BinaryIO
    | tuple[str, bytes]
    | tuple[str, bytes, str]
)


def open_file_upload(upload: FileUpload) -> tuple[str, bytes, str | None]:
    if isinstance(upload, tuple):
        if len(upload) == 2:
            filename, content = upload
            return filename, content, None
        filename, content, content_type = upload
        return filename, content, content_type

    if isinstance(upload, (bytes, bytearray, memoryview)):
        return "upload.bin", bytes(upload), None

    if isinstance(upload, (str, Path)):
        path = Path(upload)
        return path.name, path.read_bytes(), None

    if isinstance(upload, (BufferedReader, BytesIO)):
        filename = Path(getattr(upload, "name", "upload.bin")).name
        return filename, upload.read(), None

    filename = Path(getattr(upload, "name", "upload.bin")).name
    return filename, upload.read(), None
