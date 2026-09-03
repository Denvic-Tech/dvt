"""normalize_graph_node_input_value_type_keys

Revision ID: 0047
Revises: 0046
Create Date: 2026-05-12 13:30:00.000000
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0047"
down_revision: Union[str, Sequence[str], None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


graph_nodes_table = sa.table(
    "graph_nodes",
    sa.column("id", sa.String()),
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


def _rewrite_type_keys(payload: Any, *, upgrade: bool) -> tuple[Any, bool]:
    if isinstance(payload, list):
        changed = False
        updated_items: list[Any] = []
        for item in payload:
            updated_item, item_changed = _rewrite_type_keys(item, upgrade=upgrade)
            updated_items.append(updated_item)
            changed = changed or item_changed
        return updated_items, changed

    if not isinstance(payload, dict):
        return payload, False

    updated_payload = dict(payload)
    changed = False

    if upgrade:
        legacy_marker = updated_payload.pop("dvt_type", None)
        canonical_marker = updated_payload.get("__dvt_type")
        if canonical_marker is None and legacy_marker is not None:
            updated_payload["__dvt_type"] = legacy_marker
            changed = True
        elif legacy_marker is not None:
            changed = True
    else:
        canonical_marker = updated_payload.pop("__dvt_type", None)
        legacy_marker = updated_payload.get("dvt_type")
        if legacy_marker is None and canonical_marker is not None:
            updated_payload["dvt_type"] = canonical_marker
            changed = True
        elif canonical_marker is not None:
            changed = True

    for key, value in list(updated_payload.items()):
        normalized_value, value_changed = _rewrite_type_keys(value, upgrade=upgrade)
        updated_payload[key] = normalized_value
        changed = changed or value_changed

    return updated_payload, changed


def _load_target_rows(bind: sa.Connection, *, upgrade: bool) -> list[dict[str, Any]]:
    statement = sa.select(
        graph_nodes_table.c.id,
        graph_nodes_table.c.input_values,
    )
    result = bind.execute(statement)

    rows: list[dict[str, Any]] = []
    for row in result.mappings():
        parsed_input_values = _deserialize_input_values(row["input_values"])
        if parsed_input_values is None:
            continue

        _, changed = _rewrite_type_keys(parsed_input_values, upgrade=upgrade)
        if changed:
            rows.append(dict(row))

    return rows


def _persist_updates(bind: sa.Connection, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    statement = (
        sa.update(graph_nodes_table)
        .where(graph_nodes_table.c.id == sa.bindparam("row_id"))
        .values(input_values=sa.bindparam("row_input_values"))
    )
    bind.execute(statement, updates)


def _migrate_graph_node_input_values(*, upgrade: bool) -> None:
    bind = op.get_bind()
    rows = _load_target_rows(bind, upgrade=upgrade)

    updates: list[dict[str, Any]] = []
    for row in rows:
        parsed_input_values = _deserialize_input_values(row["input_values"])
        if parsed_input_values is None:
            continue

        converted_input_values, changed = _rewrite_type_keys(parsed_input_values, upgrade=upgrade)
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
    _migrate_graph_node_input_values(upgrade=True)


def downgrade() -> None:
    _migrate_graph_node_input_values(upgrade=False)
