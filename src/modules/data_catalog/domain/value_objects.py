from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .exceptions import InvalidColumnSchemaError, InvalidTableSchemaError


def _raise_invalid_column(message: str) -> None:
    raise InvalidColumnSchemaError(message)


@dataclass(frozen=True, slots=True)
class ColumnSchema:
    name: str
    dtype: str | None = None
    description: str | None = None
    nullable: bool | None = None
    default: Any = None
    order: int | None = None
    primary_key: bool | None = None
    unique: bool | None = None
    precision: int | None = None
    scale: int | None = None
    length: int | None = None
    format: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            _raise_invalid_column("Column name must be a non-empty string.")
        object.__setattr__(self, "name", self.name.strip())

        for field_name in ("dtype", "description", "format"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, str):
                _raise_invalid_column(f"Column field '{field_name}' must be a string or null.")
            if isinstance(value, str):
                normalized = value.strip()
                object.__setattr__(self, field_name, normalized or None)

        for field_name in ("nullable", "primary_key", "unique"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, bool):
                _raise_invalid_column(f"Column field '{field_name}' must be a boolean or null.")

        for field_name in ("order", "precision", "scale", "length"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                _raise_invalid_column(f"Column field '{field_name}' must be an integer or null.")
            if value < 0:
                _raise_invalid_column(f"Column field '{field_name}' must be non-negative.")

        if self.precision is not None and self.scale is not None and self.scale > self.precision:
            _raise_invalid_column("Column scale cannot be greater than precision.")

        if not isinstance(self.metadata, dict):
            _raise_invalid_column("Column metadata must be a dictionary.")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class TableSchema:
    columns: tuple[ColumnSchema, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.columns, tuple):
            raise InvalidTableSchemaError("Table schema columns must be a tuple.")
        if any(not isinstance(column, ColumnSchema) for column in self.columns):
            raise InvalidTableSchemaError("Table schema contains an invalid column value.")

        names = [column.name for column in self.columns]
        duplicate_names = sorted({name for name in names if names.count(name) > 1})
        if duplicate_names:
            raise InvalidTableSchemaError(
                f"Table schema contains duplicate column names: {duplicate_names!r}."
            )
