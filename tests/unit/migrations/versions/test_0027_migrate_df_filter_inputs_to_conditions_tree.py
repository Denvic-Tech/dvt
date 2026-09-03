from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0027_migrate_df_filter_inputs_to_conditions_tree.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0027", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0027")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_conversion_builds_conditions_tree() -> None:
    migration = _load_module()

    legacy_inputs = {
        "dataframe": {"__dvt_type": "link", "node_id": "n1", "output_name": "output"},
        "filter_conditions": {
            "__dvt_type": "const",
            "value": [
                {"column": "age", "operator": ">", "value": 30},
                {"column": "deleted_at", "operator": "==", "value": None},
            ],
        },
        "logic": {"__dvt_type": "const", "value": "OR"},
    }

    converted, changed = migration._convert_legacy_filter_inputs(legacy_inputs)

    assert changed is True
    assert "filter_conditions" not in converted
    assert "logic" not in converted

    conditions_wrapper = converted["conditions"]
    assert conditions_wrapper["__dvt_type"] == "const"

    tree = conditions_wrapper["value"]
    assert tree["kind"] == "or"
    assert len(tree["conditions"]) == 2
    assert tree["conditions"][0]["left"] == {"type": "column", "column": "age"}
    assert tree["conditions"][1]["right"]["value"] == migration.NULL_VALUE


def test_downgrade_conversion_restores_legacy_inputs() -> None:
    migration = _load_module()

    upgraded_inputs = {
        "dataframe": {"__dvt_type": "link", "node_id": "n1", "output_name": "output"},
        "conditions": {
            "__dvt_type": "const",
            "value": {
                "kind": "and",
                "conditions": [
                    {
                        "kind": "condition",
                        "left": {"type": "column", "column": "name"},
                        "operator": "==",
                        "right": {"type": "literal", "value": "Alice"},
                    },
                    {
                        "kind": "condition",
                        "left": {"type": "column", "column": "deleted_at"},
                        "operator": "==",
                        "right": {"type": "literal", "value": migration.NULL_VALUE},
                    },
                ],
            },
        },
    }

    converted, changed = migration._convert_conditions_tree_to_legacy(upgraded_inputs)

    assert changed is True
    assert "conditions" not in converted
    assert converted["logic"] == {"__dvt_type": "const", "value": "AND"}

    legacy_conditions = converted["filter_conditions"]["value"]
    assert len(legacy_conditions) == 2
    assert legacy_conditions[0] == {"column": "name", "operator": "==", "value": "Alice"}
    assert legacy_conditions[1] == {"column": "deleted_at", "operator": "==", "value": None}


def test_empty_legacy_filters_roundtrip_to_true_condition_and_back() -> None:
    migration = _load_module()

    legacy_inputs = {
        "filter_conditions": {"__dvt_type": "const", "value": []},
        "logic": {"__dvt_type": "const", "value": "AND"},
    }

    upgraded, changed_up = migration._convert_legacy_filter_inputs(legacy_inputs)
    assert changed_up is True
    assert migration._is_true_condition(upgraded["conditions"]["value"]) is True

    downgraded, changed_down = migration._convert_conditions_tree_to_legacy(upgraded)
    assert changed_down is True
    assert downgraded["filter_conditions"] == {"__dvt_type": "const", "value": []}
    assert downgraded["logic"] == {"__dvt_type": "const", "value": "AND"}
