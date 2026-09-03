from __future__ import annotations

import contextlib
from dataclasses import dataclass

from db_connection import InfrastructureError

try:
    import smbclient
except ImportError:  # pragma: no cover
    smbclient = None


@dataclass(slots=True)
class SMBProtocolClient:
    host: str
    share: str
    username: str
    password: str
    port: int = 445
    connection_timeout: int = 30

    @property
    def root_path(self) -> str:
        return f"\\\\{self.host}\\{self.share}"

    def build_unc_path(self, path: str | None = None, filename: str | None = None) -> str:
        segments = [self._normalize_segment(path), self._normalize_segment(filename)]
        suffix = "\\".join(segment for segment in segments if segment)
        return self.root_path if not suffix else f"{self.root_path}\\{suffix}"

    def ensure_session(self) -> None:
        self._require_smbclient()
        smbclient.register_session(
            self.host,
            username=self.username,
            password=self.password,
            port=self.port,
            connection_timeout=self.connection_timeout,
        )

    def close(self) -> None:
        if smbclient is None:
            return
        with contextlib.suppress(Exception):
            smbclient.delete_session(self.host, port=self.port, timeout=self.connection_timeout)

    def listdir(self, path: str | None = None) -> list[str]:
        self.ensure_session()
        return smbclient.listdir(self.build_unc_path(path=path), port=self.port)

    def scandir(self, path: str | None = None):
        self.ensure_session()
        return smbclient.scandir(self.build_unc_path(path=path), port=self.port)

    def open_file(self, path: str | None = None, filename: str | None = None, *args, **kwargs):
        self.ensure_session()
        return smbclient.open_file(
            self.build_unc_path(path=path, filename=filename),
            *args,
            port=self.port,
            **kwargs,
        )

    def stat(self, path: str | None = None, filename: str | None = None):
        self.ensure_session()
        return smbclient.stat(self.build_unc_path(path=path, filename=filename), port=self.port)

    def mkdir(self, path: str | None = None, filename: str | None = None, *args, **kwargs) -> None:
        self.ensure_session()
        smbclient.mkdir(
            self.build_unc_path(path=path, filename=filename),
            *args,
            port=self.port,
            **kwargs,
        )

    def remove(self, path: str | None = None, filename: str | None = None, *args, **kwargs) -> None:
        self.ensure_session()
        smbclient.remove(
            self.build_unc_path(path=path, filename=filename),
            *args,
            port=self.port,
            **kwargs,
        )

    def rmdir(self, path: str | None = None, filename: str | None = None, *args, **kwargs) -> None:
        self.ensure_session()
        smbclient.rmdir(
            self.build_unc_path(path=path, filename=filename),
            *args,
            port=self.port,
            **kwargs,
        )

    def rename(
        self,
        src_path: str | None = None,
        src_filename: str | None = None,
        dst_path: str | None = None,
        dst_filename: str | None = None,
        *args,
        **kwargs,
    ) -> None:
        self.ensure_session()
        smbclient.rename(
            self.build_unc_path(path=src_path, filename=src_filename),
            self.build_unc_path(path=dst_path, filename=dst_filename),
            *args,
            port=self.port,
            **kwargs,
        )

    def replace(
        self,
        src_path: str | None = None,
        src_filename: str | None = None,
        dst_path: str | None = None,
        dst_filename: str | None = None,
        *args,
        **kwargs,
    ) -> None:
        self.ensure_session()
        smbclient.replace(
            self.build_unc_path(path=src_path, filename=src_filename),
            self.build_unc_path(path=dst_path, filename=dst_filename),
            *args,
            port=self.port,
            **kwargs,
        )

    def _normalize_segment(self, value: str | None) -> str:
        if value is None:
            return ""
        return value.strip("\\/ ").replace("/", "\\")

    def _require_smbclient(self) -> None:
        if smbclient is None:
            raise InfrastructureError("SMB support requires the 'smbprotocol' package.")
