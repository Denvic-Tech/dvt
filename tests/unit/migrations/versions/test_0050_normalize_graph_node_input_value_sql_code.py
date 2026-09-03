from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0050_normalize_graph_node_input_value_sql_code.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0050", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0050")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_input_values_renames_legacy_sql_input() -> None:
    migration = _load_module()

    converted, changed = migration._upgrade_input_values(
        migration.READ_QUERY_FROM_DB_V3,
        {
            "query": {"__dvt_type": "const", "value": "SELECT 1"},
            "limit": {"__dvt_type": "const", "value": 10},
        },
    )

    assert changed is True
    assert converted == {
        "sql_code": {"__dvt_type": "const", "value": "SELECT 1"},
        "limit": {"__dvt_type": "const", "value": 10},
    }


def test_upgrade_input_values_drops_legacy_alias_when_sql_code_already_exists() -> None:
    migration = _load_module()

    converted, changed = migration._upgrade_input_values(
        migration.EXECUTE_SQL,
        {
            "sql": {"__dvt_type": "const", "value": "SELECT old"},
            "sql_code": {"__dvt_type": "const", "value": "SELECT new"},
        },
    )

    assert changed is True
    assert converted == {
        "sql_code": {"__dvt_type": "const", "value": "SELECT new"},
    }


def test_downgrade_input_values_restores_node_specific_legacy_key() -> None:
    migration = _load_module()

    converted, changed = migration._downgrade_input_values(
        migration.READ_VARIABLES_FROM_DB,
        {
            "sql_code": {"__dvt_type": "expr", "value": "query_text", "expression_kind": "single"},
            "mode": {"__dvt_type": "const", "value": "sql"},
        },
    )

    assert changed is True
    assert converted == {
        "sql_query": {"__dvt_type": "expr", "value": "query_text", "expression_kind": "single"},
        "mode": {"__dvt_type": "const", "value": "sql"},
    }


def test_rename_edge_handle_uses_node_specific_mapping() -> None:
    migration = _load_module()

    assert (
        migration._rename_edge_handle(
            migration.READ_QUERY_FROM_DB_V3,
            "input-query",
            upgrade=True,
        )
        == "input-sql_code"
    )
    assert (
        migration._rename_edge_handle(
            migration.READ_VARIABLES_FROM_DB,
            "input-sql_code",
            upgrade=False,
        )
        == "input-sql_query"
    )


def test_upgrade_persists_node_and_edge_updates(monkeypatch) -> None:
    migration = _load_module()
    rows = [
        {
            "id": "node-1",
            "name": migration.EXECUTE_SQL,
            "input_values": {
                "sql": {"__dvt_type": "const", "value": "DELETE FROM test"},
            },
        },
        {
            "id": "node-2",
            "name": migration.EXECUTE_SQL,
            "input_values": "{invalid_json}",
        },
    ]
    edges = [
        {
            "id": "edge-1",
            "node_name": migration.EXECUTE_SQL,
            "target_handle": "input-sql",
        }
    ]

    captured: dict[str, Any] = {"input_updates": None, "edge_updates": None}

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration, "_load_target_rows", lambda bind: rows)
    monkeypatch.setattr(migration, "_load_target_edges", lambda bind, upgrade: edges)
    monkeypatch.setattr(
        migration,
        "_persist_input_updates",
        lambda bind, updates: captured.update(input_updates=updates),
    )
    monkeypatch.setattr(
        migration,
        "_persist_edge_updates",
        lambda bind, updates: captured.update(edge_updates=updates),
    )

    migration.upgrade()

    assert captured["input_updates"] == [
        {
            "row_id": "node-1",
            "row_input_values": {
                "sql_code": {"__dvt_type": "const", "value": "DELETE FROM test"},
            },
        }
    ]
    assert captured["edge_updates"] == [
        {
            "row_id": "edge-1",
            "row_target_handle": "input-sql_code",
        }
    ]
