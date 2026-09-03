"""Normalize variable IO handles and input payload contracts.

Revision ID: 0045
Revises: 0044
Create Date: 2026-03-30 12:00:00.000000
"""

from __future__ import annotations

import ast
import json
import keyword
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0045"
down_revision: Union[str, Sequence[str], None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD_INPUT_VARIABLES_KEY = "variables"
NEW_INPUT_VARIABLES_KEY = "input_variables"
OLD_TARGET_HANDLE = "input-variables"
NEW_TARGET_HANDLE = "input-input_variables"
OLD_SOURCE_HANDLE = "output-variable"
NEW_SOURCE_HANDLE = "output-output_variables"
_RESERVED_REFERENCE_NAMES = frozenset(
    {
        "input_variables",
        "len",
        "true",
        "false",
        "none",
        "True",
        "False",
        "None",
    }
)

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


def _rename_input_values_key(
        input_values: dict[str, Any],
        *,
        source_key: str,
        target_key: str,
) -> tuple[dict[str, Any], bool]:
    if source_key not in input_values:
        return input_values, False

    updated_input_values = dict(input_values)
    source_value = updated_input_values.pop(source_key)
    if target_key not in updated_input_values:
        updated_input_values[target_key] = source_value

    return updated_input_values, True


def _is_safe_reference_name(name: str) -> bool:
    return (
        isinstance(name, str)
        and name.isidentifier()
        and not keyword.iskeyword(name)
        and name not in _RESERVED_REFERENCE_NAMES
    )


def _encode_reference_expression(name: str) -> str:
    if _is_safe_reference_name(name):
        return name
    return f"input_variables[{json.dumps(name, ensure_ascii=False)}]"


def _decode_reference_expression(expression: Any) -> str | None:
    if not isinstance(expression, str):
        return None

    if _is_safe_reference_name(expression):
        return expression

    if not expression.startswith("input_variables[") or not expression.endswith("]"):
        return None

    literal = expression[len("input_variables["):-1]
    try:
        parsed = ast.literal_eval(literal)
    except (SyntaxError, ValueError):
        return None

    return parsed if isinstance(parsed, str) else None


def _upgrade_payload(updated_payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    marker = updated_payload.get("__dvt_type")

    if marker == "var":
        mode = updated_payload.get("mode")
        if mode == "expr":
            expression_value = updated_payload.pop("expression", None)
            updated_payload.pop("mode", None)
            updated_payload.pop("name", None)
            updated_payload.pop("var_type", None)
            updated_payload["__dvt_type"] = "expr"
            updated_payload["value"] = expression_value
            changed = True
        else:
            variable_name = updated_payload.pop("name", None)
            updated_payload.pop("mode", None)
            updated_payload.pop("var_type", None)
            updated_payload["__dvt_type"] = "expr"
            updated_payload["expression_kind"] = "single"
            updated_payload["value"] = _encode_reference_expression(variable_name)
            changed = True
    elif marker == "expr" and "var_type" in updated_payload:
        updated_payload.pop("var_type", None)
        changed = True

    return updated_payload, changed


def _downgrade_payload(updated_payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    changed = False
    if updated_payload.get("__dvt_type") != "expr":
        return updated_payload, changed

    expression_value = updated_payload.pop("value", None)
    expression_kind = updated_payload.get("expression_kind")
    variable_name = (
        _decode_reference_expression(expression_value)
        if expression_kind == "single"
        else None
    )

    updated_payload.pop("var_type", None)
    updated_payload["__dvt_type"] = "var"
    if variable_name is not None:
        updated_payload.pop("expression_kind", None)
        updated_payload["name"] = variable_name
    else:
        updated_payload["mode"] = "expr"
        updated_payload["expression"] = expression_value
    changed = True
    return updated_payload, changed


def _normalize_payload(payload: Any, *, upgrade: bool) -> tuple[Any, bool]:
    if isinstance(payload, list):
        updated_items: list[Any] = []
        changed = False
        for item in payload:
            updated_item, item_changed = _normalize_payload(item, upgrade=upgrade)
            updated_items.append(updated_item)
            changed = changed or item_changed
        return updated_items, changed

    if not isinstance(payload, dict):
        return payload, False

    updated_payload = dict(payload)
    changed = False

    if upgrade:
        updated_payload, payload_changed = _upgrade_payload(updated_payload)
    else:
        updated_payload, payload_changed = _downgrade_payload(updated_payload)
    changed = changed or payload_changed

    for key, value in list(updated_payload.items()):
        normalized_value, value_changed = _normalize_payload(value, upgrade=upgrade)
        updated_payload[key] = normalized_value
        changed = changed or value_changed

    return updated_payload, changed


def _rewrite_input_values(
        input_values: dict[str, Any],
        *,
        source_key: str,
        target_key: str,
        upgrade: bool,
) -> tuple[dict[str, Any], bool]:
    updated_input_values, changed = _rename_input_values_key(
        input_values,
        source_key=source_key,
        target_key=target_key,
    )

    for key, value in list(updated_input_values.items()):
        normalized_value, value_changed = _normalize_payload(value, upgrade=upgrade)
        updated_input_values[key] = normalized_value
        changed = changed or value_changed

    return updated_input_values, changed


def _payload_needs_rewrite(payload: Any, *, upgrade: bool) -> bool:
    _, changed = _normalize_payload(payload, upgrade=upgrade)
    return changed


def _load_target_rows(
        bind: sa.Connection,
        source_key: str,
        *,
        upgrade: bool,
) -> list[dict[str, Any]]:
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
        if source_key in parsed_input_values or _payload_needs_rewrite(
            parsed_input_values,
            upgrade=upgrade,
        ):
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


def _migrate_graph_node_input_values(
        *,
        source_key: str,
        target_key: str,
        upgrade: bool,
) -> None:
    bind = op.get_bind()
    rows = _load_target_rows(
        bind,
        source_key,
        upgrade=upgrade,
    )

    updates: list[dict[str, Any]] = []
    for row in rows:
        parsed_input_values = _deserialize_input_values(row["input_values"])
        if parsed_input_values is None:
            continue

        converted_input_values, changed = _rewrite_input_values(
            parsed_input_values,
            source_key=source_key,
            target_key=target_key,
            upgrade=upgrade,
        )
        if not changed:
            continue

        updates.append(
            {
                "row_id": row["id"],
                "row_input_values": converted_input_values,
            }
        )

    _persist_updates(bind, updates)


def _rename_graph_edge_target_handle(*, source_handle: str, target_handle: str) -> None:
    op.execute(
        sa.text(
            """
            UPDATE graph_edges
            SET target_handle = :target_handle
            WHERE target_handle = :source_handle
            """
        ).bindparams(
            source_handle=source_handle,
            target_handle=target_handle,
        )
    )


def _rename_graph_edge_source_handle(*, source_handle: str, target_handle: str) -> None:
    op.execute(
        sa.text(
            """
            UPDATE graph_edges
            SET source_handle = :target_handle
            WHERE source_handle = :source_handle
            """
        ).bindparams(
            source_handle=source_handle,
            target_handle=target_handle,
        )
    )


def upgrade() -> None:
    op.add_column(
        "graph_nodes",
        sa.Column(
            "show_variables_io",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _migrate_graph_node_input_values(
        source_key=OLD_INPUT_VARIABLES_KEY,
        target_key=NEW_INPUT_VARIABLES_KEY,
        upgrade=True,
    )
    _rename_graph_edge_target_handle(
        source_handle=OLD_TARGET_HANDLE,
        target_handle=NEW_TARGET_HANDLE,
    )
    _rename_graph_edge_source_handle(
        source_handle=OLD_SOURCE_HANDLE,
        target_handle=NEW_SOURCE_HANDLE,
    )


def downgrade() -> None:
    _migrate_graph_node_input_values(
        source_key=NEW_INPUT_VARIABLES_KEY,
        target_key=OLD_INPUT_VARIABLES_KEY,
        upgrade=False,
    )
    _rename_graph_edge_target_handle(
        source_handle=NEW_TARGET_HANDLE,
        target_handle=OLD_TARGET_HANDLE,
    )
    _rename_graph_edge_source_handle(
        source_handle=NEW_SOURCE_HANDLE,
        target_handle=OLD_SOURCE_HANDLE,
    )
    op.drop_column("graph_nodes", "show_variables_io")
