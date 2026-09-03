from __future__ import annotations

import datetime as dt
import math
import re
import uuid
from collections.abc import Collection
from decimal import Decimal
from typing import Any

from src.modules.sql_template.domain import SQLTemplateSerializationError

_IDENTIFIER_SEGMENT_RE = re.compile(r"^[^\x00-\x1f.]+$")


def _quote_character(dialect_name: str | None) -> tuple[str, str]:
    normalized = (dialect_name or "").lower()
    if normalized in {"mssql", "tsql"}:
        return "[", "]"
    if normalized in {"clickhouse", "mysql"}:
        return "`", "`"
    return '"', '"'


class SQLLiteralSerializer:
    def serialize(self, value: Any, *, dialect_name: str | None) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if (dialect_name or "").lower() in {"mssql", "tsql"} and value else (
                "0" if (dialect_name or "").lower() in {"mssql", "tsql"} else ("TRUE" if value else "FALSE")
            )
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            return str(value)
        if isinstance(value, float):
            if not math.isfinite(value):
                raise SQLTemplateSerializationError("Non-finite numbers cannot be rendered as SQL literals.")
            return repr(value)
        if isinstance(value, str):
            return "'" + value.replace("'", "''") + "'"
        if isinstance(value, (dt.datetime, dt.date, dt.time, uuid.UUID)):
            return "'" + str(value).replace("'", "''") + "'"
        if isinstance(value, Collection) and not isinstance(value, (bytes, bytearray, dict)):
            values = list(value)
            if not values:
                raise SQLTemplateSerializationError("Empty collections cannot be rendered as SQL literals.")
            return ", ".join(self.serialize(item, dialect_name=dialect_name) for item in values)
        raise SQLTemplateSerializationError(
            f"Values of type '{type(value).__name__}' cannot be rendered as SQL literals."
        )

    @staticmethod
    def escape_quoted_content(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list, tuple, set)):
            raise SQLTemplateSerializationError(
                "Collections and mappings cannot be rendered inside a quoted SQL literal."
            )
        return str(value).replace("'", "''")


class SQLIdentifierSerializer:
    def serialize(self, value: Any, *, dialect_name: str | None) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SQLTemplateSerializationError("SQL identifiers must be non-empty strings.")
        left, right = _quote_character(dialect_name)
        segments = value.split(".")
        if any(not segment or _IDENTIFIER_SEGMENT_RE.fullmatch(segment) is None for segment in segments):
            raise SQLTemplateSerializationError(f"Unsafe SQL identifier '{value}'.")
        return ".".join(
            left + segment.replace(right, right + right) + right
            for segment in segments
        )
