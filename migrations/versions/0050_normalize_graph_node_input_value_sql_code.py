"""normalize_graph_node_input_value_sql_code

Revision ID: 0050
Revises: 0049
Create Date: 2026-05-20 15:32:16.452846
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0050"
down_revision: Union[str, Sequence[str], None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


graph_nodes_table = sa.table(
    "graph_nodes",
    sa.column("id", sa.String()),
    sa.column("ui_id", sa.String()),
    sa.column("name", sa.String()),
    sa.column("input_values", sa.JSON()),
)

graph_edges_table = sa.table(
    "graph_edges",
    sa.column("id", sa.String()),
    sa.column("target", sa.String()),
    sa.column("target_handle", sa.String()),
)


READ_QUERY_FROM_DB_V3 = "ReadQueryFromDBV3"
READ_VARIABLES_FROM_DB = "ReadVariablesFromDB"
EXECUTE_SQL = "ExecuteSQL"

legacy_input_name_by_node = {
    READ_QUERY_FROM_DB_V3: "query",
    READ_VARIABLES_FROM_DB: "sql_query",
    EXECUTE_SQL: "sql",
}

target_node_names = frozenset(legacy_input_name_by_node)

old_input_names = tuple(dict.fromkeys(legacy_input_name_by_node.values()))

new_input_name = "sql_code"
new_target_handle = f"input-{new_input_name}"
_MISSING = object()


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


def _iter_legacy_input_names(node_name: str) -> Iterable[str]:
    preferred_name = legacy_input_name_by_node[node_name]
    yield preferred_name
    for input_name in old_input_names:
        if input_name != preferred_name:
            yield input_name


def _upgrade_input_values(node_name: str, input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if node_name not in legacy_input_name_by_node:
        return input_values, False

    updated_input_values = dict(input_values)
    changed = False
    new_value = updated_input_values.get(new_input_name, _MISSING)

    if new_value is _MISSING:
        for input_name in _iter_legacy_input_names(node_name):
            if input_name in updated_input_values:
                new_value = updated_input_values[input_name]
                break

    for input_name in old_input_names:
        if input_name in updated_input_values:
            updated_input_values.pop(input_name, None)
            changed = True

    if new_value is not _MISSING and new_input_name not in updated_input_values:
        updated_input_values[new_input_name] = new_value
        changed = True

    return updated_input_values, changed


def _downgrade_input_values(node_name: str, input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    target_input_name = legacy_input_name_by_node.get(node_name)
    if target_input_name is None:
        return input_values, False

    updated_input_values = dict(input_values)
    changed = False
    new_value = updated_input_values.pop(new_input_name, _MISSING)
    if new_value is not _MISSING:
        changed = True

    for input_name in old_input_names:
        if input_name != target_input_name and input_name in updated_input_values:
            updated_input_values.pop(input_name, None)
            changed = True

    if new_value is not _MISSING and target_input_name not in updated_input_values:
        updated_input_values[target_input_name] = new_value
        changed = True

    return updated_input_values, changed


def _rename_edge_handle(node_name: str, target_handle: str, *, upgrade: bool) -> str | None:
    legacy_input_name = legacy_input_name_by_node.get(node_name)
    if legacy_input_name is None:
        return None

    if upgrade:
        if target_handle == f"input-{legacy_input_name}":
            return new_target_handle
        return None

    if target_handle == new_target_handle:
        return f"input-{legacy_input_name}"
    return None


def _load_target_rows(bind: sa.Connection) -> list[dict[str, Any]]:
    statement = (
        sa.select(
            graph_nodes_table.c.id,
            graph_nodes_table.c.name,
            graph_nodes_table.c.input_values,
        )
        .where(sa.func.lower(graph_nodes_table.c.name).in_(tuple(name.lower() for name in target_node_names)))
    )
    return list(bind.execute(statement).mappings())


def _load_target_edges(bind: sa.Connection, *, upgrade: bool) -> list[dict[str, Any]]:
    relevant_handles = (
        tuple(f"input-{name}" for name in old_input_names)
        if upgrade
        else (new_target_handle,)
    )
    statement = (
        sa.select(
            graph_edges_table.c.id,
            graph_edges_table.c.target_handle,
            graph_nodes_table.c.name.label("node_name"),
        )
        .select_from(
            graph_edges_table.join(graph_nodes_table, graph_edges_table.c.target == graph_nodes_table.c.ui_id)
        )
        .where(sa.func.lower(graph_nodes_table.c.name).in_(tuple(name.lower() for name in target_node_names)))
        .where(graph_edges_table.c.target_handle.in_(relevant_handles))
    )
    return list(bind.execute(statement).mappings())


def _persist_input_updates(bind: sa.Connection, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    statement = (
        sa.update(graph_nodes_table)
        .where(graph_nodes_table.c.id == sa.bindparam("row_id"))
        .values(input_values=sa.bindparam("row_input_values"))
    )
    bind.execute(statement, updates)


def _persist_edge_updates(bind: sa.Connection, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    statement = (
        sa.update(graph_edges_table)
        .where(graph_edges_table.c.id == sa.bindparam("row_id"))
        .values(target_handle=sa.bindparam("row_target_handle"))
    )
    bind.execute(statement, updates)


def _migrate_graph_node_input_values(*, upgrade: bool) -> None:
    bind = op.get_bind()
    rows = _load_target_rows(bind)
    edges = _load_target_edges(bind, upgrade=upgrade)

    input_updates: list[dict[str, Any]] = []
    for row in rows:
        input_values = _deserialize_input_values(row["input_values"])
        if input_values is None:
            continue

        if upgrade:
            converted_input_values, changed = _upgrade_input_values(row["name"], input_values)
        else:
            converted_input_values, changed = _downgrade_input_values(row["name"], input_values)
        if not changed:
            continue

        input_updates.append(
            {
                "row_id": row["id"],
                "row_input_values": converted_input_values,
            }
        )

    edge_updates: list[dict[str, Any]] = []
    for row in edges:
        target_handle = _rename_edge_handle(
            row["node_name"],
            row["target_handle"],
            upgrade=upgrade,
        )
        if target_handle is None:
            continue

        edge_updates.append(
            {
                "row_id": row["id"],
                "row_target_handle": target_handle,
            }
        )

    _persist_input_updates(bind, input_updates)
    _persist_edge_updates(bind, edge_updates)


def upgrade() -> None:
    _migrate_graph_node_input_values(upgrade=True)


def downgrade() -> None:
    _migrate_graph_node_input_values(upgrade=False)
