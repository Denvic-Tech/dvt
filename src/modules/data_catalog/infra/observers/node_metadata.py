"""Преобразование метаданных выполненной Read-ноды в доменное наблюдение схемы."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from core.types import DataFrameMetadata
from core.types.db_column import DBColumn

from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.variables import is_unresolved_value
from src.pipeline.execution_mode import PipelineExecutionMode

from ...domain import ObservedField, ObservedNodeSchema

OBSERVED_READ_NODES = frozenset({"ReadTableFromDBV3"})
_SERVICE_NODE_PREFIX = "__service_output"


def _text(value: Any) -> str | None:
    if value is None or is_unresolved_value(value):
        return None
    text = str(value).strip()
    return text or None


def build_observation(
    node: Any,
    metadata: Mapping[str, Any] | None,
    *,
    project_id: str,
) -> ObservedNodeSchema | None:
    """Возвращает наблюдение или None, если ноду нельзя безопасно сопоставить с сущностью.

    Пропускаются: не-Read ноды, служебные ноды, mock-подключения без идентификатора,
    пустая схема (нерезолвленный локатор) и выходы без DataFrame-метаданных.
    """
    if type(node).__name__ not in OBSERVED_READ_NODES:
        return None

    node_id = getattr(node, "node_id", None) or getattr(node, "_node_id", None)
    if not node_id or str(node_id).startswith(_SERVICE_NODE_PREFIX):
        return None

    connection = getattr(node, "connection", None)
    if not isinstance(connection, SqlConnectionRecord):
        return None

    output = (metadata or {}).get("output")
    if not isinstance(output, DataFrameMetadata) or not output.columns:
        return None

    mode = getattr(node, "execution_mode", None)
    all_db_columns = all(isinstance(column, DBColumn) for column in output.columns)
    trust_types = mode == PipelineExecutionMode.METADATA_ONLY and all_db_columns

    fields = tuple(
        ObservedField(
            name=column.name,
            dtype=str(column.dtype) if column.dtype is not None else None,
            nullable=column.nullable,
            ordinal=position,
            primary_key=bool(getattr(column, "primary_key", False) or False),
            comment=column.comment,
        )
        for position, column in enumerate(output.columns, start=1)
    )

    updated_at = getattr(getattr(connection, "record", None), "updated_at", None)
    revision = updated_at.isoformat() if isinstance(updated_at, datetime) else "unversioned"

    return ObservedNodeSchema(
        project_id=project_id,
        node_id=str(node_id),
        connection_id=str(connection.id),
        connection_revision=revision,
        fields=fields,
        observed_at=datetime.now(UTC),
        trust_types=trust_types,
        partial=bool(getattr(node, "columns", None)),
        locator_parts={
            "table": _text(getattr(node, "table_name", None)),
            "schema": _text(getattr(node, "schema_name", None)),
            "database": _text(getattr(node, "database_name", None)),
        },
    )
