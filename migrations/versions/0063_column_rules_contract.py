"""Move saved single-column transforms to rule/binding contracts without data execution.

Revision ID: 0063
Revises: 0062

Old ports are retained for expression/link bindings and rollback. This file deliberately
freezes the conversion instead of importing the current node registry.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy

import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None

LOG = logging.getLogger("alembic.runtime.migration")
MARKER = "__column_rules_migration_0063"
CONTRACT_FIELDS = ("column_rules", "calculated_columns", "column_bindings")
NODES = {
    "dataframereplacevalues": ("column_to_replace", {"legacy_dictionary": ("dictionary", None)}),
    "dataframeregexreplace": (
        "column_to_replace",
        {
            "pattern": ("pattern", None),
            "replacement": ("replacement", ""),
        },
    ),
    "dataframesettimezone": ("column", {"timezone": ("timezone", "Europe/Moscow")}),
    "dataframeconverttoperiodstart": ("column", {"period": ("period", "month")}),
    "addtimedeltatodataframe": (
        "column_with_time",
        {unit: (unit, 0.0) for unit in ("years", "months", "days", "hours", "minutes", "seconds")},
    ),
    "dataframesplitcolumn": (
        "column",
        {
            "delimiter": ("delimiter", None),
            "max_splits": ("max_splits", 1),
            "drop_source": ("drop_source", False),
        },
    ),
    "dataframeaddcolumnbyexpression": None,
    "setcolumntodataframe": None,
}
nodes = sa.table(
    "graph_nodes",
    sa.column("id", sa.String),
    sa.column("name", sa.String),
    sa.column("ui_id", sa.String),
    sa.column("project_id", sa.String),
    sa.column("input_values", sa.JSON),
)
edges = sa.table(
    "graph_edges",
    sa.column("target", sa.String),
    sa.column("project_id", sa.String),
    sa.column("target_handle", sa.String),
)


def const(value):
    return {"__dvt_type": "const", "value": value}


def unwrap(value):
    if isinstance(value, dict) and value.get("__dvt_type") == "const":
        return value.get("value")
    return value


def deserialize(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def upgrade_inputs(name, raw, connected_inputs=()):
    name = name.lower()
    if name not in NODES:
        return raw, False
    values = deserialize(raw)
    if MARKER in values:
        return raw, False
    # Respect an already configured new contract, including an explicitly empty list.
    if any(field in values and unwrap(values[field]) is not None for field in CONTRACT_FIELDS):
        return raw, False
    bindings = {}

    def read(field, default, path):
        original = values.get(field, const(default))
        if field in connected_inputs or (
            isinstance(original, dict) and original.get("__dvt_type") in {"expr", "link"}
        ):
            bindings[path] = field
            # Placeholder only: runtime resolves the retained port before validating a rule.
            return default
        return deepcopy(unwrap(original))

    if name == "dataframeaddcolumnbyexpression":
        entry = {
            "name": read("column_name", None, "name"),
            "expression": read("expression", None, "expression"),
            "overwrite_existing": True,
            "input_bindings": bindings,
        }
        generated = {"calculated_columns": const([entry])}
    elif name == "setcolumntodataframe":
        entry = {
            # A Series name is runtime metadata, never infer it from a node's display name.
            "source": None,
            "target": read("column_name", None, "target"),
            "input_bindings": bindings,
        }
        generated = {"column_bindings": const([entry]), "overwrite_existing": const(True)}
    else:
        source_field, parameters = NODES[name]
        source = read(source_field, None, "selector.tokens.0.value")
        params = {
            key: read(field, default, "params." + key)
            for key, (field, default) in parameters.items()
        }
        if name == "dataframereplacevalues":
            dictionary = params["legacy_dictionary"]
            params["pairs"] = (
                [{"old": key, "new": value} for key, value in dictionary.items()]
                if isinstance(dictionary, dict)
                else []
            )
        output = {"mode": "replace"}
        if name in {"dataframeconverttoperiodstart", "addtimedeltatodataframe"}:
            field = (
                "new_column" if name == "dataframeconverttoperiodstart" else "new_column_with_time"
            )
            target = read(field, None, "output.target")
            output = {
                "mode": "new",
                "target": target,
                "fallback_to_source": name == "dataframeconverttoperiodstart",
                "require_target": name == "addtimedeltatodataframe",
            }
        generated = {
            "column_rules": const(
                [
                    {
                        "id": "migrated-v1",
                        "enabled": True,
                        "selector": {"tokens": [{"kind": "name", "value": source}]},
                        "params": params,
                        "output": output,
                        "compatibility": "v1",
                        "input_bindings": bindings,
                    }
                ]
            )
        }

    updated = deepcopy(values)
    backup = {
        "generated": deepcopy(generated),
        "previous": {field: deepcopy(values[field]) for field in generated if field in values},
    }
    if not isinstance(raw, dict):
        backup["original_raw"] = raw
    updated.update(generated)
    updated[MARKER] = const(backup)
    return updated, True


def downgrade_inputs(name, raw):
    if name.lower() not in NODES:
        return raw, False
    values = deserialize(raw)
    backup = unwrap(values.get(MARKER))
    if not isinstance(backup, dict) or not isinstance(backup.get("generated"), dict):
        return raw, False
    # Preserve edits made with the new UI. The previous application ignores new inputs
    # and uses the retained old ports; re-upgrade must not overwrite the edited rules.
    if any(values.get(field) != value for field, value in backup["generated"].items()):
        return raw, False
    updated = deepcopy(values)
    for field in backup["generated"]:
        updated.pop(field, None)
    updated.update(backup.get("previous", {}))
    updated.pop(MARKER, None)
    if "original_raw" in backup and updated == deserialize(backup["original_raw"]):
        return backup["original_raw"], True
    return updated, True


def _migrate(*, reverse=False):
    bind = op.get_bind()
    last_id = None
    while True:
        query = sa.select(nodes).where(sa.func.lower(nodes.c.name).in_(tuple(NODES)))
        if last_id is not None:
            query = query.where(nodes.c.id > last_id)
        rows = bind.execute(query.order_by(nodes.c.id).limit(500)).mappings().all()
        if not rows:
            break
        connected = {}
        if not reverse:
            links = bind.execute(
                sa.select(edges.c.project_id, edges.c.target, edges.c.target_handle)
                .join(
                    nodes,
                    sa.and_(
                        nodes.c.ui_id == edges.c.target, nodes.c.project_id == edges.c.project_id
                    ),
                )
                .where(nodes.c.id.in_([row["id"] for row in rows]))
            ).mappings()
            for link in links:
                handle = link["target_handle"] or ""
                if handle.startswith("input-"):
                    connected.setdefault((link["project_id"], link["target"]), set()).add(
                        handle[6:]
                    )
        updates = []
        for row in rows:
            raw = row["input_values"]
            if reverse:
                converted, changed = downgrade_inputs(row["name"], raw)
            else:
                converted, changed = upgrade_inputs(
                    row["name"], raw, connected.get((row["project_id"], row["ui_id"]), ())
                )
                if raw is not None and not deserialize(raw) and raw != {}:
                    LOG.warning(
                        "Preserved malformed legacy input payload for graph node %s", row["id"]
                    )
            if changed:
                updates.append({"row_id": row["id"], "payload": converted})
        if updates:
            bind.execute(
                sa.update(nodes)
                .where(nodes.c.id == sa.bindparam("row_id"))
                .values(input_values=sa.bindparam("payload")),
                updates,
            )
        last_id = rows[-1]["id"]


def upgrade():
    _migrate()


def downgrade():
    _migrate(reverse=True)
