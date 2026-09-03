"""Remove filename input from save file nodes.

Revision ID: 0049
Revises: 0048
Create Date: 2026-05-15 19:00:00.000000
"""

from __future__ import annotations

import json
import posixpath as ppath
import re
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0049"
down_revision: Union[str, Sequence[str], None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SAVE_CSV = "SaveCSV"
SAVE_EXCEL = "SaveExcel"
SAVE_PARQUET = "SaveParquet"
TARGET_NODE_EXTENSIONS = {
    SAVE_CSV: ".csv",
    SAVE_EXCEL: ".xlsx",
    SAVE_PARQUET: ".parquet",
}
PARQUET_DEFAULT_FILENAME = "data"
UNSUPPORTED_TARGET_HANDLES = ("input-path", "input-filename")
_SINGLE_EXPR_RE = re.compile(r"^\{\{\s*(.+?)\s*\}\}$", re.DOTALL)

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


def _payload_marker(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    return payload.get("__dvt_type") or payload.get("dvt_type")


def _is_link_payload(payload: Any) -> bool:
    return _payload_marker(payload) == "link"


def _make_const(value: Any) -> dict[str, Any]:
    return {"__dvt_type": "const", "value": value}


def _make_template_expr(value: str) -> dict[str, Any]:
    return {"__dvt_type": "expr", "value": value, "expression_kind": "template"}


def _normalize_file_name(file_name: str, extension: str) -> str:
    candidate = (file_name or "").strip().strip("/")
    if not candidate:
        raise ValueError("path must include a file or dataset name")

    stem = candidate
    lowered_extension = extension.lower()
    while stem.lower().endswith(lowered_extension):
        stem = stem[:-len(extension)]
        if not stem:
            raise ValueError(f"path cannot consist only of '{extension}'")

    return f"{stem}{extension}"


def _normalize_relative_target_path(path: str, extension: str) -> str:
    raw_path = (path or "").strip().strip("/")
    if not raw_path:
        raise ValueError("path cannot be empty")

    parent_dir, file_name = ppath.split(raw_path)
    if not file_name:
        raise ValueError("path must include a file or dataset name")

    normalized_file_name = _normalize_file_name(file_name, extension)
    return ppath.join(parent_dir, normalized_file_name) if parent_dir else normalized_file_name


def _payload_to_string(payload: Any) -> str:
    marker = _payload_marker(payload)
    if marker != "const":
        raise ValueError(f"Expected const payload, got {marker!r}")
    return "" if payload.get("value") is None else str(payload.get("value"))


def _payload_to_template_segment(payload: Any) -> str:
    marker = _payload_marker(payload)
    if marker == "const":
        return _payload_to_string(payload)

    if marker != "expr":
        raise ValueError(f"Unsupported payload marker {marker!r} for path migration")

    expression_value = payload.get("value")
    expression_kind = payload.get("expression_kind")
    if not isinstance(expression_value, str):
        raise ValueError("Expression payload value must be string")

    if expression_kind == "single":
        return f"{{{{ {expression_value} }}}}"
    if expression_kind == "template":
        return expression_value

    raise ValueError(f"Unsupported expression kind {expression_kind!r}")


def _strip_segment_slashes(segment: str) -> str:
    return segment.strip().strip("/")


def _build_template_target_path(
    *,
    path_segment: str,
    filename_segment: str,
    extension: str,
) -> str:
    clean_path = _strip_segment_slashes(path_segment)
    clean_filename = _strip_segment_slashes(filename_segment)
    if not clean_filename:
        raise ValueError("filename cannot be empty")

    target_file_name = f"{clean_filename}{extension}"
    return f"{clean_path}/{target_file_name}" if clean_path else target_file_name


def _convert_to_new_path_payload(
    *,
    node_name: str,
    path_payload: Any,
    filename_payload: Any,
) -> dict[str, Any]:
    extension = TARGET_NODE_EXTENSIONS[node_name]

    if _payload_marker(path_payload) == "const" and _payload_marker(filename_payload) == "const":
        old_path = _payload_to_string(path_payload)
        old_filename = _payload_to_string(filename_payload)
        combined = "/".join(
            part for part in [old_path.strip().strip("/"), old_filename.strip().strip("/")] if part
        )
        return _make_const(_normalize_relative_target_path(combined, extension))

    return _make_template_expr(
        _build_template_target_path(
            path_segment=_payload_to_template_segment(path_payload),
            filename_segment=_payload_to_template_segment(filename_payload),
            extension=extension,
        )
    )


def _normalize_existing_path_payload(*, node_name: str, path_payload: Any) -> tuple[Any, bool]:
    if not isinstance(path_payload, dict):
        return path_payload, False

    if _is_link_payload(path_payload):
        raise ValueError("Linked path input cannot be migrated to the new single-path contract")

    marker = _payload_marker(path_payload)
    if marker == "const":
        normalized = _normalize_relative_target_path(
            _payload_to_string(path_payload),
            TARGET_NODE_EXTENSIONS[node_name],
        )
        if normalized == path_payload.get("value"):
            return path_payload, False
        return _make_const(normalized), True

    return path_payload, False


def _upgrade_input_values(node_name: str, input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    updated = dict(input_values)
    path_payload = updated.get("path")
    filename_payload = updated.get("filename")

    if filename_payload is None:
        if node_name == SAVE_PARQUET:
            filename_payload = _make_const(PARQUET_DEFAULT_FILENAME)
        else:
            normalized_path_payload, changed = _normalize_existing_path_payload(
                node_name=node_name,
                path_payload=path_payload,
            )
            if changed:
                updated["path"] = normalized_path_payload
            return updated, changed

    if path_payload is None:
        path_payload = _make_const("")

    if _is_link_payload(path_payload) or _is_link_payload(filename_payload):
        raise ValueError("Linked path/filename inputs cannot be migrated to the new single-path contract")

    updated["path"] = _convert_to_new_path_payload(
        node_name=node_name,
        path_payload=path_payload,
        filename_payload=filename_payload,
    )
    updated.pop("filename", None)
    return updated, True


def _payload_from_segment(segment: str) -> dict[str, Any]:
    stripped = segment.strip()
    if not stripped:
        return _make_const("")

    single_match = _SINGLE_EXPR_RE.fullmatch(stripped)
    if single_match is not None:
        return {
            "__dvt_type": "expr",
            "value": single_match.group(1).strip(),
            "expression_kind": "single",
        }

    if "{{" in stripped or "{%" in stripped:
        return {
            "__dvt_type": "expr",
            "value": stripped,
            "expression_kind": "template",
        }

    return _make_const(stripped)


def _split_const_target_path(path: str, extension: str) -> tuple[str, str]:
    normalized = _normalize_relative_target_path(path, extension)
    parent_dir, file_name = ppath.split(normalized)
    stem = file_name[:-len(extension)]
    return parent_dir, stem


def _downgrade_path_payload(*, node_name: str, path_payload: Any) -> tuple[Any, Any]:
    extension = TARGET_NODE_EXTENSIONS[node_name]
    marker = _payload_marker(path_payload)

    if marker == "const":
        path_value, filename_value = _split_const_target_path(_payload_to_string(path_payload), extension)
        return _make_const(path_value), _make_const(filename_value)

    if marker != "expr":
        raise ValueError(f"Unsupported payload marker {marker!r} for downgrade")

    expression_value = path_payload.get("value")
    expression_kind = path_payload.get("expression_kind")
    if expression_kind != "template" or not isinstance(expression_value, str):
        raise ValueError("Only template path expressions generated by the upgrade migration can be downgraded")

    if not expression_value.endswith(extension):
        raise ValueError(f"Upgraded path expression must end with '{extension}'")

    raw_without_extension = expression_value[:-len(extension)]
    path_segment, _, filename_segment = raw_without_extension.rpartition("/")
    if not filename_segment:
        filename_segment = path_segment
        path_segment = ""

    return _payload_from_segment(path_segment), _payload_from_segment(filename_segment)


def _downgrade_input_values(node_name: str, input_values: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    updated = dict(input_values)
    path_payload = updated.get("path")
    if path_payload is None:
        return updated, False

    legacy_path_payload, legacy_filename_payload = _downgrade_path_payload(
        node_name=node_name,
        path_payload=path_payload,
    )
    updated["path"] = legacy_path_payload
    updated["filename"] = legacy_filename_payload
    return updated, True


def _load_target_rows(bind: sa.Connection) -> list[dict[str, Any]]:
    statement = (
        sa.select(
            graph_nodes_table.c.id,
            graph_nodes_table.c.name,
            graph_nodes_table.c.input_values,
        )
        .where(sa.func.lower(graph_nodes_table.c.name).in_(tuple(name.lower() for name in TARGET_NODE_EXTENSIONS)))
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


def _ensure_no_unsupported_edges(bind: sa.Connection) -> None:
    statement = (
        sa.select(
            graph_edges_table.c.id,
            graph_edges_table.c.target_handle,
            graph_nodes_table.c.id.label("node_id"),
            graph_nodes_table.c.name.label("node_name"),
        )
        .select_from(
            graph_edges_table.join(graph_nodes_table, graph_edges_table.c.target == graph_nodes_table.c.ui_id)
        )
        .where(sa.func.lower(graph_nodes_table.c.name).in_(tuple(name.lower() for name in TARGET_NODE_EXTENSIONS)))
        .where(graph_edges_table.c.target_handle.in_(UNSUPPORTED_TARGET_HANDLES))
    )
    rows = list(bind.execute(statement).mappings())
    if not rows:
        return

    formatted = ", ".join(
        f"{row['node_name']}:{row['node_id']}->{row['target_handle']}"
        for row in rows[:5]
    )
    raise RuntimeError(
        "Cannot migrate save-file nodes with linked 'path' or 'filename' inputs. "
        f"Found edges: {formatted}"
    )


def upgrade() -> None:
    bind = op.get_bind()
    _ensure_no_unsupported_edges(bind)
    rows = _load_target_rows(bind)

    updates: list[dict[str, Any]] = []
    for row in rows:
        parsed_input_values = _deserialize_input_values(row["input_values"])
        if parsed_input_values is None:
            continue

        converted_input_values, changed = _upgrade_input_values(row["name"], parsed_input_values)
        if not changed:
            continue

        updates.append(
            {
                "row_id": row["id"],
                "row_input_values": converted_input_values,
            }
        )

    _persist_updates(bind, updates)


def downgrade() -> None:
    bind = op.get_bind()
    rows = _load_target_rows(bind)

    updates: list[dict[str, Any]] = []
    for row in rows:
        parsed_input_values = _deserialize_input_values(row["input_values"])
        if parsed_input_values is None:
            continue

        converted_input_values, changed = _downgrade_input_values(row["name"], parsed_input_values)
        if not changed:
            continue

        updates.append(
            {
                "row_id": row["id"],
                "row_input_values": converted_input_values,
            }
        )

    _persist_updates(bind, updates)
