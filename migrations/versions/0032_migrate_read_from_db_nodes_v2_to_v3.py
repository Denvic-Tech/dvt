"""Migrate Read*FromDB nodes from V2 to V3.

Revision ID: 0032
Revises: 0031
Create Date: 2026-03-03 11:00:00.000000
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0032"
down_revision: Union[str, Sequence[str], None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


READ_TABLE_FROM_DB_V2 = "ReadTableFromDBV2"
READ_TABLE_FROM_DB_V3 = "ReadTableFromDBV3"
READ_QUERY_FROM_DB_V2 = "ReadQueryFromDBV2"
READ_QUERY_FROM_DB_V3 = "ReadQueryFromDBV3"
READ_TABLE_FROM_DB_V2_DISPLAY = "Read Table From DB V2"
READ_TABLE_FROM_DB_V3_DISPLAY = "Read Table From DB V3"
READ_QUERY_FROM_DB_V2_DISPLAY = "Read Query From DB V2"
READ_QUERY_FROM_DB_V3_DISPLAY = "Read Query From DB V3"

UPGRADE_NODE_NAME_MAP: dict[str, str] = {
    READ_TABLE_FROM_DB_V2.lower(): READ_TABLE_FROM_DB_V3,
    READ_QUERY_FROM_DB_V2.lower(): READ_QUERY_FROM_DB_V3,
}
DOWNGRADE_NODE_NAME_MAP: dict[str, str] = {
    READ_TABLE_FROM_DB_V3.lower(): READ_TABLE_FROM_DB_V2,
    READ_QUERY_FROM_DB_V3.lower(): READ_QUERY_FROM_DB_V2,
}
UPGRADE_NODE_DISPLAY_NAME_MAP: dict[str, tuple[str, str]] = {
    READ_TABLE_FROM_DB_V2.lower(): (READ_TABLE_FROM_DB_V2_DISPLAY, READ_TABLE_FROM_DB_V3_DISPLAY),
    READ_QUERY_FROM_DB_V2.lower(): (READ_QUERY_FROM_DB_V2_DISPLAY, READ_QUERY_FROM_DB_V3_DISPLAY),
}
DOWNGRADE_NODE_DISPLAY_NAME_MAP: dict[str, tuple[str, str]] = {
    READ_TABLE_FROM_DB_V3.lower(): (READ_TABLE_FROM_DB_V3_DISPLAY, READ_TABLE_FROM_DB_V2_DISPLAY),
    READ_QUERY_FROM_DB_V3.lower(): (READ_QUERY_FROM_DB_V3_DISPLAY, READ_QUERY_FROM_DB_V2_DISPLAY),
}

graph_nodes_table = sa.table(
    "graph_nodes",
    sa.column("id", sa.String()),
    sa.column("name", sa.String()),
    sa.column("display_name", sa.String()),
    sa.column("input_values", sa.JSON()),
)


def _deserialize_input_values(raw_value: Any) -> dict[str, Any] | None:
    if isinstance(raw_value, dict):
        return raw_value

    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    return None


def _resolve_dvt_type_marker(value: dict[str, Any]) -> str | None:
    return str(value.get("__dvt_type", value.get("dvt_type"))) if isinstance(value, dict) else None


def _has_effective_value(value: Any) -> bool:
    """Match V2 fallback semantics where partition_col uses truthy index_col."""
    if isinstance(value, dict):
        marker = _resolve_dvt_type_marker(value)
        if marker == "const":
            return bool(value.get("value"))
        return bool(value)
    return bool(value)


def _convert_read_table_inputs_to_v3(input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if "index_col" not in input_values:
        return input_values, False

    updated_input_values = dict(input_values)
    index_col_value = updated_input_values.get("index_col")
    partition_col_value = updated_input_values.get("partition_col")

    if not _has_effective_value(partition_col_value) and _has_effective_value(index_col_value):
        updated_input_values["partition_col"] = index_col_value

    updated_input_values.pop("index_col", None)
    return updated_input_values, True


def _convert_read_table_inputs_to_v2(input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    updated_input_values = dict(input_values)
    changed = False

    if "max_rows_per_partition" in updated_input_values:
        updated_input_values.pop("max_rows_per_partition", None)
        changed = True

    index_col_value = updated_input_values.get("index_col")
    partition_col_value = updated_input_values.get("partition_col")
    if not _has_effective_value(index_col_value) and _has_effective_value(partition_col_value):
        updated_input_values["index_col"] = partition_col_value
        changed = True

    return updated_input_values, changed


def _convert_read_query_inputs_to_v2(input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    updated_input_values = dict(input_values)
    changed = False

    if "limit" in updated_input_values:
        updated_input_values.pop("limit", None)
        changed = True

    if "max_rows_per_partition" in updated_input_values:
        updated_input_values.pop("max_rows_per_partition", None)
        changed = True

    return updated_input_values, changed


def _convert_display_name(
        display_name: Any,
        *,
        source_display_name: str,
        target_display_name: str
) -> tuple[Any, bool]:
    if isinstance(display_name, str) and display_name.lower() == source_display_name.lower():
        return target_display_name, True
    return display_name, False


def _convert_row_for_upgrade(
        node_name: str,
        display_name: Any,
        raw_input_values: Any
) -> tuple[str, Any, Any, bool]:
    target_name = UPGRADE_NODE_NAME_MAP.get(node_name.lower())
    if target_name is None:
        return node_name, display_name, raw_input_values, False

    changed = target_name != node_name
    source_display_name, target_display_name = UPGRADE_NODE_DISPLAY_NAME_MAP[node_name.lower()]
    converted_display_name, display_name_changed = _convert_display_name(
        display_name,
        source_display_name=source_display_name,
        target_display_name=target_display_name,
    )
    changed = changed or display_name_changed

    converted_input_values = raw_input_values
    parsed_input_values = _deserialize_input_values(raw_input_values)

    if target_name == READ_TABLE_FROM_DB_V3 and parsed_input_values is not None:
        converted_table_values, table_values_changed = _convert_read_table_inputs_to_v3(parsed_input_values)
        if table_values_changed:
            converted_input_values = converted_table_values
            changed = True

    return target_name, converted_display_name, converted_input_values, changed


def _convert_row_for_downgrade(
        node_name: str,
        display_name: Any,
        raw_input_values: Any
) -> tuple[str, Any, Any, bool]:
    target_name = DOWNGRADE_NODE_NAME_MAP.get(node_name.lower())
    if target_name is None:
        return node_name, display_name, raw_input_values, False

    changed = target_name != node_name
    source_display_name, target_display_name = DOWNGRADE_NODE_DISPLAY_NAME_MAP[node_name.lower()]
    converted_display_name, display_name_changed = _convert_display_name(
        display_name,
        source_display_name=source_display_name,
        target_display_name=target_display_name,
    )
    changed = changed or display_name_changed

    converted_input_values = raw_input_values
    parsed_input_values = _deserialize_input_values(raw_input_values)

    if parsed_input_values is None:
        return target_name, converted_display_name, converted_input_values, changed

    if target_name == READ_TABLE_FROM_DB_V2:
        converted_table_values, table_values_changed = _convert_read_table_inputs_to_v2(parsed_input_values)
        if table_values_changed:
            converted_input_values = converted_table_values
            changed = True
        return target_name, converted_display_name, converted_input_values, changed

    if target_name == READ_QUERY_FROM_DB_V2:
        converted_query_values, query_values_changed = _convert_read_query_inputs_to_v2(parsed_input_values)
        if query_values_changed:
            converted_input_values = converted_query_values
            changed = True

    return target_name, converted_display_name, converted_input_values, changed


def _load_target_rows(bind: sa.Connection, source_node_names: Sequence[str]) -> list[dict[str, Any]]:
    if not source_node_names:
        return []

    statement = (
        sa.select(
            graph_nodes_table.c.id,
            graph_nodes_table.c.name,
            graph_nodes_table.c.display_name,
            graph_nodes_table.c.input_values,
        )
        .where(sa.func.lower(graph_nodes_table.c.name).in_(tuple(source_node_names)))
    )
    result = bind.execute(statement)
    return list(result.mappings())


def _persist_updates(bind: sa.Connection, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    statement = (
        sa.update(graph_nodes_table)
        .where(graph_nodes_table.c.id == sa.bindparam("row_id"))
        .values(
            name=sa.bindparam("row_name"),
            display_name=sa.bindparam("row_display_name"),
            input_values=sa.bindparam("row_input_values"),
        )
    )
    bind.execute(statement, updates)


def upgrade() -> None:
    bind = op.get_bind()
    rows = _load_target_rows(bind, list(UPGRADE_NODE_NAME_MAP.keys()))

    updates: list[dict[str, Any]] = []
    for row in rows:
        converted_name, converted_display_name, converted_input_values, changed = _convert_row_for_upgrade(
            node_name=row["name"],
            display_name=row["display_name"],
            raw_input_values=row["input_values"],
        )
        if not changed:
            continue

        updates.append(
            {
                "row_id": row["id"],
                "row_name": converted_name,
                "row_display_name": converted_display_name,
                "row_input_values": converted_input_values,
            }
        )

    _persist_updates(bind, updates)


def downgrade() -> None:
    bind = op.get_bind()
    rows = _load_target_rows(bind, list(DOWNGRADE_NODE_NAME_MAP.keys()))

    updates: list[dict[str, Any]] = []
    for row in rows:
        converted_name, converted_display_name, converted_input_values, changed = _convert_row_for_downgrade(
            node_name=row["name"],
            display_name=row["display_name"],
            raw_input_values=row["input_values"],
        )
        if not changed:
            continue

        updates.append(
            {
                "row_id": row["id"],
                "row_name": converted_name,
                "row_display_name": converted_display_name,
                "row_input_values": converted_input_values,
            }
        )

    _persist_updates(bind, updates)
