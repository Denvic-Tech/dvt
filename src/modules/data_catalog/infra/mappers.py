from __future__ import annotations

import math
import numbers
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, NoReturn
from uuid import UUID

import dask.dataframe as dd
import numpy as np
import pandas as pd

from ..domain import ColumnSchema
from .exceptions import DataFrameSchemaMappingError


@dataclass(frozen=True, slots=True)
class DataFrameSchemaMapping:
    column_names: str
    column_dtypes: str | None = None
    column_descriptions: str | None = None
    column_nullable: str | None = None
    column_defaults: str | None = None
    column_order: str | None = None
    column_primary_key: str | None = None
    column_unique: str | None = None
    column_precision: str | None = None
    column_scale: str | None = None
    column_length: str | None = None
    column_format: str | None = None
    metadata_columns: tuple[str, ...] = ()

    def selected_columns(self) -> tuple[str, ...]:
        configured = (
            self.column_names,
            self.column_dtypes,
            self.column_descriptions,
            self.column_nullable,
            self.column_defaults,
            self.column_order,
            self.column_primary_key,
            self.column_unique,
            self.column_precision,
            self.column_scale,
            self.column_length,
            self.column_format,
            *self.metadata_columns,
        )
        return tuple(dict.fromkeys(value for value in configured if value is not None))


class DataFrameSchemaMapper:
    def to_columns(
        self,
        *,
        dataframe: dd.DataFrame,
        mapping: DataFrameSchemaMapping,
    ) -> tuple[ColumnSchema, ...]:
        self._validate_mapping(dataframe=dataframe, mapping=mapping)
        selected_columns = mapping.selected_columns()
        frame = dataframe.loc[:, list(selected_columns)].compute()

        columns: list[ColumnSchema] = []
        for row_number, row in enumerate(frame.to_dict(orient="records"), start=1):
            columns.append(self._map_row(row=row, row_number=row_number, mapping=mapping))
        return tuple(columns)

    @staticmethod
    def _validate_mapping(*, dataframe: dd.DataFrame, mapping: DataFrameSchemaMapping) -> None:
        if not isinstance(mapping.column_names, str) or not mapping.column_names:
            raise DataFrameSchemaMappingError("column_names must reference an input column.")
        if len(set(mapping.metadata_columns)) != len(mapping.metadata_columns):
            raise DataFrameSchemaMappingError("metadata_columns must not contain duplicates.")

        dataframe_columns = list(dataframe.columns)
        missing = [name for name in mapping.selected_columns() if name not in dataframe_columns]
        if missing:
            raise DataFrameSchemaMappingError(
                f"Configured schema source columns are missing from DataFrame: {missing!r}."
            )
        ambiguous = [
            name for name in mapping.selected_columns() if dataframe_columns.count(name) > 1
        ]
        if ambiguous:
            raise DataFrameSchemaMappingError(
                f"Configured schema source columns are duplicated in DataFrame: {ambiguous!r}."
            )

    def _map_row(
        self,
        *,
        row: dict[str, Any],
        row_number: int,
        mapping: DataFrameSchemaMapping,
    ) -> ColumnSchema:
        name = self._required_string(
            row[mapping.column_names], field_name="name", row_number=row_number
        )
        return ColumnSchema(
            name=name,
            dtype=self._optional_string(row, mapping.column_dtypes, "dtype", row_number),
            description=self._optional_string(
                row, mapping.column_descriptions, "description", row_number
            ),
            nullable=self._optional_bool(row, mapping.column_nullable, "nullable", row_number),
            default=self._optional_value(row, mapping.column_defaults, row_number),
            order=self._optional_int(
                row,
                mapping.column_order,
                "order",
                row_number,
                required=mapping.column_order is not None,
            ),
            primary_key=self._optional_bool(
                row, mapping.column_primary_key, "primary_key", row_number
            ),
            unique=self._optional_bool(row, mapping.column_unique, "unique", row_number),
            precision=self._optional_int(row, mapping.column_precision, "precision", row_number),
            scale=self._optional_int(row, mapping.column_scale, "scale", row_number),
            length=self._optional_int(row, mapping.column_length, "length", row_number),
            format=self._optional_string(row, mapping.column_format, "format", row_number),
            metadata={
                column_name: self._normalize_value(row[column_name], row_number=row_number)
                for column_name in mapping.metadata_columns
            },
        )

    def _optional_string(
        self,
        row: dict[str, Any],
        source_column: str | None,
        field_name: str,
        row_number: int,
    ) -> str | None:
        if source_column is None:
            return None
        value = row[source_column]
        if self._is_missing(value):
            return None
        if not isinstance(value, str):
            self._raise_value_error(row_number, field_name, "must be a string or null")
        normalized = value.strip()
        return normalized or None

    def _optional_bool(
        self,
        row: dict[str, Any],
        source_column: str | None,
        field_name: str,
        row_number: int,
    ) -> bool | None:
        if source_column is None:
            return None
        value = row[source_column]
        if self._is_missing(value):
            return None
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
        if isinstance(value, numbers.Real) and not isinstance(value, bool) and value in (0, 1):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "false"}:
                return normalized == "true"
        return self._raise_value_error(
            row_number, field_name, "must be bool, 0/1, true/false, or null"
        )

    def _optional_int(
        self,
        row: dict[str, Any],
        source_column: str | None,
        field_name: str,
        row_number: int,
        *,
        required: bool = False,
    ) -> int | None:
        if source_column is None:
            return None
        value = row[source_column]
        if self._is_missing(value):
            if required:
                self._raise_value_error(row_number, field_name, "must not be null")
            return None
        if isinstance(value, (bool, np.bool_)):
            self._raise_value_error(row_number, field_name, "must be a non-negative integer")

        parsed: int | None = None
        if isinstance(value, numbers.Integral):
            parsed = int(value)
        elif isinstance(value, numbers.Real) and math.isfinite(float(value)):
            if float(value).is_integer():
                parsed = int(value)
        elif (
            isinstance(value, Decimal) and value.is_finite() and value == value.to_integral_value()
        ):
            parsed = int(value)
        elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
            parsed = int(value.strip())

        if parsed is None or parsed < 0:
            self._raise_value_error(row_number, field_name, "must be a non-negative integer")
        return parsed

    def _optional_value(
        self,
        row: dict[str, Any],
        source_column: str | None,
        row_number: int,
    ) -> Any:
        if source_column is None:
            return None
        return self._normalize_value(row[source_column], row_number=row_number)

    def _required_string(self, value: Any, *, field_name: str, row_number: int) -> str:
        if self._is_missing(value) or not isinstance(value, str) or not value.strip():
            self._raise_value_error(row_number, field_name, "must be a non-empty string")
        return value.strip()

    def _normalize_value(self, value: Any, *, row_number: int) -> Any:
        if self._is_missing(value):
            normalized = None
        elif isinstance(value, np.generic):
            normalized = self._normalize_value(value.item(), row_number=row_number)
        elif isinstance(value, np.ndarray):
            normalized = [
                self._normalize_value(item, row_number=row_number) for item in value.tolist()
            ]
        elif isinstance(value, pd.Timestamp):
            normalized = value.to_pydatetime()
        elif isinstance(value, pd.Timedelta):
            normalized = value.to_pytimedelta()
        elif isinstance(value, dict):
            normalized = {
                self._normalize_value(key, row_number=row_number): self._normalize_value(
                    item, row_number=row_number
                )
                for key, item in value.items()
            }
        elif isinstance(value, list):
            normalized = [self._normalize_value(item, row_number=row_number) for item in value]
        elif isinstance(value, tuple):
            normalized = tuple(self._normalize_value(item, row_number=row_number) for item in value)
        elif isinstance(value, set):
            normalized = {self._normalize_value(item, row_number=row_number) for item in value}
        elif isinstance(value, frozenset):
            normalized = frozenset(
                self._normalize_value(item, row_number=row_number) for item in value
            )
        elif isinstance(
            value,
            (str, bytes, bool, int, float, Decimal, date, datetime, time, timedelta, UUID, Enum),
        ):
            normalized = value
        else:
            raise DataFrameSchemaMappingError(
                f"Row {row_number}: value of type {type(value).__name__!r} is not supported "
                "in schema defaults or metadata."
            )
        return normalized

    @staticmethod
    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, (dict, list, tuple, set, frozenset, np.ndarray)):
            return False
        try:
            result = pd.isna(value)
        except (TypeError, ValueError):
            return False
        return isinstance(result, (bool, np.bool_)) and bool(result)

    @staticmethod
    def _raise_value_error(row_number: int, field_name: str, message: str) -> NoReturn:
        raise DataFrameSchemaMappingError(f"Row {row_number}, field '{field_name}': {message}.")
