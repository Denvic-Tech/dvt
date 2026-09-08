from __future__ import annotations

from enum import StrEnum

from typing import Union


class IO(StrEnum):
    """Node input/output data types."""

    STRING = "STRING"
    BOOLEAN = "BOOLEAN"
    INT = "INT"
    FLOAT = "FLOAT"
    DICT = "DICT"  # Для внутренних параметров в NodeData
    JSON = "JSON"  # Для самих данных (текут через соединения)
    DATAFRAME = "DATAFRAME"
    TABLE_SCHEMA = "TABLE_SCHEMA"
    COLUMN = "COLUMN"
    COLUMN_NAME = "COLUMN_NAME"
    DB_CONNECTION = "DB_CONNECTION"
    DB_CONNECTION_ID = "DB_CONNECTION_ID"
    FILE_CONNECTION = "S3_CONNECTION,FTP_CONNECTION,SMB_CONNECTION"
    S3_CONNECTION = "S3_CONNECTION"
    S3_CONNECTION_ID = "S3_CONNECTION_ID"
    FTP_CONNECTION = "FTP_CONNECTION"
    FTP_CONNECTION_ID = "FTP_CONNECTION_ID"
    SMB_CONNECTION = "SMB_CONNECTION"
    SMB_CONNECTION_ID = "SMB_CONNECTION_ID"
    KAFKA_CONNECTION = "KAFKA_CONNECTION"
    KAFKA_CONNECTION_ID = "KAFKA_CONNECTION_ID"
    DATETIME = "DATETIME"
    TIMEDELTA = "TIMEDELTA"
    OBJECT = "OBJECT"  # Для неизвестных или смешанных типов
    UNKNOWN = "UNKNOWN"  # Если тип совсем не удалось определить
    SCHEMA = "SCHEMA"  # Для схемы данных, например, JSON Schema или Pydantic Model
    VARIABLE = "VARIABLE"
    SIGNAL = "SIGNAL"

    ANY = "*"
    """Always matches any type, but can cause issues. Avoid if possible."""

    NUMBER = "FLOAT,INT"
    """A float or an int."""

    PRIMITIVE = "PRIMITIVE"
    """Any of: string, float, int, or bool."""

    def __ne__(self, value: object) -> bool:
        return not self.__eq__(value)

    def is_subset(self, other: Union[IO, str]) -> bool:
        if str(self) == "*" or str(other) == "*": return True
        if not isinstance(other, str): return False
        return frozenset(str(self).split(",")).issubset(frozenset(str(other).split(",")))

    def intersects(self, other: Union[IO, str]) -> bool:
        if str(self) == "*" or str(other) == "*": return True
        if not isinstance(other, str): return False
        return not frozenset(str(self).split(",")).isdisjoint(frozenset(str(other).split(",")))

    def __hash__(self):
        return hash(self.value)


def try_get_io_member(value: object) -> IO | None:
    if isinstance(value, IO):
        return value
    if not isinstance(value, str):
        return None
    member = IO.__members__.get(value)
    if member is not None:
        return member
    try:
        return IO(value)
    except ValueError:
        return None


def matches_exact_io(value: object, expected: IO) -> bool:
    return try_get_io_member(value) is expected


def contains_exact_io(value: object, expected: IO) -> bool:
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(matches_exact_io(item, expected) for item in value)
    return matches_exact_io(value, expected)
