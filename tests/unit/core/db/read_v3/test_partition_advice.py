from __future__ import annotations

from datetime import date

import pytest

from core.db.read_v3.dialects import (
    ClickHouseDialect,
    MssqlDialect,
    MySQLDialect,
    OracleDialect,
    PostgresDialect,
    SQLDialect,
    SqliteDialect,
)
from core.db.read_v3.key_stats import ColumnKeyStats, KeyStatsSource, RelationKeyStats
from core.db.read_v3.models import PartitionStrategy, ReadMode, ValueKind
from core.db.read_v3.partition_advice import (
    SINGLE_QUERY_BOUNDARY_DIALECTS,
    advise_partitioning,
    build_sizing,
)

import config

SIZING = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}
RECEIPTS_ROWS = 49_690_000


def _column(name: str, type_repr: str, kind: ValueKind, **values) -> ColumnKeyStats:
    defaults = {
        "available": True,
        "source": KeyStatsSource.EXACT,
        "null_count": 0,
    }
    return ColumnKeyStats(name=name, type_repr=type_repr, value_kind=kind, **{**defaults, **values})


def _stats(
    *columns: ColumnKeyStats,
    total_rows: int = RECEIPTS_ROWS,
    bytes_per_row: int = 2087,
    mode: ReadMode = ReadMode.TABLE,
    dialect: str = "clickhouse",
) -> RelationKeyStats:
    return RelationKeyStats(
        mode=mode,
        dialect=dialect,
        relation="receipts",
        total_rows=total_rows,
        total_rows_estimated=False,
        bytes_per_row_est=bytes_per_row,
        read_columns=tuple(column.name for column in columns),
        sort_key="naimenovanie_tovara",
        sample_method=None,
        sample_rows=None,
        sample_threshold_rows=1_000_000,
        columns=columns,
    )


def _receipts() -> RelationKeyStats:
    numeric, string = ValueKind.NUMERIC, ValueKind.STRING
    return _stats(
        _column(
            "naimenovanie_tovara",
            "String",
            string,
            distinct_count=20_057,
            max_repeat=464_500,
            max_repeat_value="Бананы",
            indexed=True,
        ),
        _column(
            "kod_tovara",
            "Int64",
            numeric,
            distinct_count=20_071,
            max_repeat=404_499,
            max_repeat_value=75_588,
            min_value=14,
            max_value=933_974,
        ),
        _column(
            "nomer_cheka",
            "Int64",
            numeric,
            distinct_count=894,
            max_repeat=131_325,
            max_repeat_value=129,
            min_value=129,
            max_value=41_265,
        ),
        _column(
            "summa_k_oplate",
            "Float64",
            numeric,
            distinct_count=40_487,
            max_repeat=204_325,
            max_repeat_value=19.0,
        ),
        _column(
            "vremia_pokupki",
            "String",
            string,
            distinct_count=730,
            max_repeat=68_929,
            max_repeat_value="2025-02-24 09:04:45",
        ),
    )


def test_heavy_value_key_is_excluded_and_low_skew_integer_key_ranks_first():
    advice = advise_partitioning(_receipts(), npartitions=600, **SIZING)

    assert advice.sizing.target_npartitions == 600
    assert advice.sizing.target_rows_per_partition == 82_817
    assert advice.sizing.max_rows_per_partition == 331_268
    excluded = {item.name: item.reasons for item in advice.excluded}
    assert set(excluded) == {"kod_tovara", "naimenovanie_tovara"}
    assert "value 75588 occurs 404499 times" in excluded["kod_tovara"][0]
    assert "max_rows_per_partition >= 487316" in excluded["kod_tovara"][0]

    ranked = [item.partition_col for item in advice.recommendations]
    assert ranked == ["nomer_cheka", "summa_k_oplate", "vremia_pokupki"]
    best = advice.recommendations[0]
    # Not sorted by nomer_cheka: hash, one bucket per target partition.
    assert best.strategy == PartitionStrategy.HASH
    assert best.partition_grouping == {"mode": "hash", "buckets": 600}
    assert best.npartitions == 600
    assert best.max_rows_per_partition == 2 * (82_817 + 131_325)
    assert best.skew == pytest.approx(131_325 / (RECEIPTS_ROWS / 894), abs=1e-3)
    # The reason is the reading cost: range planning on ClickHouse is one sort of the key.
    assert best.reasons[-1] == (
        "hash with buckets=600: relation is not sorted or indexed by 'nomer_cheka': range and "
        "hash segments would each scan the whole relation, and hash keeps segments even when key "
        "values repeat (range boundaries would take one sort of the key per plan)"
    )


def test_default_sizing_matches_the_planner_estimate_and_excludes_every_receipts_key():
    advice = advise_partitioning(_receipts(), **SIZING)

    assert advice.sizing.npartitions_source == "planner_estimate"
    assert advice.sizing.target_npartitions == 3435
    assert advice.sizing.max_rows_per_partition == 100_000
    assert advice.recommendations == ()
    excluded = {item.name: item.reasons for item in advice.excluded}
    assert any("894 distinct values" in reason for reason in excluded["nomer_cheka"])
    assert any("fits npartitions <= 730" in reason for reason in excluded["vremia_pokupki"])
    assert "no profiled column fits" in advice.warnings[-1]


def test_requested_ceiling_admits_a_key_and_is_kept_in_the_recommendation():
    advice = advise_partitioning(
        _receipts(), npartitions=600, max_rows_per_partition=450_000, **SIZING
    )

    assert advice.sizing.max_rows_per_partition_source == "request"
    kod = next(item for item in advice.recommendations if item.partition_col == "kod_tovara")
    assert kod.max_rows_per_partition == 450_000
    assert any(
        "above max_rows_per_partition=450000; reading that segment can fail" in warning
        for warning in kod.warnings
    )


def test_explicit_npartitions_is_clamped_to_rows():
    sizing = build_sizing(
        _stats(
            _column("id", "Int64", ValueKind.NUMERIC, distinct_count=50, max_repeat=1),
            total_rows=50,
        ),
        npartitions=100,
        **SIZING,
    )
    assert sizing.target_npartitions == 50
    assert sizing.max_rows_per_partition == 100_000


def test_indexed_non_null_key_gets_range_and_nulls_force_hash():
    stats = _stats(
        _column(
            "id", "UInt64", ValueKind.NUMERIC, distinct_count=1_000_000, max_repeat=1, indexed=True
        ),
        _column(
            "customer_id",
            "Nullable(Int64)",
            ValueKind.NUMERIC,
            distinct_count=900_000,
            max_repeat=3,
            null_count=50_000,
            indexed=True,
        ),
        _column(
            "big_nulls",
            "Nullable(Int64)",
            ValueKind.NUMERIC,
            distinct_count=900_000,
            max_repeat=3,
            null_count=600_000,
        ),
        total_rows=1_000_000,
        bytes_per_row=100,
    )
    advice = advise_partitioning(stats, npartitions=10, **SIZING)

    by_name = {item.partition_col: item for item in advice.recommendations}
    assert by_name["id"].strategy == PartitionStrategy.RANGE
    assert by_name["id"].partition_grouping == {"mode": "range"}
    assert by_name["id"].reasons[-1] == (
        "relation is sorted or indexed by 'id' and the key has no NULLs: each range segment "
        "reads only its slice of the key; boundaries take one sort of the key per plan"
    )
    assert advice.recommendations[0].partition_col == "id"
    assert by_name["customer_id"].partition_grouping == {"mode": "hash", "buckets": 10}
    assert any("NULL keys rule out range" in reason for reason in by_name["customer_id"].reasons)
    assert any("one hash bucket" in warning for warning in by_name["customer_id"].warnings)
    excluded = {item.name: item.reasons for item in advice.excluded}
    assert "600000 NULL keys form one hash bucket" in excluded["big_nulls"][0]


def test_query_mode_and_strings_use_hash():
    stats = _stats(
        _column("code", "String", ValueKind.STRING, distinct_count=500_000, max_repeat=2),
        _column("id", "Int64", ValueKind.NUMERIC, distinct_count=1_000_000, max_repeat=1),
        total_rows=1_000_000,
        bytes_per_row=100,
        mode=ReadMode.QUERY,
    )
    advice = advise_partitioning(stats, npartitions=10, **SIZING)

    assert [item.partition_col for item in advice.recommendations] == ["id", "code"]
    assert {item.strategy for item in advice.recommendations} == {PartitionStrategy.HASH}
    assert advice.recommendations[0].reasons[-1] == (
        "hash with buckets=10: a query result has no index: range and hash segments would each "
        "scan the whole relation, and hash keeps segments even when key values repeat"
    )


def test_date_key_gets_the_coarsest_fitting_granularity_estimate():
    stats = _stats(
        _column(
            "sale_date",
            "Date",
            ValueKind.DATE,
            distinct_count=1827,
            max_repeat=6_000,
            min_value=date(2020, 1, 1),
            max_value=date(2024, 12, 31),
        ),
        total_rows=10_000_000,
        bytes_per_row=100,
    )
    advice = advise_partitioning(stats, npartitions=100, **SIZING)

    option = advice.recommendations[0].granularity_option
    assert option is not None
    # Years hold about 2M rows (above the 400k ceiling); months about 164k.
    assert option.partition_grouping == {"mode": "granularity", "granularity": "month"}
    # The planner adds a closing [next period start, max] segment after the 60 months.
    assert option.periods_est == 61
    assert option.rows_per_period_est == 163_935


def test_unavailable_and_unsupported_columns_are_reported():
    stats = _stats(
        ColumnKeyStats(
            name="payload",
            type_repr="JSON",
            value_kind=ValueKind.JSON,
            available=False,
            note="type 'JSON' (json) is not usable",
        ),
        _column("flag", "Bool", ValueKind.BOOL, distinct_count=2, max_repeat=10),
        total_rows=20,
    )
    advice = advise_partitioning(stats, **SIZING)

    excluded = {item.name: item.reasons for item in advice.excluded}
    assert excluded["payload"] == ("type 'JSON' (json) is not usable",)
    assert "not a usable key" in excluded["flag"][0]


@pytest.mark.parametrize(
    ("dialect", "indexed", "cost"),
    [
        ("postgresql", True, "boundaries take one sort of the key per plan"),
        (
            "sqlite",
            True,
            "boundaries take one ORDER BY key ... OFFSET query per partition on sqlite",
        ),
        (
            "sqlite",
            False,
            "range boundaries would take one ORDER BY key ... OFFSET query per partition on sqlite",
        ),
    ],
)
def test_range_planning_cost_follows_the_dialect(dialect, indexed, cost):
    stats = _stats(
        _column(
            "id",
            "BIGINT",
            ValueKind.NUMERIC,
            distinct_count=1_000_000,
            max_repeat=1,
            indexed=indexed,
        ),
        total_rows=1_000_000,
        bytes_per_row=100,
        dialect=dialect,
    )
    advice = advise_partitioning(stats, npartitions=10, **SIZING)

    recommendation = advice.recommendations[0]
    expected = PartitionStrategy.RANGE if indexed else PartitionStrategy.HASH
    assert recommendation.strategy == expected
    assert cost in recommendation.reasons[-1]


@pytest.mark.parametrize(
    "dialect",
    [
        ClickHouseDialect(),
        PostgresDialect(),
        MssqlDialect(),
        MySQLDialect(),
        OracleDialect(),
        SqliteDialect(),
    ],
    ids=lambda dialect: dialect.name,
)
def test_single_query_dialects_match_the_dialect_overrides(dialect):
    overrides = type(dialect).range_boundaries_query is not SQLDialect.range_boundaries_query

    assert (dialect.name in SINGLE_QUERY_BOUNDARY_DIALECTS) == overrides
