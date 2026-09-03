from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0060_save_parquet_compatibility_mode.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0060", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0060")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adds_legacy_without_touching_other_inputs() -> None:
    migration = _load_module()
    original = {
        "path": {"__dvt_type": "const", "value": "reports/orders.parquet"},
        "row_cap": {"__dvt_type": "const", "value": 1000},
        "mode": {"__dvt_type": "const", "value": "append"},
    }

    converted, changed = migration._upgrade_input_values(original)

    assert changed is True
    assert converted == {
        **original,
        "compatibility_mode": {"__dvt_type": "const", "value": "legacy"},
    }
    assert original.get("compatibility_mode") is None


def test_upgrade_is_idempotent_when_field_already_exists() -> None:
    migration = _load_module()
    original = {
        "compatibility_mode": {"__dvt_type": "const", "value": "new"},
        "path": {"__dvt_type": "const", "value": "orders.parquet"},
    }

    converted, changed = migration._upgrade_input_values(original)

    assert changed is False
    assert converted is original


def test_downgrade_removes_only_compatibility_mode() -> None:
    migration = _load_module()
    original = {
        "compatibility_mode": {"__dvt_type": "const", "value": "legacy"},
        "path": {"__dvt_type": "const", "value": "orders.parquet"},
        "partition_on": {"__dvt_type": "const", "value": ["country"]},
    }

    converted, changed = migration._downgrade_input_values(original)

    assert changed is True
    assert converted == {
        "path": original["path"],
        "partition_on": original["partition_on"],
    }
