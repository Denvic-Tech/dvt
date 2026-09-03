from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from src.modules.db_connection import ConnectionRecord


def _normalize_connection_type(value: object) -> str:
    return str(getattr(value, "value", value)).lower()


@dataclass(frozen=True, slots=True)
class ConnectionRecordWrapper:
    record: ConnectionRecord

    EXPECTED_KINDS: ClassVar[frozenset[str] | None] = None
    EXPECTED_TYPES: ClassVar[frozenset[str] | None] = None

    def __post_init__(self) -> None:
        expected_kinds = self.EXPECTED_KINDS
        expected_types = self.EXPECTED_TYPES
        record_kind = _normalize_connection_type(self.record.kind)
        record_type = _normalize_connection_type(self.record.type)

        if expected_kinds is not None and record_kind not in expected_kinds:
            raise TypeError(
                f"{self.__class__.__name__} expects connection kind in {sorted(expected_kinds)}, "
                f"got '{record_kind}'."
            )
        if expected_types is not None and record_type not in expected_types:
            raise TypeError(
                f"{self.__class__.__name__} expects connection type in {sorted(expected_types)}, "
                f"got '{record_type}'."
            )

    @property
    def id(self) -> str:
        return self.record.id

    @property
    def name(self) -> str:
        return self.record.name

    @property
    def kind(self) -> str:
        return _normalize_connection_type(self.record.kind)

    @property
    def type(self) -> str:
        return _normalize_connection_type(self.record.type)

    @property
    def driver(self) -> str | None:
        return self.record.driver

    @property
    def driver_options(self):
        return self.record.driver_options

    @property
    def properties(self) -> dict:
        return self.record.properties

    @property
    def secrets(self) -> dict:
        return self.record.secrets or {}


@dataclass(frozen=True, slots=True)
class SqlConnectionRecord(ConnectionRecordWrapper):
    EXPECTED_KINDS = frozenset({"sql"})


@dataclass(frozen=True, slots=True)
class FileConnectionRecord(ConnectionRecordWrapper):
    EXPECTED_KINDS = frozenset({"file"})
    EXPECTED_TYPES = frozenset({"s3", "ftp", "sftp", "smbprotocol", "dvt_service_files"})


@dataclass(frozen=True, slots=True)
class S3ConnectionRecord(FileConnectionRecord):
    EXPECTED_TYPES = frozenset({"s3"})


@dataclass(frozen=True, slots=True)
class FTPConnectionRecord(FileConnectionRecord):
    EXPECTED_TYPES = frozenset({"ftp", "sftp"})


@dataclass(frozen=True, slots=True)
class SMBConnectionRecord(FileConnectionRecord):
    EXPECTED_TYPES = frozenset({"smbprotocol"})


@dataclass(frozen=True, slots=True)
class KafkaConnectionRecord(ConnectionRecordWrapper):
    EXPECTED_KINDS = frozenset({"queue"})
    EXPECTED_TYPES = frozenset({"kafka"})
