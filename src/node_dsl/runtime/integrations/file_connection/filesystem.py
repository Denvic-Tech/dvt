from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import fsspec

from core.types import FsCtx

from .errors import build_file_connection_error_translator

_GLOB_CHARS = frozenset({"*", "?", "[", "]"})


class FileConnectionRuntime:
    """Общие fsspec-операции для нод, использующих файловые подключения."""

    def __init__(self, ctx: FsCtx) -> None:
        self._ctx = ctx
        self._error_translator = build_file_connection_error_translator(ctx)
        self._ensure_filesystem()

    @property
    def context(self) -> FsCtx:
        return self._ctx

    def _ensure_filesystem(self) -> None:
        if self._ctx.fs is not None:
            return

        try:
            self._ctx.fs = fsspec.filesystem(
                self._ctx.protocol,
                **self._ctx.storage_options,
            )
        except Exception as exc:  # noqa: BLE001
            translated = self._translate_error(
                exc,
                operation="initializing file connection",
                path=self._ctx.path,
            )
            if translated is exc:
                raise
            raise translated from exc

    def strip_protocol_path(self, path: str | None = None) -> str:
        target_path = path or self._ctx.path
        strip_protocol = getattr(self._ctx.fs, "_strip_protocol", None)
        if callable(strip_protocol):
            return strip_protocol(target_path)
        return target_path

    def restore_url(self, path: str) -> str:
        if "://" in path:
            return path

        path = path.lstrip("/")
        if self._ctx.url_root:
            separator = "" if self._ctx.url_root.endswith("/") else "/"
            return f"{self._ctx.url_root}{separator}{path}"

        return f"{self._ctx.protocol}://{path}"

    def has_glob(self, path: str | None = None) -> bool:
        raw_path = self.strip_protocol_path(path)
        return any(char in raw_path for char in _GLOB_CHARS)

    @contextmanager
    def operation(
        self,
        operation: str,
        *,
        path: str | None = None,
    ) -> Iterator[None]:
        target_path = path or self._ctx.path
        try:
            yield
        except Exception as exc:  # noqa: BLE001
            translated = self._translate_error(
                exc,
                operation=operation,
                path=target_path,
            )
            if translated is exc:
                raise
            raise translated from exc

    def list_files(
        self,
        *,
        required: bool = False,
        subject: str = "File(s)",
        operation: str = "listing files",
    ) -> list[str]:
        raw_path = self.strip_protocol_path()
        with self.operation(operation):
            if self.has_glob():
                files = [
                    self.restore_url(path)
                    for path in sorted(self._ctx.fs.glob(raw_path))
                ]
            else:
                try:
                    self._ctx.fs.info(raw_path)
                except FileNotFoundError:
                    files = []
                else:
                    files = [self._ctx.path]

        if required and not files:
            self.raise_missing(operation=operation, subject=subject)
        return files

    def raise_missing(
        self,
        *,
        operation: str,
        subject: str = "File(s)",
        path: str | None = None,
    ) -> None:
        target_path = path or self._ctx.path
        if self._error_translator is not None:
            raise self._error_translator.missing(
                operation=operation,
                path=target_path,
                subject=subject,
            )
        raise FileNotFoundError(f"{subject} not found by path: {target_path}")

    def _translate_error(
        self,
        exc: BaseException,
        *,
        operation: str,
        path: str,
    ) -> BaseException:
        if self._error_translator is None:
            return exc
        return self._error_translator.translate(
            exc,
            operation=operation,
            path=path,
        )
