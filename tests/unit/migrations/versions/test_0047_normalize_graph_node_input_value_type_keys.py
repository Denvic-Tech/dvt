from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0047_normalize_graph_node_input_value_type_keys.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0047", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0047")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rewrite_type_keys_upgrade_normalizes_nested_payloads() -> None:
    migration = _load_module()

    converted, changed = migration._rewrite_type_keys(
        {
            "value_in": {"dvt_type": "const", "value": "hello"},
            "items": [
                {"dvt_type": "link", "node_id": "n1", "output_name": "output"},
                {
                    "__dvt_type": "const",
                    "value": {
                        "nested": {"dvt_type": "expr", "value": "x", "expression_kind": "single"},
                    },
                },
            ],
        },
        upgrade=True,
    )

    assert changed is True
    assert converted == {
        "value_in": {"__dvt_type": "const", "value": "hello"},
        "items": [
            {"__dvt_type": "link", "node_id": "n1", "output_name": "output"},
            {
                "__dvt_type": "const",
                "value": {
                    "nested": {"__dvt_type": "expr", "value": "x", "expression_kind": "single"},
                },
            },
        ],
    }


def test_rewrite_type_keys_upgrade_prefers_existing_canonical_marker() -> None:
    migration = _load_module()

    converted, changed = migration._rewrite_type_keys(
        {
            "value_in": {
                "__dvt_type": "const",
                "dvt_type": "expr",
                "value": "hello",
            }
        },
        upgrade=True,
    )

    assert changed is True
    assert converted == {
        "value_in": {
            "__dvt_type": "const",
            "value": "hello",
        }
    }


def test_rewrite_type_keys_downgrade_restores_legacy_marker_recursively() -> None:
    migration = _load_module()

    converted, changed = migration._rewrite_type_keys(
        {
            "value_in": {"__dvt_type": "const", "value": "hello"},
            "items": [
                {"__dvt_type": "link", "node_id": "n1", "output_name": "output"},
                {"value": {"nested": {"__dvt_type": "expr", "value": "x", "expression_kind": "single"}}},
            ],
        },
        upgrade=False,
    )

    assert changed is True
    assert converted == {
        "value_in": {"dvt_type": "const", "value": "hello"},
        "items": [
            {"dvt_type": "link", "node_id": "n1", "output_name": "output"},
            {"value": {"nested": {"dvt_type": "expr", "value": "x", "expression_kind": "single"}}},
        ],
    }


def test_upgrade_updates_only_rows_that_need_cleanup(monkeypatch) -> None:
    migration = _load_module()
    rows = [
        {
            "id": "n1",
            "input_values": {
                "value_in": {"dvt_type": "const", "value": "hello"},
            },
        },
        {
            "id": "n2",
            "input_values": {
                "value_in": {"__dvt_type": "const", "value": "ready"},
            },
        },
        {
            "id": "n3",
            "input_values": "{invalid_json}",
        },
    ]

    captured: dict[str, Any] = {"updates": None}

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration, "_load_target_rows", lambda bind, upgrade: rows[:1])
    monkeypatch.setattr(
        migration,
        "_persist_updates",
        lambda bind, updates: captured.update(updates=updates),
    )

    migration.upgrade()

    assert captured["updates"] == [
        {
            "row_id": "n1",
            "row_input_values": {
                "value_in": {"__dvt_type": "const", "value": "hello"},
            },
        }
    ]


def test_downgrade_updates_rows_that_have_canonical_marker(monkeypatch) -> None:
    migration = _load_module()
    rows = [
        {
            "id": "n1",
            "input_values": {
                "value_in": {"__dvt_type": "const", "value": "hello"},
                "items": [{"__dvt_type": "link", "node_id": "n1", "output_name": "output"}],
            },
        },
    ]

    captured: dict[str, Any] = {"updates": None}

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration, "_load_target_rows", lambda bind, upgrade: rows)
    monkeypatch.setattr(
        migration,
        "_persist_updates",
        lambda bind, updates: captured.update(updates=updates),
    )

    migration.downgrade()

    assert captured["updates"] == [
        {
            "row_id": "n1",
            "row_input_values": {
                "value_in": {"dvt_type": "const", "value": "hello"},
                "items": [{"dvt_type": "link", "node_id": "n1", "output_name": "output"}],
            },
        }
    ]
