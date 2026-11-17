"""Типизированный вид локатора таблицы БД поверх универсального DatasetLocator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ....catalog_values import DatasetLocator
from ....exceptions import UnknownSourceKindError
from ....graph import ConnectionLocator

DB_TABLE_KIND = "db_table"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _port(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class DbTableLocator:
    dialect: str
    host: str
    port: int | None
    database: str | None
    schema: str | None
    table: str

    @classmethod
    def from_locator(cls, locator: DatasetLocator) -> DbTableLocator:
        if locator.kind != DB_TABLE_KIND:
            raise UnknownSourceKindError(
                f"Locator of kind {locator.kind!r} is not a database table locator"
            )
        return cls(
            dialect=_text(locator.get("dialect")) or "",
            host=_text(locator.get("host")) or "",
            port=_port(locator.get("port")),
            database=_text(locator.get("database")),
            schema=_text(locator.get("schema")),
            table=_text(locator.get("table")) or "",
        )

    def to_locator(self) -> DatasetLocator:
        return DatasetLocator(
            kind=DB_TABLE_KIND,
            parts={
                "dialect": self.dialect,
                "host": self.host,
                "port": self.port,
                "database": self.database,
                "schema": self.schema,
                "table": self.table,
            },
        )


def db_table_locator(
    dialect: str,
    host: str,
    port: int | None,
    database: str | None,
    schema: str | None,
    table: str,
) -> DatasetLocator:
    """Фабрика универсального локатора таблицы БД (для фасадов и тестов)."""
    return DbTableLocator(
        dialect=dialect, host=host, port=port, database=database, schema=schema, table=table
    ).to_locator()


@dataclass(frozen=True, slots=True)
class DbConnectionCoordinates:
    """Несекретные координаты SQL-connection'а, нужные для нормализации локатора."""

    host: str
    port: int | None
    database: str | None


def db_connection_coordinates(connection: ConnectionLocator) -> DbConnectionCoordinates:
    """Хост, порт и база из свойств connection'а; именованный инстанс MSSQL без порта клеится к хосту."""
    properties = connection.properties
    host = _text(properties.get("host")) or ""
    port = _port(properties.get("port"))
    instance_name = _text(properties.get("instance_name"))
    if instance_name and port is None:
        host = f"{host}\\{instance_name}"
    return DbConnectionCoordinates(host=host, port=port, database=_text(properties.get("database")))
