from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .data_type import DataType


class DTypeMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True, frozen=True)

    name: str = Field(..., description="Имя типа данных.")
    class_name: str = Field(..., alias="class", description="Класс типа данных.")
    origin: Literal["numpy", "pandas", "python"] = Field(..., description="Источник типа данных.")
    repr: str | None = Field(default=None, description="Строковое представление dtype.")
    module: str | None = Field(default=None, description="Полное имя Python-модуля класса dtype.")
    kind: str | None = Field(default=None, description="Низкоуровневый код kind для dtype.")
    itemsize: int | None = Field(default=None, description="Размер элемента dtype в байтах, если применимо.")
    is_extension: bool | None = Field(default=None, description="Является ли dtype pandas ExtensionDtype.")
    scalar_type: str | None = Field(default=None, description="Имя скалярного типа элементов dtype.")
    storage: str | None = Field(default=None, description="Бэкенд хранения dtype, если он задан.")
    unit: str | None = Field(default=None, description="Единица времени для datetime/timedelta dtype.")
    timezone: str | None = Field(default=None, description="Часовой пояс для timezone-aware datetime dtype.")
    ordered: bool | None = Field(default=None, description="Флаг упорядоченности категориального dtype.")
    categories_count: int | None = Field(default=None, description="Количество категорий для category dtype.")
    categories_dtype: str | None = Field(default=None, description="dtype значений категорий для category dtype.")


class Column(BaseModel):
    """Метаданные одной колонки DataFrame."""
    name: str = Field(..., description="Имя колонки в таблице.")
    dtype: DataType = Field(..., description="Тип данных колонки.")
    dtype_metadata: DTypeMetadata | None = Field(
        default=None,
        description="Метаданные типа данных колонки."
    )
    nullable: bool | None = Field(
        default=None,
        description="Флаг, указывающий, допускает ли колонка значения NULL."
    )
    index: bool | None = Field(
        default=None,
        description="Флаг, указывающий, участвует ли колонка в каком-либо индексе."
    )
