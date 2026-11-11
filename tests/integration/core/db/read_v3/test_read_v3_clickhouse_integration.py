from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pandas as pd
import pytest
import sqlalchemy as sa
from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.httpclient import HttpClient

from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client
from core.db.read_v3._auto_partition import (
    ROW_OVERHEAD_BYTES,
    TABLE_BPR_SAFETY_COEF,
    estimate_table_bytes_per_row,
)
from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.errors import ReadV3ExecutionError
from core.db.read_v3.executors import ch as ch_executor
from core.db.read_v3.executors.ch import ClickHouseReadExecutor
from core.db.read_v3.models import ReadV3Plan
from core.db.read_v3.planner.boundaries import query_range_boundaries
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config

pytestmark = pytest.mark.docker_required

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}

# Every type of the Arrow allow-list, plain and inside Nullable/LowCardinality.
TYPED_COLUMNS = {
    "id": "Int64",
    "i8": "Int8",
    "i16": "Int16",
    "i32": "Int32",
    "i64": "Int64",
    "u8": "UInt8",
    "u16": "UInt16",
    "u32": "UInt32",
    "u64": "UInt64",
    "n_i8": "Nullable(Int8)",
    "n_i32": "Nullable(Int32)",
    "n_i64": "Nullable(Int64)",
    "n_u64": "Nullable(UInt64)",
    "f32": "Float32",
    "f64": "Float64",
    "n_f32": "Nullable(Float32)",
    "n_f64": "Nullable(Float64)",
    "b": "Bool",
    "n_b": "Nullable(Bool)",
    "s": "String",
    "n_s": "Nullable(String)",
    "lc_s": "LowCardinality(String)",
    "lc_n_s": "LowCardinality(Nullable(String))",
    "d": "Date",
    "n_d": "Nullable(Date)",
    "d32": "Date32",
    "n_d32": "Nullable(Date32)",
    "dt": "DateTime",
    "dt_tokyo": "DateTime('Asia/Tokyo')",
    "n_dt": "Nullable(DateTime)",
    "dt64": "DateTime64(3)",
    "dt64_msk": "DateTime64(3, 'Europe/Moscow')",
    "dt64_us": "DateTime64(6)",
    "dt64_ns": "DateTime64(9)",
    "n_dt64_tokyo": "Nullable(DateTime64(6, 'Asia/Tokyo'))",
    "dec": "Decimal(38, 4)",
    "n_dec": "Nullable(Decimal(18, 2))",
    "dec_int": "Decimal(18, 0)",
    "dec32": "Decimal32(3)",
    "dec256": "Decimal256(10)",
}
TYPED_ROWS = [
    (
        "1, -128, -32768, -2147483648, -9223372036854775807, 0, 0, 0, 9007199254740993, "
        "NULL, NULL, NULL, NULL, 1.5, -2.25, NULL, NULL, true, NULL, "
        "'привет', NULL, 'lc', NULL, '1970-01-01', NULL, '1900-01-01', NULL, "
        "'1970-01-01 00:00:00', '2024-03-01 10:20:30', NULL, "
        "'2024-03-01 10:20:30.123', '1969-12-31 23:59:58.001', '2024-03-01 10:20:30.123456', "
        "'2024-03-01 10:20:30.123456789', NULL, "
        "1234567890123456789012345678901234.5678, NULL, 12, 1.5, 3.1415926535"
    ),
    (
        "2, 127, 32767, 2147483647, 9223372036854775807, 255, 65535, 4294967295, 1, "
        "-7, 5, 9007199254740993, 9223372036854775807, -0.0, 1e300, 3.5, 2.5, false, true, "
        "'', '', '', 'x', '2149-06-06', '2024-02-29', '2200-12-31', '1960-05-05', "
        "'2106-02-07 06:28:15', '1970-01-01 09:00:00', '2024-01-01 00:00:00', "
        "'1900-01-01 00:00:00.001', '2024-03-01 10:20:30.123', '2200-12-31 23:59:59.999999', "
        "'2262-04-11 23:47:16.854775806', '2024-01-01 00:00:00.010000', "
        "-0.0001, 99.99, -5, -0.001, -1.5"
    ),
    (
        "3, 0, 0, 0, 0, 1, 1, 1, 0, "
        "0, NULL, 42, NULL, nan, inf, NULL, nan, true, false, "
        "'tab\\tnl\\n', 'v', 'lc', 'y', '2000-02-29', NULL, '1969-12-31', NULL, "
        "'2000-01-01 12:00:00', '2000-01-01 12:00:00', NULL, "
        "'2000-01-01 12:00:00.5', '2000-01-01 12:00:00.5', '2000-01-01 12:00:00.5', "
        "'2000-01-01 12:00:00.5', NULL, "
        "0.5, NULL, 0, 0, 0"
    ),
    (
        "4, 1, 2, 3, 4, 5, 6, 7, 8, "
        "9, 10, 11, 12, 0.25, -0.5, 0.75, -1.25, false, NULL, "
        "'Ünïcødé ✓', NULL, 'other', NULL, '2024-12-31', '2024-12-31', '2024-12-31', "
        "'2024-12-31', '2024-12-31 23:59:59', '2024-12-31 23:59:59', '2024-12-31 23:59:59', "
        "'2024-12-31 23:59:59.999', '2024-12-31 23:59:59.999', '2024-12-31 23:59:59.999999', "
        "'2024-12-31 23:59:59.999999999', '2024-12-31 23:59:59.999999', "
        "-99999999999999999999999999999999.9999, -0.01, 999999999999999999, 999999.999, "
        "-123456789.0123456789"
    ),
]


@pytest.fixture
def clickhouse_client(clickhouse_http_test_engine: sa.Engine) -> Generator[Client]:
    client = create_clickhouse_client(build_clickhouse_client_kwargs(clickhouse_http_test_engine))
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def table_name(clickhouse_client: Client) -> Generator[str]:
    name = f"read_v3_ch_{uuid4().hex[:12]}"
    try:
        yield name
    finally:
        clickhouse_client.command(f"DROP TABLE IF EXISTS `{name}`")


def _create_table(client: Client, name: str, columns: dict[str, str], rows: list[str]) -> None:
    columns_sql = ", ".join(f"`{column}` {type_sql}" for column, type_sql in columns.items())
    client.command(f"CREATE TABLE `{name}` ({columns_sql}) ENGINE = MergeTree ORDER BY id")
    client.command(f"INSERT INTO `{name}` VALUES " + ", ".join(f"({row})" for row in rows))


def _table_plan(engine: sa.Engine, table_name: str, **kwargs) -> ReadV3Plan:
    kwargs.setdefault("partition_col", "id")
    kwargs.setdefault("npartitions", 1)
    kwargs.setdefault("partition_grouping", {"mode": "range"})
    return resolve_planner(mode="table").build_plan(
        engine=engine, table_name=table_name, **STRICT_PARTITIONING_KWARGS, **kwargs
    )


def _query_plan(engine: sa.Engine, query: str, **kwargs) -> ReadV3Plan:
    kwargs.setdefault("partition_col", "id")
    kwargs.setdefault("npartitions", 1)
    kwargs.setdefault("partition_grouping", {"mode": "range"})
    return resolve_planner(mode="query").build_plan(
        engine=engine, query=query, **STRICT_PARTITIONING_KWARGS, **kwargs
    )


def _segment_sql(executor: ClickHouseReadExecutor, plan: ReadV3Plan) -> str:
    assert plan.segment_count == 1
    sql = executor._segment_sql(plan, plan.segments[0])
    return executor.dialect.cap_rows_sql(sql, plan.max_rows_per_partition + 1)


def _decimal_strings(series: pd.Series) -> list[str | None]:
    return [None if value is None else str(value) for value in series.tolist()]


def _assert_paths_match(
    executor: ClickHouseReadExecutor,
    plan: ReadV3Plan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ch_executor._segment_arrow_specs(plan) is not None
    sql = _segment_sql(executor, plan)
    arrow_df = executor._fetch_segment_df(sql, plan)
    query_df = executor.sql_runner.query_df(sql)
    assert len(arrow_df) == len(TYPED_ROWS)

    for column in query_df.columns:
        assert arrow_df[column].dtype == query_df[column].dtype, column
        pd.testing.assert_series_equal(arrow_df[column], query_df[column], obj=column)
        if str(query_df[column].dtype) == "object" and column.startswith(("dec", "n_dec")):
            assert _decimal_strings(arrow_df[column]) == _decimal_strings(query_df[column])

    hinted_arrow = executor._apply_output_type_hints(arrow_df, plan, stage="test")
    hinted_query = executor._apply_output_type_hints(query_df, plan, stage="test")
    pd.testing.assert_frame_equal(hinted_arrow, hinted_query)

    segment = plan.segments[0]
    loaded_arrow = executor.load_partition(plan, segment)
    with monkeypatch.context() as patch:
        patch.setattr(ch_executor, "_segment_arrow_specs", lambda _plan: None)
        loaded_query = executor.load_partition(plan, segment)
    pd.testing.assert_frame_equal(loaded_arrow, loaded_query)


def test_arrow_path_matches_query_df_for_every_supported_type(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table(clickhouse_client, table_name, TYPED_COLUMNS, TYPED_ROWS)
    executor = resolve_executor(clickhouse_http_test_engine, max_concurrent_queries=2)
    assert isinstance(executor, ClickHouseReadExecutor)

    table_plan = _table_plan(clickhouse_http_test_engine, table_name)
    _assert_paths_match(executor, table_plan, monkeypatch)

    query_plan = _query_plan(clickhouse_http_test_engine, f"SELECT * FROM `{table_name}`")
    assert query_plan.output_column_type_repr["dt_tokyo"] == "DateTime('Asia/Tokyo')"
    _assert_paths_match(executor, query_plan, monkeypatch)

    # The partition key is read as a raw helper column (the index) when it is not an output.
    helper_plan = _table_plan(
        clickhouse_http_test_engine,
        table_name,
        columns=["s", "dt_tokyo", "n_dec"],
        partition_col="dt",
    )
    assert helper_plan.index_column_name == helper_plan.partition_key_alias
    loaded = executor.load_partition(helper_plan, helper_plan.segments[0])
    with monkeypatch.context() as patch:
        patch.setattr(ch_executor, "_segment_arrow_specs", lambda _plan: None)
        loaded_query = executor.load_partition(helper_plan, helper_plan.segments[0])
    assert list(loaded.columns) == ["s", "dt_tokyo", "n_dec"]
    assert len(loaded) == len(TYPED_ROWS)
    pd.testing.assert_frame_equal(loaded, loaded_query)


def test_tz_columns_keep_instants_and_decimals_stay_exact(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
) -> None:
    _create_table(clickhouse_client, table_name, TYPED_COLUMNS, TYPED_ROWS)
    plan = _table_plan(clickhouse_http_test_engine, table_name)
    executor = resolve_executor(clickhouse_http_test_engine)
    loaded = executor.load_partition(plan, plan.segments[0]).sort_index()

    epochs = clickhouse_client.query(
        f"SELECT toUnixTimestamp(dt_tokyo), toUnixTimestamp64Milli(dt64_msk), "
        f"toString(dec), toString(n_dec) FROM `{table_name}` ORDER BY id"
    ).result_rows
    tokyo = pd.to_datetime([row[0] for row in epochs], unit="s").as_unit("us")
    moscow = pd.to_datetime([row[1] for row in epochs], unit="ms").as_unit("us")
    assert loaded["dt_tokyo"].tolist() == tokyo.tolist()
    assert loaded["dt64_msk"].tolist() == moscow.tolist()
    assert loaded["n_u64"].tolist()[1] == 9223372036854775807
    assert loaded["u64"].tolist()[0] == 9007199254740993
    assert loaded["s"].tolist()[0] == "привет"
    assert loaded["n_s"].isna().tolist() == [True, False, False, True]


def test_unsupported_type_reads_segment_through_query_df(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _create_table(
        clickhouse_client,
        table_name,
        {"id": "Int64", "label": "Nullable(String)", "uid": "UUID", "amount": "Decimal(18, 2)"},
        [
            "1, 'a', '00000000-0000-0000-0000-000000000001', 1.25",
            "2, NULL, '00000000-0000-0000-0000-000000000002', -3.50",
        ],
    )
    plan = _table_plan(clickhouse_http_test_engine, table_name, npartitions=2)
    assert ch_executor._segment_arrow_specs(plan) is None

    original_raw_query = HttpClient.raw_query

    def _no_arrow(self, query, *args, **kwargs):
        assert kwargs.get("fmt") != "Arrow", "a segment with an unsupported type must not use Arrow"
        return original_raw_query(self, query, *args, **kwargs)

    monkeypatch.setattr(HttpClient, "raw_query", _no_arrow)
    executor = resolve_executor(clickhouse_http_test_engine)
    result = frame_from_executor(executor, plan).compute(scheduler="threads", num_workers=2)
    result = result.sort_index()

    assert result["id"].tolist() == [1, 2]
    assert result["label"].tolist()[0] == "a"
    assert result["label"].isna().tolist() == [False, True]
    assert result["uid"].tolist() == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    assert result["amount"].tolist() == [1.25, -3.5]


def test_invalid_utf8_segment_is_reread_through_query_df(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
) -> None:
    _create_table(
        clickhouse_client,
        table_name,
        {"id": "Int64", "payload": "String"},
        ["1, unhex('C328')", "2, 'ok'"],
    )
    plan = _table_plan(clickhouse_http_test_engine, table_name)
    executor = resolve_executor(clickhouse_http_test_engine)

    loaded = executor.load_partition(plan, plan.segments[0]).sort_index()

    # query_df renders undecodable bytes as hex.
    assert loaded["payload"].tolist() == ["c328", "ok"]


def test_datetime64_precision_outside_query_df_support_reads_through_arrow(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
) -> None:
    _create_table(
        clickhouse_client,
        table_name,
        {"id": "Int64", "ts": "DateTime64(2)"},
        ["1, '2024-03-01 10:20:30.12'"],
    )
    plan = _table_plan(clickhouse_http_test_engine, table_name)
    executor = resolve_executor(clickhouse_http_test_engine)

    loaded = executor.load_partition(plan, plan.segments[0])

    assert loaded["ts"].tolist() == [pd.Timestamp("2024-03-01 10:20:30.12")]


def test_frame_from_executor_reads_every_segment_through_arrow(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = 60_000
    clickhouse_client.command(
        f"CREATE TABLE `{table_name}` (id Int64, label LowCardinality(String), "
        "note Nullable(String), amount Decimal(18, 2), ts DateTime64(3, 'Europe/Moscow'), "
        "flag Bool) ENGINE = MergeTree ORDER BY id"
    )
    clickhouse_client.command(
        f"INSERT INTO `{table_name}` SELECT number, concat('g', toString(number % 7)), "
        "if(number % 5 = 0, NULL, toString(number)), toDecimal64(number, 2) / 100, "
        "toDateTime64(1700000000 + number, 3, 'Europe/Moscow'), number % 2 = 0 "
        f"FROM numbers({rows})"
    )
    plan = _table_plan(clickhouse_http_test_engine, table_name, npartitions=6)
    assert plan.segment_count == 6

    calls = {"arrow": 0, "df": 0}
    original_raw_query = HttpClient.raw_query
    original_df = Client.query_df

    def _count_arrow(self, *args, **kwargs):
        calls["arrow"] += kwargs.get("fmt") == "Arrow"
        return original_raw_query(self, *args, **kwargs)

    def _count_df(self, *args, **kwargs):
        calls["df"] += 1
        return original_df(self, *args, **kwargs)

    executor = resolve_executor(clickhouse_http_test_engine, max_concurrent_queries=3)
    ddf = frame_from_executor(executor, plan)
    monkeypatch.setattr(HttpClient, "raw_query", _count_arrow)
    monkeypatch.setattr(Client, "query_df", _count_df)
    result = ddf.compute(scheduler="threads", num_workers=4)

    expected = clickhouse_client.query(
        f"SELECT count(), sum(id), sum(amount), countIf(note IS NULL), sum(length(label)), "
        f"countIf(flag), sum(toUnixTimestamp64Milli(ts)) FROM `{table_name}`"
    ).first_row
    assert calls == {"arrow": plan.segment_count, "df": 0}
    assert len(result) == expected[0] == rows
    assert int(result["id"].sum()) == expected[1]
    assert float(result["amount"].sum()) == pytest.approx(float(expected[2]), abs=0.01)
    assert int(result["note"].isna().sum()) == expected[3]
    assert int(result["label"].str.len().sum()) == expected[4]
    assert int(result["flag"].sum()) == expected[5]
    epoch_ms = result["ts"].astype("datetime64[ms]").astype("int64")
    assert int(epoch_ms.sum()) == expected[6]


def test_max_rows_per_partition_guard_fires_on_arrow_path(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
) -> None:
    clickhouse_client.command(
        f"CREATE TABLE `{table_name}` (id Int64, label String) ENGINE = MergeTree ORDER BY id"
    )
    clickhouse_client.command(
        f"INSERT INTO `{table_name}` SELECT number, toString(number) FROM numbers(50)"
    )
    plan = _table_plan(clickhouse_http_test_engine, table_name, max_rows_per_partition=10)
    assert ch_executor._segment_arrow_specs(plan) is not None
    executor = resolve_executor(clickhouse_http_test_engine)

    with pytest.raises(
        ReadV3ExecutionError,
        match=r"Segment .* exceeded max_rows_per_partition=10 \(rows_read=11\)",
    ):
        executor.load_partition(plan, plan.segments[0])


BOUNDARY_ROWS = 30_000
BOUNDARY_KEYS = {
    "k_int": "Int64",
    "k_str": "String",
    "k_dt": "DateTime",
    "k_dec": "Decimal(18, 4)",
    "n_int": "Nullable(Int64)",
    "n_str": "Nullable(String)",
    "n_dt": "Nullable(DateTime)",
    "n_dec": "Nullable(Decimal(18, 4))",
}


def _create_boundary_table(client: Client, name: str, *, settings: str = "") -> None:
    columns_sql = ", ".join(f"`{column}` {type_sql}" for column, type_sql in BOUNDARY_KEYS.items())
    client.command(
        f"CREATE TABLE `{name}` (id Int64, {columns_sql}) ENGINE = MergeTree ORDER BY id {settings}"
    )
    # Duplicated keys in a physical order unrelated to the key order; NULLs in the n_* columns.
    client.command(
        f"INSERT INTO `{name}` SELECT number, "
        "toInt64(cityHash64(number, 1) % 4000) - 2000, "
        "concat('s', toString(cityHash64(number, 2) % 2500)), "
        "toDateTime(1700000000 + (cityHash64(number, 3) % 3000) * 60), "
        "toDecimal64(cityHash64(number, 4) % 7000, 4) / 3, "
        "if(number % 17 = 0, NULL, toInt64(cityHash64(number, 5) % 900)), "
        "if(number % 19 = 0, NULL, concat('n', toString(cityHash64(number, 6) % 700))), "
        "if(number % 23 = 0, NULL, toDateTime(1600000000 + (cityHash64(number, 7) % 800) * 3600)), "
        "if(number % 29 = 0, NULL, toDecimal64(cityHash64(number, 8) % 600, 4) / 7) "
        f"FROM numbers({BOUNDARY_ROWS})"
    )


class _OffsetOnlyClickHouseDialect(ClickHouseDialect):
    def range_boundaries_query(self, relation_sql, key_sql, *, page_size, non_null_rows):
        raise NotImplementedError


@pytest.mark.parametrize("key", list(BOUNDARY_KEYS))
def test_single_query_range_boundaries_match_offset_queries(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
    key: str,
) -> None:
    _create_boundary_table(clickhouse_client, table_name)
    count_sql = f"SELECT count(`{key}`) FROM `{table_name}`"
    non_null_rows = clickhouse_client.query(count_sql).first_row[0]
    for npartitions in (13, 64):
        kwargs = {
            "engine": clickhouse_http_test_engine,
            "cte_prefix_sql": None,
            "relation_sql": f"FROM `{table_name}`",
            "key_sql": f"`{key}`",
            "page_size": -(-non_null_rows // npartitions),
            "non_null_rows": non_null_rows,
        }
        single, single_status = query_range_boundaries(dialect=ClickHouseDialect(), **kwargs)
        offset, offset_status = query_range_boundaries(
            dialect=_OffsetOnlyClickHouseDialect(), **kwargs
        )

        assert (single_status, offset_status) == ("single_query", "offset_loop")
        assert len(single) == len(range(0, non_null_rows, kwargs["page_size"]))
        assert single == offset, (key, npartitions)
        assert [type(value) for value in single] == [type(value) for value in offset]


@pytest.mark.parametrize(
    "key",
    [
        "k_int",
        "k_str",
        "k_dt",
        pytest.param(
            "k_dec",
            marks=pytest.mark.xfail(
                raises=ReadV3ExecutionError,
                strict=True,
                reason="Known defect, independent of the boundary query: the segment index of a "
                "Decimal range key is float64 and fails the Decimal division bound check.",
            ),
        ),
    ],
)
def test_single_query_range_plan_reads_every_row(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
    key: str,
) -> None:
    _create_boundary_table(clickhouse_client, table_name)
    executor = resolve_executor(clickhouse_http_test_engine, max_concurrent_queries=4)

    table_plan = _table_plan(
        clickhouse_http_test_engine, table_name, partition_col=key, npartitions=12
    )
    query_plan = _query_plan(
        clickhouse_http_test_engine,
        f"SELECT id, `{key}` FROM `{table_name}` WHERE id % 3 <> 1",
        partition_col=key,
        npartitions=7,
    )

    for plan, expected_rows in (
        (table_plan, BOUNDARY_ROWS),
        (query_plan, BOUNDARY_ROWS - len(range(1, BOUNDARY_ROWS, 3))),
    ):
        assert "range_boundaries=single_query" in plan.extra_warnings
        assert plan.segment_count > 1
        result = frame_from_executor(executor, plan).compute(scheduler="threads", num_workers=4)
        assert len(result) == expected_rows
        assert result["id"].nunique() == expected_rows


def test_table_width_estimate_matches_uncompressed_size(
    clickhouse_http_test_engine: sa.Engine,
    clickhouse_client: Client,
    table_name: str,
) -> None:
    # Wide parts: compact parts report no per-column sizes.
    _create_boundary_table(
        clickhouse_client, table_name, settings="SETTINGS min_bytes_for_wide_part = 0"
    )
    real = clickhouse_client.query(
        "SELECT sum(data_uncompressed_bytes) / sum(rows) FROM system.parts "
        f"WHERE database = currentDatabase() AND table = '{table_name}' AND active"
    ).first_row[0]
    columns_info = sa.inspect(clickhouse_http_test_engine).get_columns(table_name)

    estimate = estimate_table_bytes_per_row(
        engine=clickhouse_http_test_engine,
        dialect=ClickHouseDialect(),
        table_name=table_name,
        schema=None,
        selected_columns=[str(column["name"]) for column in columns_info],
        columns_info=columns_info,
    )

    raw_width = (estimate - ROW_OVERHEAD_BYTES) / TABLE_BPR_SAFETY_COEF
    assert abs(raw_width - real) <= 0.3 * real, (estimate, real)
