"""Migrate DataFrameFilter input_values to conditions tree

Revision ID: 0027
Revises: 0026
Create Date: 2026-02-18 20:10:00.000000

"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: Union[str, Sequence[str], None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NULL_VALUE = "__dvt_null_value"
FILTER_NODE_NAME = "dataframefilter"


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


def _unwrap_const_wrapper(value: Any) -> Any:
    if isinstance(value, dict) and value.get("__dvt_type") == "const":
        return value.get("value")
    return value


def _wrap_const_wrapper(value: Any) -> dict[str, Any]:
    return {"__dvt_type": "const", "value": value}


def _build_true_condition() -> dict[str, Any]:
    return {
        "kind": "condition",
        "left": {"type": "literal", "value": True},
        "operator": "==",
        "right": {"type": "literal", "value": True},
    }


def _legacy_condition_to_tree_node(raw_condition: Any) -> dict[str, Any] | None:
    if not isinstance(raw_condition, dict):
        return None

    column = raw_condition.get("column")
    if not isinstance(column, str) or not column:
        return None

    operator_name = str(raw_condition.get("operator") or "==")
    node: dict[str, Any] = {
        "kind": "condition",
        "left": {"type": "column", "column": column},
        "operator": operator_name,
        "right": None,
    }

    if operator_name not in {"isnull", "notnull"}:
        raw_value = raw_condition.get("value")
        literal_value = NULL_VALUE if raw_value is None else raw_value
        node["right"] = {"type": "literal", "value": literal_value}

    return node


def _convert_legacy_filter_inputs(input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if "conditions" in input_values or "filter_conditions" not in input_values:
        return input_values, False

    raw_filter_conditions = _unwrap_const_wrapper(input_values.get("filter_conditions"))
    raw_logic = _unwrap_const_wrapper(input_values.get("logic"))

    logic_kind = "or" if str(raw_logic).upper() == "OR" else "and"

    converted_conditions: list[dict[str, Any]] = []
    if isinstance(raw_filter_conditions, list):
        for item in raw_filter_conditions:
            converted_item = _legacy_condition_to_tree_node(item)
            if converted_item is not None:
                converted_conditions.append(converted_item)

    if converted_conditions:
        conditions_tree: dict[str, Any] = {
            "kind": logic_kind,
            "conditions": converted_conditions,
        }
    else:
        conditions_tree = _build_true_condition()

    updated_input_values = dict(input_values)
    updated_input_values.pop("filter_conditions", None)
    updated_input_values.pop("logic", None)
    updated_input_values["conditions"] = _wrap_const_wrapper(conditions_tree)

    return updated_input_values, True


def _is_true_condition(node: Any) -> bool:
    if not isinstance(node, dict):
        return False

    if node.get("kind") != "condition" or node.get("operator") != "==":
        return False

    left = node.get("left")
    right = node.get("right")

    return (
        isinstance(left, dict)
        and isinstance(right, dict)
        and left.get("type") == "literal"
        and right.get("type") == "literal"
        and left.get("value") is True
        and right.get("value") is True
    )


def _tree_condition_to_legacy(raw_condition: Any) -> dict[str, Any] | None:
    if not isinstance(raw_condition, dict):
        return None

    if raw_condition.get("kind") != "condition":
        return None

    left = raw_condition.get("left")
    if not isinstance(left, dict) or left.get("type") != "column":
        return None

    column = left.get("column")
    if not isinstance(column, str) or not column:
        return None

    operator_name = str(raw_condition.get("operator") or "==")

    value: Any = None
    if operator_name not in {"isnull", "notnull"}:
        right = raw_condition.get("right")
        if isinstance(right, dict) and right.get("type") == "literal":
            value = right.get("value")
            if value == NULL_VALUE:
                value = None
        elif isinstance(right, dict) and right.get("type") == "column":
            value = {
                "__dvt_type": "column",
                "column": right.get("column"),
            }

    return {
        "column": column,
        "operator": operator_name,
        "value": value,
    }


def _convert_conditions_tree_to_legacy(input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if "conditions" not in input_values or "filter_conditions" in input_values:
        return input_values, False

    raw_tree = _unwrap_const_wrapper(input_values.get("conditions"))

    legacy_logic = "AND"
    legacy_conditions: list[dict[str, Any]] = []

    if _is_true_condition(raw_tree):
        legacy_conditions = []
        legacy_logic = "AND"

    elif isinstance(raw_tree, dict) and raw_tree.get("kind") in {"and", "or"}:
        legacy_logic = "OR" if raw_tree.get("kind") == "or" else "AND"
        raw_children = raw_tree.get("conditions")
        if isinstance(raw_children, list):
            for raw_child in raw_children:
                legacy_child = _tree_condition_to_legacy(raw_child)
                if legacy_child is not None:
                    legacy_conditions.append(legacy_child)

    elif isinstance(raw_tree, dict) and raw_tree.get("kind") == "condition":
        legacy_condition = _tree_condition_to_legacy(raw_tree)
        if legacy_condition is not None:
            legacy_conditions = [legacy_condition]

    updated_input_values = dict(input_values)
    updated_input_values.pop("conditions", None)
    updated_input_values["filter_conditions"] = _wrap_const_wrapper(legacy_conditions)
    updated_input_values["logic"] = _wrap_const_wrapper(legacy_logic)

    return updated_input_values, True


def _load_target_rows(bind: sa.Connection) -> list[dict[str, Any]]:
    result = bind.execute(
        sa.text(
            """
            SELECT id, input_values
            FROM graph_nodes
            WHERE lower(name) = :node_name
              AND input_values IS NOT NULL
            """
        ),
        {"node_name": FILTER_NODE_NAME},
    )
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


def upgrade() -> None:
    bind = op.get_bind()
    rows = _load_target_rows(bind)

    updates: list[dict[str, Any]] = []
    for row in rows:
        input_values = _deserialize_input_values(row["input_values"])
        if input_values is None:
            continue

        converted, changed = _convert_legacy_filter_inputs(input_values)
        if not changed:
            continue

        updates.append({"row_id": row["id"], "row_input_values": converted})

    _persist_updates(bind, updates)


def downgrade() -> None:
    bind = op.get_bind()
    rows = _load_target_rows(bind)

    updates: list[dict[str, Any]] = []
    for row in rows:
        input_values = _deserialize_input_values(row["input_values"])
        if input_values is None:
            continue

        converted, changed = _convert_conditions_tree_to_legacy(input_values)
        if not changed:
            continue

        updates.append({"row_id": row["id"], "row_input_values": converted})

    _persist_updates(bind, updates)
