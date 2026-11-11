from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import dask
import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest
import sqlalchemy as sa

from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client
from core.db.write_v4 import WriteMode, WriteRequest, WriteTarget, write_dataframe
from core.db.write_v4.errors import WriteV4ExecutionError

from services.task_benchmarking import synthetic

pytestmark = pytest.mark.docker_required

ROWS = 20_000
NPARTITIONS = 4
SEED = 42
_MSK = timezone(timedelta(hours=3))


@pytest.fixture
def clickhouse_client(clickhouse_http_test_engine: sa.Engine) -> Generator:
    client = create_clickhouse_client(build_clickhouse_client_kwargs(clickhouse_http_test_engine))
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def table_name(clickhouse_client) -> Generator[str]:
    name = f"write_v4_ch_{uuid4().hex[:12]}"
    try:
        yield name
    finally:
        clickhouse_client.command(f"DROP TABLE IF EXISTS `{name}`")


def _write(engine: sa.Engine, pdf: pd.DataFrame, table_name: str, **kwargs) -> int:
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name=table_name),
        write_workers=2,
        **kwargs,
    )
    # Keep object columns (lists, UUID, date) as built: dask would turn them into strings.
    with dask.config.set({"dataframe.convert-string": False}):
        ddf = dd.from_pandas(pdf, npartitions=NPARTITIONS)
    return write_dataframe(ddf, engine, request).rows_written


def _column(pdf: pd.DataFrame, name: str) -> list:
    return pdf[name].to_numpy(dtype=object, na_value=None).tolist()


def _driver_decimal(value: float) -> Decimal:
    # clickhouse_connect semantics kept by the executor: int(Decimal(str(x)) * 10**scale).
    return Decimal(int(Decimal(str(value)) * 100)).scaleb(-2)


def test_wide_mixed_round_trips_per_column(
    clickhouse_http_test_engine: sa.Engine, clickhouse_client, table_name: str
) -> None:
    for statement in synthetic.create_table_sql("wide_mixed", "clickhouse", table_name):
        clickhouse_client.command(statement)
    pdf = pd.concat(
        [
            synthetic.generate_partition("wide_mixed", spec, SEED)
            for spec in synthetic.partition_plan(ROWS, NPARTITIONS)
        ],
        ignore_index=True,
    )

    # chunksize below the partition size: several INSERTs per partition.
    assert _write(clickhouse_http_test_engine, pdf, table_name, chunksize=3_000) == ROWS

    names = synthetic.column_names("wide_mixed")
    select = ", ".join(
        "toUnixTimestamp64Milli(ts_a)" if name == "ts_a" else f"`{name}`" for name in names
    )
    result = clickhouse_client.query(f"SELECT {select} FROM `{table_name}` ORDER BY id")
    got = dict(zip(names, result.result_columns, strict=True))
    assert len(got["id"]) == ROWS
    for name in ("id", "int_a", "int_b", "float_a", "float_b", "bool_a"):
        assert got[name] == _column(pdf, name), name
    for name in ("str_low", "str_high", "str_text", "str_null"):
        assert got[name] == _column(pdf, name), name
    expected_amount = [_driver_decimal(value) for value in pdf["amount"].tolist()]
    assert got["amount"] == expected_amount
    expected_ms = pdf["ts_a"].to_numpy().astype("datetime64[ms]").astype(np.int64).tolist()
    assert got["ts_a"] == expected_ms
    assert got["date_a"] == pdf["date_a"].dt.date.tolist()

    totals = clickhouse_client.query(
        f"SELECT count(), toString(sum(amount)), countIf(isNull(int_b)), "
        f"countIf(isNull(str_null)) FROM `{table_name}`"
    ).result_rows[0]
    assert totals[0] == ROWS
    assert Decimal(totals[1]) == sum(expected_amount, Decimal(0))
    assert totals[2] == int(pdf["int_b"].isna().sum()) > 0
    assert totals[3] == int(pdf["str_null"].isna().sum()) > 0
    str_low_type = clickhouse_client.command(
        "SELECT type FROM system.columns WHERE database = currentDatabase() "
        f"AND table = '{table_name}' AND name = 'str_low'"
    )
    assert str_low_type == "LowCardinality(String)"


def test_datetime_semantics_for_timezones_precision_and_nulls(
    clickhouse_http_test_engine: sa.Engine, clickhouse_client, table_name: str
) -> None:
    clickhouse_client.command(
        f"CREATE TABLE `{table_name}` (id Int64, plain DateTime, tokyo DateTime('Asia/Tokyo'), "
        "ms DateTime64(3, 'Asia/Tokyo'), cs Nullable(DateTime64(2)), ns DateTime64(9), "
        "day Date, day32 Date32, missing DateTime) ENGINE = MergeTree ORDER BY id"
    )
    naive = pd.Series(pd.to_datetime(["2024-03-01 10:20:30.456789123", "1999-12-31 23:59:59.995"]))
    aware = naive.dt.tz_localize("UTC").dt.tz_convert(_MSK)
    pdf = pd.DataFrame(
        {
            "id": [1, 2],
            "plain": naive,
            "tokyo": aware,
            "ms": aware,
            "cs": [naive[0], pd.NaT],
            "ns": naive,
            "day": aware,
            "day32": [date(1950, 1, 1), datetime(2024, 3, 1, 1, tzinfo=_MSK)],
            "missing": [naive[0], pd.NaT],
        }
    )

    assert _write(clickhouse_http_test_engine, pdf, table_name) == 2

    rows = clickhouse_client.query(
        "SELECT toUnixTimestamp(plain), toUnixTimestamp(tokyo), toUnixTimestamp64Milli(ms), "
        "toUnixTimestamp64Milli(cs), toUnixTimestamp64Nano(ns), toString(day), toString(day32), "
        f"toUnixTimestamp(missing) FROM `{table_name}` ORDER BY id"
    ).result_rows
    first, second = naive[0].value, naive[1].value
    assert rows == [
        (
            first // 10**9,
            first // 10**9,
            first // 10**6,
            first // 10**7 * 10,
            first,
            "2024-03-01",
            "1950-01-01",
            first // 10**9,
        ),
        (
            second // 10**9,
            second // 10**9,
            second // 10**6,
            None,
            second,
            "1999-12-31",
            "2024-02-29",
            0,
        ),
    ]


def test_unsupported_arrow_types_use_native_insert(
    clickhouse_http_test_engine: sa.Engine, clickhouse_client, table_name: str
) -> None:
    clickhouse_client.command(
        f"CREATE TABLE `{table_name}` (id Int64, tags Array(String), "
        "seen Nullable(DateTime64(3)), day Date, amount Decimal(10, 2), uid UUID) "
        "ENGINE = MergeTree ORDER BY id"
    )
    uid = uuid4()
    pdf = pd.DataFrame(
        {
            "id": [1, 2],
            "tags": [["a", "b"], []],
            "seen": [pd.Timestamp("2024-03-01 10:20:30.4567"), pd.NaT],
            "day": pd.to_datetime(["2024-03-01", "2024-03-02"]),
            "amount": [1.239, -2.5],
            "uid": [uid, uid],
        }
    )

    assert _write(clickhouse_http_test_engine, pdf, table_name) == 2

    rows = clickhouse_client.query(
        "SELECT tags, toUnixTimestamp64Milli(seen), day, amount, uid "
        f"FROM `{table_name}` ORDER BY id"
    ).result_rows
    seen_ms = pd.Timestamp("2024-03-01 10:20:30.456").value // 10**6
    assert rows == [
        (["a", "b"], seen_ms, date(2024, 3, 1), Decimal("1.23"), uid),
        ([], None, date(2024, 3, 2), Decimal("-2.50"), uid),
    ]


def test_out_of_range_datetime_fails_without_writing(
    clickhouse_http_test_engine: sa.Engine, clickhouse_client, table_name: str
) -> None:
    clickhouse_client.command(
        f"CREATE TABLE `{table_name}` (id Int64, seen DateTime) ENGINE = MergeTree ORDER BY id"
    )
    pdf = pd.DataFrame({"id": [1], "seen": [pd.Timestamp("2107-01-01")]})

    with pytest.raises(WriteV4ExecutionError, match="out of range for ClickHouse DateTime"):
        _write(clickhouse_http_test_engine, pdf, table_name)

    assert clickhouse_client.command(f"SELECT count() FROM `{table_name}`") == 0
