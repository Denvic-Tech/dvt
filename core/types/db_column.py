from pydantic import Field

from core.types import Column


class DBColumn(Column):
    """
    Модель, представляющая метаданные колонки таблицы БД.
    """
    # Можно добавить другие поля, например:
    # is_nullable: bool = Field(..., description="Указывает, может ли колонка содержать NULL значения.")
    # default_value: Optional[str] = Field(None, description="Значение по умолчанию для колонки, если установлено.")
    # character_maximum_length: Optional[int] = Field(None, description="Максимальная длина символов для строковых типов.")
    # numeric_precision: Optional[int] = Field(None, description="Точность для числовых типов.")

    indexes: list[str] | None = Field(
        default=None,
        description="Список индексов, в которых участвует колонка (с указанием типа индекса)."
    )
    primary_key: bool | None = Field(
        default=None,
        description="Флаг, указывающий, является ли колонка частью PRIMARY KEY."
    )
