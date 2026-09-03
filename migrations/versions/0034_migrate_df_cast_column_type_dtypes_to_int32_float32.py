"""Migrate DataFrameCastColumnType dtypes int/float to Int32/Float32.

Revision ID: 0034
Revises: 0033
Create Date: 2026-03-10 14:30:00.000000
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0034"
down_revision: Union[str, Sequence[str], None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CAST_NODE_NAME = "dataframecastcolumntype"

UPGRADE_DTYPE_REPLACEMENTS: dict[str, str] = {
    "int": "Int32",
    "float": "Float32",
}

DOWNGRADE_DTYPE_REPLACEMENTS: dict[str, str] = {
    "Int32": "int",
    "Float32": "float",
}


graph_nodes_table = sa.table(
    "graph_nodes",
    sa.column("id", sa.String()),
    sa.column("name", sa.String()),
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
    marker = value.get("__dvt_type", value.get("dvt_type"))
    return str(marker) if marker is not None else None


def _replace_dtypes_mapping(
    dtypes: dict[str, Any],
    replacements: dict[str, str],
) -> tuple[dict[str, Any], bool]:
    updated: dict[str, Any] = {}
    changed = False

    for key, value in dtypes.items():
        if isinstance(value, str) and value in replacements:
            updated[key] = replacements[value]
            changed = True
        else:
            updated[key] = value

    return updated, changed


def _convert_dtypes_payload(
    raw_dtypes: Any,
    replacements: dict[str, str],
) -> tuple[Any, bool]:
    if not isinstance(raw_dtypes, dict):
        return raw_dtypes, False

    marker = _resolve_dvt_type_marker(raw_dtypes)

    if marker == "const":
        raw_value = raw_dtypes.get("value")
        if not isinstance(raw_value, dict):
            return raw_dtypes, False

        converted_value, changed = _replace_dtypes_mapping(raw_value, replacements)
        if not changed:
            return raw_dtypes, False

        updated_wrapper = dict(raw_dtypes)
        updated_wrapper["value"] = converted_value
        return updated_wrapper, True

    if marker is None:
        return _replace_dtypes_mapping(raw_dtypes, replacements)

    return raw_dtypes, False


def _convert_input_values(
    input_values: dict[str, Any],
    replacements: dict[str, str],
) -> tuple[dict[str, Any], bool]:
    if "dtypes" not in input_values:
        return input_values, False

    converted_dtypes, changed = _convert_dtypes_payload(input_values.get("dtypes"), replacements)
    if not changed:
        return input_values, False

    updated_input_values = dict(input_values)
    updated_input_values["dtypes"] = converted_dtypes
    return updated_input_values, True


def _load_target_rows(bind: sa.Connection) -> list[dict[str, Any]]:
    statement = (
        sa.select(
            graph_nodes_table.c.id,
            graph_nodes_table.c.input_values,
        )
        .where(sa.func.lower(graph_nodes_table.c.name) == CAST_NODE_NAME)
        .where(graph_nodes_table.c.input_values.is_not(None))
    )
    result = bind.execute(statement)
    return list(result.mappings())


def _persist_updates(bind: sa.Connection, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    statement = (
        sa.update(graph_nodes_table)
        .where(graph_nodes_table.c.id == sa.bindparam("row_id"))
        .values(input_values=sa.bindparam("row_input_values"))
    )
    bind.execute(statement, updates)


def _run_migration(bind: sa.Connection, replacements: dict[str, str]) -> None:
    rows = _load_target_rows(bind)

    updates: list[dict[str, Any]] = []
    for row in rows:
        input_values = _deserialize_input_values(row["input_values"])
        if input_values is None:
            continue

        converted_input_values, changed = _convert_input_values(input_values, replacements)
        if not changed:
            continue

        updates.append(
            {
                "row_id": row["id"],
                "row_input_values": converted_input_values,
            }
        )

    _persist_updates(bind, updates)


def upgrade() -> None:
    bind = op.get_bind()
    _run_migration(bind, UPGRADE_DTYPE_REPLACEMENTS)


def downgrade() -> None:
    bind = op.get_bind()
    _run_migration(bind, DOWNGRADE_DTYPE_REPLACEMENTS)
