"""Nullability reflection corrections for wrapped ClickHouse types."""

from collections.abc import Mapping
from typing import Any

from clickhouse_sqlalchemy import types as ch_types
from sqlalchemy.sql.type_api import to_instance


def reflected_column_nullable(column: Mapping[str, Any], dialect_name: str) -> bool:
    if dialect_name == "clickhouse" and column.get("type") is not None:
        column_type = to_instance(column["type"])
        if isinstance(column_type, ch_types.LowCardinality):
            column_type = to_instance(column_type.nested_type)
        # Nullable elements inside Array/Tuple do not make the column nullable.
        return isinstance(column_type, ch_types.Nullable)
    return bool(column.get("nullable", True))
