from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import sqlalchemy as sa


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0045_normalize_variable_io_and_input_payloads.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0043", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0045")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rewrite_input_values_upgrade_renames_key_and_normalizes_var_payloads() -> None:
    migration = _load_module()

    converted, changed = migration._rewrite_input_values(
        {
            "variables": {
                "__dvt_type": "link",
                "node_id": "source",
                "output_name": "variable",
            },
            "value_in": {"__dvt_type": "var", "name": "message"},
            "sql": {
                "__dvt_type": "var",
                "var_type": "system",
                "mode": "expr",
                "expression": "SELECT * FROM {{ input_variables.target_table }}",
                "expression_kind": "template",
            },
        },
        source_key="variables",
        target_key="input_variables",
        upgrade=True,
    )

    assert changed is True
    assert "variables" not in converted
    assert converted["input_variables"] == {
        "__dvt_type": "link",
        "node_id": "source",
        "output_name": "variable",
    }
    assert converted["value_in"] == {
        "__dvt_type": "expr",
        "value": "message",
        "expression_kind": "single",
    }
    assert converted["sql"] == {
        "__dvt_type": "expr",
        "value": "SELECT * FROM {{ input_variables.target_table }}",
        "expression_kind": "template",
    }


def test_rewrite_input_values_upgrade_uses_explicit_reference_for_unsafe_name() -> None:
    migration = _load_module()

    converted, changed = migration._rewrite_input_values(
        {
            "value_in": {"__dvt_type": "var", "name": "target-table"},
        },
        source_key="variables",
        target_key="input_variables",
        upgrade=True,
    )

    assert changed is True
    assert converted["value_in"] == {
        "__dvt_type": "expr",
        "value": 'input_variables["target-table"]',
        "expression_kind": "single",
    }


def test_rewrite_input_values_downgrade_restores_var_payloads() -> None:
    migration = _load_module()

    converted, changed = migration._rewrite_input_values(
        {
            "input_variables": {
                "__dvt_type": "link",
                "node_id": "source",
                "output_name": "output_variables",
            },
            "value_in": {
                "__dvt_type": "expr",
                "value": "target_table",
                "expression_kind": "single",
            },
            "sql": {
                "__dvt_type": "expr",
                "value": "SELECT * FROM {{ input_variables.target_table }}",
                "expression_kind": "template",
            },
        },
        source_key="input_variables",
        target_key="variables",
        upgrade=False,
    )

    assert changed is True
    assert "input_variables" not in converted
    assert converted["variables"] == {
        "__dvt_type": "link",
        "node_id": "source",
        "output_name": "output_variables",
    }
    assert converted["value_in"] == {
        "__dvt_type": "var",
        "name": "target_table",
    }
    assert converted["sql"] == {
        "__dvt_type": "var",
        "mode": "expr",
        "expression": "SELECT * FROM {{ input_variables.target_table }}",
        "expression_kind": "template",
    }


def test_rewrite_input_values_upgrade_normalizes_nested_value_input_payloads() -> None:
    migration = _load_module()

    converted, changed = migration._rewrite_input_values(
        {
            "defined_variables": {
                "nested": {
                    "type": "STRING",
                    "value_input": {
                        "__dvt_type": "var",
                        "var_type": "user",
                        "mode": "expr",
                        "expression": "base + 1",
                        "expression_kind": "single",
                    },
                }
            },
        },
        source_key="variables",
        target_key="input_variables",
        upgrade=True,
    )

    assert changed is True
    assert converted["defined_variables"]["nested"]["value_input"] == {
        "__dvt_type": "expr",
        "value": "base + 1",
        "expression_kind": "single",
    }


def test_upgrade_updates_rows_and_invokes_all_schema_changes(monkeypatch) -> None:
    migration = _load_module()
    rows = [
        {
            "id": "n1",
            "input_values": {
                "variables": {
                    "__dvt_type": "link",
                    "node_id": "source",
                    "output_name": "variable",
                },
                "value_in": {"__dvt_type": "const", "value": "hello"},
            },
        },
        {
            "id": "n2",
            "input_values": {
                "value_in": {"__dvt_type": "var", "name": "message"},
                "sql": {
                    "__dvt_type": "var",
                    "mode": "expr",
                    "expression": "SELECT * FROM {{ input_variables.target_table }}",
                    "expression_kind": "template",
                    "var_type": "system",
                },
            },
        },
    ]

    captured: dict[str, Any] = {
        "updates": None,
        "add_column": None,
        "target_handle_rename": None,
        "source_handle_rename": None,
    }

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration,
        "_load_target_rows",
        lambda bind, source_key, upgrade: rows,
    )
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table_name, column: captured.update(add_column=(table_name, column)),
    )
    monkeypatch.setattr(
        migration,
        "_rename_graph_edge_target_handle",
        lambda **kwargs: captured.update(target_handle_rename=kwargs),
    )
    monkeypatch.setattr(
        migration,
        "_rename_graph_edge_source_handle",
        lambda **kwargs: captured.update(source_handle_rename=kwargs),
    )

    def _capture_updates(bind, updates):
        captured["updates"] = updates

    monkeypatch.setattr(migration, "_persist_updates", _capture_updates)

    migration.upgrade()

    table_name, column = captured["add_column"]
    assert table_name == "graph_nodes"
    assert isinstance(column, sa.Column)
    assert column.name == "show_variables_io"

    assert captured["target_handle_rename"] == {
        "source_handle": "input-variables",
        "target_handle": "input-input_variables",
    }
    assert captured["source_handle_rename"] == {
        "source_handle": "output-variable",
        "target_handle": "output-output_variables",
    }
    assert captured["updates"] == [
        {
            "row_id": "n1",
            "row_input_values": {
                "input_variables": {
                    "__dvt_type": "link",
                    "node_id": "source",
                    "output_name": "variable",
                },
                "value_in": {"__dvt_type": "const", "value": "hello"},
            },
        },
        {
            "row_id": "n2",
            "row_input_values": {
                "value_in": {
                    "__dvt_type": "expr",
                    "value": "message",
                    "expression_kind": "single",
                },
                "sql": {
                    "__dvt_type": "expr",
                    "value": "SELECT * FROM {{ input_variables.target_table }}",
                    "expression_kind": "template",
                },
            },
        },
    ]


def test_downgrade_restores_legacy_state(monkeypatch) -> None:
    migration = _load_module()
    rows = [
        {
            "id": "n1",
            "input_values": {
                "input_variables": {
                    "__dvt_type": "link",
                    "node_id": "source",
                    "output_name": "output_variables",
                },
                "value_in": {
                    "__dvt_type": "expr",
                    "value": "target_table",
                    "expression_kind": "single",
                },
                "unsafe": {
                    "__dvt_type": "expr",
                    "value": 'input_variables["target-table"]',
                    "expression_kind": "single",
                },
                "sql": {
                    "__dvt_type": "expr",
                    "value": "SELECT * FROM {{ input_variables.target_table }}",
                    "expression_kind": "template",
                },
            },
        },
    ]

    captured: dict[str, Any] = {
        "updates": None,
        "drop_column": None,
        "target_handle_rename": None,
        "source_handle_rename": None,
    }

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration,
        "_load_target_rows",
        lambda bind, source_key, upgrade: rows,
    )
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table_name, column_name: captured.update(drop_column=(table_name, column_name)),
    )
    monkeypatch.setattr(
        migration,
        "_rename_graph_edge_target_handle",
        lambda **kwargs: captured.update(target_handle_rename=kwargs),
    )
    monkeypatch.setattr(
        migration,
        "_rename_graph_edge_source_handle",
        lambda **kwargs: captured.update(source_handle_rename=kwargs),
    )

    def _capture_updates(bind, updates):
        captured["updates"] = updates

    monkeypatch.setattr(migration, "_persist_updates", _capture_updates)

    migration.downgrade()

    assert captured["target_handle_rename"] == {
        "source_handle": "input-input_variables",
        "target_handle": "input-variables",
    }
    assert captured["source_handle_rename"] == {
        "source_handle": "output-output_variables",
        "target_handle": "output-variable",
    }
    assert captured["drop_column"] == ("graph_nodes", "show_variables_io")
    assert captured["updates"] == [
        {
            "row_id": "n1",
            "row_input_values": {
                "variables": {
                    "__dvt_type": "link",
                    "node_id": "source",
                    "output_name": "output_variables",
                },
                "value_in": {"__dvt_type": "var", "name": "target_table"},
                "unsafe": {"__dvt_type": "var", "name": "target-table"},
                "sql": {
                    "__dvt_type": "var",
                    "mode": "expr",
                    "expression": "SELECT * FROM {{ input_variables.target_table }}",
                    "expression_kind": "template",
                },
            },
        },
    ]
