from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


def _load_module():
    module_path = (
        Path(__file__).resolve().parents[4]
        / "migrations"
        / "versions"
        / "0032_migrate_read_from_db_nodes_v2_to_v3.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0032", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load migration module 0032")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_convert_read_table_inputs_to_v3_moves_index_col_when_partition_missing() -> None:
    migration = _load_module()

    input_values = {
        "index_col": {"__dvt_type": "const", "value": "id"},
        "partition_col": {"__dvt_type": "const", "value": None},
        "table_name": {"__dvt_type": "const", "value": "sales"},
    }

    converted, changed = migration._convert_read_table_inputs_to_v3(input_values)

    assert changed is True
    assert "index_col" not in converted
    assert converted["partition_col"] == {"__dvt_type": "const", "value": "id"}


def test_convert_read_table_inputs_to_v3_keeps_existing_partition_col() -> None:
    migration = _load_module()

    input_values = {
        "index_col": {"__dvt_type": "const", "value": "legacy_id"},
        "partition_col": {"__dvt_type": "const", "value": "partition_id"},
    }

    converted, changed = migration._convert_read_table_inputs_to_v3(input_values)

    assert changed is True
    assert "index_col" not in converted
    assert converted["partition_col"] == {"__dvt_type": "const", "value": "partition_id"}


def test_convert_read_table_inputs_to_v3_copies_variable_index_col() -> None:
    migration = _load_module()

    input_values = {
        "index_col": {"__dvt_type": "var", "name": "partition_column_name"},
        "table_name": {"__dvt_type": "const", "value": "sales"},
    }

    converted, changed = migration._convert_read_table_inputs_to_v3(input_values)

    assert changed is True
    assert converted["partition_col"] == {"__dvt_type": "var", "name": "partition_column_name"}
    assert "index_col" not in converted


def test_convert_read_table_inputs_to_v3_no_index_col_no_change() -> None:
    migration = _load_module()

    input_values = {
        "partition_col": {"__dvt_type": "const", "value": "id"},
    }

    converted, changed = migration._convert_read_table_inputs_to_v3(input_values)

    assert changed is False
    assert converted == input_values


def test_convert_read_table_inputs_to_v2_restores_index_col_and_removes_v3_field() -> None:
    migration = _load_module()

    input_values = {
        "partition_col": {"__dvt_type": "const", "value": "id"},
        "max_rows_per_partition": {"__dvt_type": "const", "value": 200000},
    }

    converted, changed = migration._convert_read_table_inputs_to_v2(input_values)

    assert changed is True
    assert converted["index_col"] == {"__dvt_type": "const", "value": "id"}
    assert "max_rows_per_partition" not in converted


def test_convert_read_query_inputs_to_v2_removes_v3_only_fields() -> None:
    migration = _load_module()

    input_values = {
        "query": {"__dvt_type": "const", "value": "SELECT 1"},
        "limit": {"__dvt_type": "const", "value": 100},
        "max_rows_per_partition": {"__dvt_type": "const", "value": 50000},
    }

    converted, changed = migration._convert_read_query_inputs_to_v2(input_values)

    assert changed is True
    assert "limit" not in converted
    assert "max_rows_per_partition" not in converted
    assert converted["query"] == {"__dvt_type": "const", "value": "SELECT 1"}


def test_convert_row_for_upgrade_renames_query_node() -> None:
    migration = _load_module()

    converted_name, converted_display_name, converted_inputs, changed = migration._convert_row_for_upgrade(
        node_name="ReadQueryFromDBV2",
        display_name="Read Query From DB V2",
        raw_input_values={"query": {"__dvt_type": "const", "value": "SELECT 1"}},
    )

    assert changed is True
    assert converted_name == "ReadQueryFromDBV3"
    assert converted_display_name == "Read Query From DB V3"
    assert converted_inputs == {"query": {"__dvt_type": "const", "value": "SELECT 1"}}


def test_convert_row_for_upgrade_does_not_touch_non_standard_display_name() -> None:
    migration = _load_module()

    converted_name, converted_display_name, converted_inputs, changed = migration._convert_row_for_upgrade(
        node_name="ReadQueryFromDBV2",
        display_name="ReadQueryFromDBV2",
        raw_input_values={"query": {"__dvt_type": "const", "value": "SELECT 1"}},
    )

    assert changed is True
    assert converted_name == "ReadQueryFromDBV3"
    assert converted_display_name == "ReadQueryFromDBV2"
    assert converted_inputs == {"query": {"__dvt_type": "const", "value": "SELECT 1"}}


def test_convert_row_for_upgrade_renames_table_with_invalid_json_payload() -> None:
    migration = _load_module()

    converted_name, converted_display_name, converted_inputs, changed = migration._convert_row_for_upgrade(
        node_name="ReadTableFromDBV2",
        display_name="Custom display",
        raw_input_values="{invalid_json}",
    )

    assert changed is True
    assert converted_name == "ReadTableFromDBV3"
    assert converted_display_name == "Custom display"
    assert converted_inputs == "{invalid_json}"


def test_convert_row_for_downgrade_query_removes_limit_and_max_rows() -> None:
    migration = _load_module()

    converted_name, converted_display_name, converted_inputs, changed = migration._convert_row_for_downgrade(
        node_name="ReadQueryFromDBV3",
        display_name="Read Query From DB V3",
        raw_input_values={
            "query": {"__dvt_type": "const", "value": "SELECT 1"},
            "limit": {"__dvt_type": "const", "value": 1000},
            "max_rows_per_partition": {"__dvt_type": "const", "value": 100000},
        },
    )

    assert changed is True
    assert converted_name == "ReadQueryFromDBV2"
    assert converted_display_name == "Read Query From DB V2"
    assert "limit" not in converted_inputs
    assert "max_rows_per_partition" not in converted_inputs


def test_upgrade_updates_all_target_rows(monkeypatch) -> None:
    migration = _load_module()

    rows = [
        {
            "id": "n1",
            "name": "ReadTableFromDBV2",
            "display_name": "Read Table From DB V2",
            "input_values": {
                "index_col": {"__dvt_type": "const", "value": "id"},
                "table_name": {"__dvt_type": "const", "value": "orders"},
            },
        },
        {
            "id": "n2",
            "name": "ReadQueryFromDBV2",
            "display_name": "Кастомный query reader",
            "input_values": {"query": {"__dvt_type": "const", "value": "SELECT * FROM orders"}},
        },
        {
            "id": "n3",
            "name": "ReadTableFromDBV2",
            "display_name": "Read Table From DB V2",
            "input_values": {
                "index_col": {"__dvt_type": "const", "value": None},
                "partition_col": {"__dvt_type": "const", "value": "order_id"},
            },
        },
    ]

    captured: dict[str, Any] = {"updates": None}

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration, "_load_target_rows", lambda bind, source_node_names: rows)

    def _capture_updates(bind, updates):
        captured["updates"] = updates

    monkeypatch.setattr(migration, "_persist_updates", _capture_updates)

    migration.upgrade()

    assert captured["updates"] is not None
    assert len(captured["updates"]) == 3

    updates_by_id = {item["row_id"]: item for item in captured["updates"]}
    assert updates_by_id["n1"]["row_name"] == "ReadTableFromDBV3"
    assert updates_by_id["n1"]["row_display_name"] == "Read Table From DB V3"
    assert "index_col" not in updates_by_id["n1"]["row_input_values"]
    assert updates_by_id["n1"]["row_input_values"]["partition_col"] == {"__dvt_type": "const", "value": "id"}

    assert updates_by_id["n2"]["row_name"] == "ReadQueryFromDBV3"
    assert updates_by_id["n2"]["row_display_name"] == "Кастомный query reader"
    assert updates_by_id["n2"]["row_input_values"]["query"] == {"__dvt_type": "const", "value": "SELECT * FROM orders"}

    assert updates_by_id["n3"]["row_name"] == "ReadTableFromDBV3"
    assert updates_by_id["n3"]["row_display_name"] == "Read Table From DB V3"
    assert "index_col" not in updates_by_id["n3"]["row_input_values"]
    assert updates_by_id["n3"]["row_input_values"]["partition_col"] == {
        "__dvt_type": "const",
        "value": "order_id",
    }


def test_downgrade_updates_all_target_rows(monkeypatch) -> None:
    migration = _load_module()

    rows = [
        {
            "id": "n1",
            "name": "ReadTableFromDBV3",
            "display_name": "Read Table From DB V3",
            "input_values": {
                "partition_col": {"__dvt_type": "const", "value": "id"},
                "max_rows_per_partition": {"__dvt_type": "const", "value": 50000},
            },
        },
        {
            "id": "n2",
            "name": "ReadQueryFromDBV3",
            "display_name": "Кастомное название V3",
            "input_values": {
                "query": {"__dvt_type": "const", "value": "SELECT * FROM orders"},
                "limit": {"__dvt_type": "const", "value": 1000},
                "max_rows_per_partition": {"__dvt_type": "const", "value": 100000},
            },
        },
    ]

    captured: dict[str, Any] = {"updates": None}

    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(migration, "_load_target_rows", lambda bind, source_node_names: rows)

    def _capture_updates(bind, updates):
        captured["updates"] = updates

    monkeypatch.setattr(migration, "_persist_updates", _capture_updates)

    migration.downgrade()

    assert captured["updates"] is not None
    assert len(captured["updates"]) == 2

    updates_by_id = {item["row_id"]: item for item in captured["updates"]}
    assert updates_by_id["n1"]["row_name"] == "ReadTableFromDBV2"
    assert updates_by_id["n1"]["row_display_name"] == "Read Table From DB V2"
    assert updates_by_id["n1"]["row_input_values"]["index_col"] == {"__dvt_type": "const", "value": "id"}
    assert "max_rows_per_partition" not in updates_by_id["n1"]["row_input_values"]

    assert updates_by_id["n2"]["row_name"] == "ReadQueryFromDBV2"
    assert updates_by_id["n2"]["row_display_name"] == "Кастомное название V3"
    assert "limit" not in updates_by_id["n2"]["row_input_values"]
    assert "max_rows_per_partition" not in updates_by_id["n2"]["row_input_values"]
