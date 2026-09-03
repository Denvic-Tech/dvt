from typing import List, Any, TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from core.types import Column


class DataFrameData(BaseModel):
    """Данные DataFrame с метаданными (для передачи части данных)."""
    columns: List["Column"] = Field(..., description="Колонки DataFrame")
    values: List[List[Any]] = Field(..., description="Данные DataFrame как список списков")

    total_rows: int = Field(..., description="Количество строк в DataFrame")
    total_partitions: int = Field(..., description="Количество партиций в DataFrame")
