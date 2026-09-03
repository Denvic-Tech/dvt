from __future__ import annotations

from typing import Protocol

from core.types import FsCtx


class FileConnectionErrorTranslator(Protocol):
    """Backend-specific file-connection error translation contract."""

    def translate(
        self,
        exc: BaseException,
        *,
        operation: str,
        path: str,
    ) -> BaseException:
        ...

    def missing(
        self,
        *,
        operation: str,
        path: str,
        subject: str,
    ) -> BaseException:
        ...


def build_file_connection_error_translator(
    ctx: FsCtx,
) -> FileConnectionErrorTranslator | None:
    """Resolve a protocol-specific error translator without loading unused backends."""
    if ctx.protocol == "s3":
        from .s3.errors import S3FileConnectionErrorTranslator

        return S3FileConnectionErrorTranslator(ctx)
    return None
