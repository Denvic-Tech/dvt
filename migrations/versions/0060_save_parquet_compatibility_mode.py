"""Mark existing SaveParquet nodes as legacy.

Revision ID: 0060
Revises: 0059
Create Date: 2026-08-25 15:20:00.000000
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0060"
down_revision: Union[str, Sequence[str], None] = "0059"
branch_labels = None
depends_on = None

SAVE_PARQUET = "SaveParquet"
COMPATIBILITY_FIELD = "compatibility_mode"

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


def _legacy_payload() -> dict[str, Any]:
    return {"__dvt_type": "const", "value": "legacy"}


def _upgrade_input_values(input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if COMPATIBILITY_FIELD in input_values:
        return input_values, False
    updated = dict(input_values)
    updated[COMPATIBILITY_FIELD] = _legacy_payload()
    return updated, True


def _downgrade_input_values(input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if COMPATIBILITY_FIELD not in input_values:
        return input_values, False
    updated = dict(input_values)
    updated.pop(COMPATIBILITY_FIELD, None)
    return updated, True


def _migrate(converter) -> None:
    bind = op.get_bind()
    rows = list(
        bind.execute(
            sa.select(graph_nodes_table.c.id, graph_nodes_table.c.input_values).where(
                sa.func.lower(graph_nodes_table.c.name) == SAVE_PARQUET.lower()
            )
        ).mappings()
    )

    updates: list[dict[str, Any]] = []
    for row in rows:
        parsed = _deserialize_input_values(row["input_values"])
        if parsed is None:
            continue
        converted, changed = converter(parsed)
        if changed:
            updates.append({"row_id": row["id"], "row_input_values": converted})

    if updates:
        bind.execute(
            sa.update(graph_nodes_table)
            .where(graph_nodes_table.c.id == sa.bindparam("row_id"))
            .values(input_values=sa.bindparam("row_input_values")),
            updates,
        )


def upgrade() -> None:
    _migrate(_upgrade_input_values)


def downgrade() -> None:
    _migrate(_downgrade_input_values)
