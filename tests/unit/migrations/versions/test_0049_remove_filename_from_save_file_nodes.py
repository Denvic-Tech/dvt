from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0049_remove_filename_from_save_file_nodes.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0049", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0049")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_input_values_merges_const_csv_path_and_filename() -> None:
    migration = _load_module()

    converted, changed = migration._upgrade_input_values(
        migration.SAVE_CSV,
        {
            "path": {"__dvt_type": "const", "value": "reports"},
            "filename": {"__dvt_type": "const", "value": "export.csv"},
        },
    )

    assert changed is True
    assert converted == {
        "path": {"__dvt_type": "const", "value": "reports/export.csv"},
    }


def test_upgrade_input_values_merges_single_expr_filename_into_template_path() -> None:
    migration = _load_module()

    converted, changed = migration._upgrade_input_values(
        migration.SAVE_EXCEL,
        {
            "path": {"__dvt_type": "const", "value": "reports"},
            "filename": {"__dvt_type": "expr", "value": "file_name", "expression_kind": "single"},
        },
    )

    assert changed is True
    assert converted == {
        "path": {
            "__dvt_type": "expr",
            "value": "reports/{{ file_name }}.xlsx",
            "expression_kind": "template",
        },
    }


def test_upgrade_input_values_merges_template_expr_path_into_template_path() -> None:
    migration = _load_module()

    converted, changed = migration._upgrade_input_values(
        migration.SAVE_PARQUET,
        {
            "path": {"__dvt_type": "expr", "value": "reports/{{ month }}", "expression_kind": "template"},
            "filename": {"__dvt_type": "const", "value": "dataset"},
        },
    )

    assert changed is True
    assert converted == {
        "path": {
            "__dvt_type": "expr",
            "value": "reports/{{ month }}/dataset.parquet",
            "expression_kind": "template",
        },
    }


def test_upgrade_input_values_uses_default_parquet_filename_when_missing() -> None:
    migration = _load_module()

    converted, changed = migration._upgrade_input_values(
        migration.SAVE_PARQUET,
        {
            "path": {"__dvt_type": "const", "value": "reports"},
        },
    )

    assert changed is True
    assert converted == {
        "path": {"__dvt_type": "const", "value": "reports/data.parquet"},
    }


def test_upgrade_input_values_rejects_link_payloads() -> None:
    migration = _load_module()

    with pytest.raises(ValueError, match="Linked path/filename inputs"):
        migration._upgrade_input_values(
            migration.SAVE_CSV,
            {
                "path": {"__dvt_type": "link", "node_id": "path-source", "output_name": "output"},
                "filename": {"__dvt_type": "const", "value": "export"},
            },
        )


def test_downgrade_input_values_splits_const_path_back_to_legacy_fields() -> None:
    migration = _load_module()

    converted, changed = migration._downgrade_input_values(
        migration.SAVE_CSV,
        {
            "path": {"__dvt_type": "const", "value": "reports/export.csv"},
        },
    )

    assert changed is True
    assert converted == {
        "path": {"__dvt_type": "const", "value": "reports"},
        "filename": {"__dvt_type": "const", "value": "export"},
    }


def test_downgrade_input_values_restores_expression_fields() -> None:
    migration = _load_module()

    converted, changed = migration._downgrade_input_values(
        migration.SAVE_EXCEL,
        {
            "path": {
                "__dvt_type": "expr",
                "value": "reports/{{ file_name }}.xlsx",
                "expression_kind": "template",
            },
        },
    )

    assert changed is True
    assert converted == {
        "path": {"__dvt_type": "const", "value": "reports"},
        "filename": {"__dvt_type": "expr", "value": "file_name", "expression_kind": "single"},
    }


def test_upgrade_blocks_unsupported_edges(monkeypatch) -> None:
    migration = _load_module()
    rows = [
        {
            "id": "edge-1",
            "target_handle": "input-filename",
            "node_id": "node-1",
            "node_name": migration.SAVE_CSV,
        }
    ]

    class _FakeResult:
        def mappings(self) -> list[dict[str, Any]]:
            return rows

    class _FakeBind:
        def execute(self, statement):
            return _FakeResult()

    with pytest.raises(RuntimeError, match="linked 'path' or 'filename' inputs"):
        migration._ensure_no_unsupported_edges(_FakeBind())
