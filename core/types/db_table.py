from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from core.types import DBColumn

DBDialect = Literal[
    "postgresql", "mysql", "mariadb", "mongodb", "mssql", "sqlserver", "clickhouse", "sqlite", "oracle"
] | str


class DBTableType(StrEnum):
    """
    Перечисление типов таблиц в базе данных.
    """
    BASE_TABLE = "BASE_TABLE"
    VIEW = "VIEW"
    TEMPORARY = "TEMPORARY"
    SYSTEM = "SYSTEM"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_string(cls, value: str) -> 'DBTableType':
        """
        Преобразует строковое представление типа таблицы в DBTableType.
        """
        value = value.strip().upper().replace(" ", "_")
        for member in cls:
            if member.value == value:
                return member
        return cls.UNKNOWN


class DBTable(BaseModel):
    """
    Модель, представляющая метаданные таблицы БД.
    """
    id: str = Field(default_factory=lambda: str(uuid4()), description="Уникальный идентификатор таблицы.")
    schema_name: str | None = Field(None,
                                       description="Схема, которой принадлежит таблица (если применимо).")
    database_name: str | None = Field(None,
                                         description="Имя базы данных, к которой принадлежит таблица (если применимо).")
    name: str = Field(..., description="Имя таблицы в базе данных.")
    columns: list[DBColumn] = Field(..., description="Список колонок в таблице.")
    type: DBTableType = Field(..., description="Тип таблицы (например, BASE TABLE, VIEW).")


class DBSchema(BaseModel):
    """
    Модель, представляющая метаданные схемы БД.
    """
    name: str = Field(..., description="Имя схемы.")
    database_name: str | None = Field(
        None,
        description="Имя базы данных, к которой относится схема (если применимо).",
    )
    tables: list[DBTable] = Field(
        default_factory=list,
        description="Список таблиц и представлений в схеме.",
    )


class DBDatabase(BaseModel):
    """
    Модель, представляющая метаданные базы данных.
    """
    name: str = Field(..., description="Имя базы данных.")
    schemas: list[DBSchema] = Field(
        default_factory=list,
        description="Схемы базы данных.",
    )
    tables: list[DBTable] = Field(
        default_factory=list,
        description="Таблицы базы данных для диалектов без слоя схем.",
    )
