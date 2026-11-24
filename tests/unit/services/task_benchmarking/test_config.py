import pytest

from services.task_benchmarking import (
    cli_global_input_overrides,
    merge_global_overrides,
    resolve_preset,
)
from services.task_benchmarking.config import merge_node_overrides, parse_node_sets


def test_resolve_preset_contains_expected_defaults() -> None:
    preset = resolve_preset("ram_8g")

    assert preset is not None
    assert preset.global_input_overrides["npartitions"] == 64
    assert preset.global_input_overrides["num_workers"] == 2


def test_cli_global_input_overrides_and_merge() -> None:
    preset_overrides = {"npartitions": 64, "num_workers": 2}
    cli_overrides = cli_global_input_overrides(
        npartitions=None,
        num_workers=3,
        max_rows_per_partition=1_000_000,
    )

    merged = merge_global_overrides(preset_overrides, cli_overrides)

    assert merged["npartitions"] == 64
    assert merged["num_workers"] == 3
    assert merged["max_rows_per_partition"] == 1_000_000


def test_parse_node_sets_parses_json_values_and_keeps_plain_strings() -> None:
    overrides = parse_node_sets(
        ["data.rows=5000000", "data.schema=numeric", "join.left_on=[\"id\"]", "sink.flag=null"]
    )

    assert overrides == {
        "data": {"rows": 5_000_000, "schema": "numeric"},
        "join": {"left_on": ["id"]},
        "sink": {"flag": None},
    }


@pytest.mark.parametrize("item", ["rows=1", "data.rows", ".rows=1", "data.=1"])
def test_parse_node_sets_rejects_items_without_node_input_and_value(item: str) -> None:
    with pytest.raises(ValueError, match=r"NODE\.INPUT=VALUE"):
        parse_node_sets([item])


def test_merge_node_overrides_lets_later_values_win_per_input() -> None:
    merged = merge_node_overrides(
        {"data": {"rows": 1, "seed": 7}}, None, {"data": {"rows": 2}, "sink": {"mode": "x"}}
    )

    assert merged == {"data": {"rows": 2, "seed": 7}, "sink": {"mode": "x"}}
