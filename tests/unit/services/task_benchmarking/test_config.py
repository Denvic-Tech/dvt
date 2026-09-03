from services.task_benchmarking import (
    cli_global_input_overrides,
    merge_global_overrides,
    resolve_preset,
)


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
