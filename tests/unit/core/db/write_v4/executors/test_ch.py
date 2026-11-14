from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
import sqlalchemy as sa

from core.db.write_v4 import WriteMode, WriteRequest, WriteTarget
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors import ch as ch_module
from core.db.write_v4.executors.ch import ClickHouseWriteExecutor

_MSK = timezone(timedelta(hours=3))


class _CHType(sa.types.UserDefinedType):
    """Renders a ClickHouse type string like a reflected clickhouse-sqlalchemy column type."""

    cache_ok = True

    def __init__(self, spec: str) -> None:
        self.spec = spec

    def get_col_spec(self, **kw) -> str:
        return self.spec


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def insert_arrow(self, table: str, arrow_table: pa.Table, settings=None) -> None:
        call = {"table": table, "data": arrow_table, "settings": settings}
        self.calls.append(("insert_arrow", call))

    def insert(self, **kwargs) -> None:
        self.calls.append(("insert", kwargs))


class _RecordingPool:
    def __init__(self) -> None:
        self.client = _RecordingClient()

    @contextmanager
    def acquire(self):
        yield self.client


def _table(*columns: tuple[str, str]) -> sa.Table:
    return sa.Table(
        "events",
        sa.MetaData(),
        *(sa.Column(name, _CHType(spec), nullable="Nullable(" in spec) for name, spec in columns),
        schema="db",
    )


def _insert(
    table: sa.Table,
    pdf: pd.DataFrame,
    *,
    rows_per_batch: int | None = None,
    use_async_insert: bool = False,
    **request_kwargs,
) -> tuple[int, list[tuple[str, dict]]]:
    pool = _RecordingPool()
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        rows_per_batch=rows_per_batch,
        **request_kwargs,
    )
    executor = object.__new__(ClickHouseWriteExecutor)
    rows = executor._insert_partition(pool, table, pdf, request, use_async_insert=use_async_insert)
    return rows, pool.client.calls


def _arrow_table(calls: list[tuple[str, dict]]) -> pa.Table:
    [(method, kwargs)] = calls
    assert method == "insert_arrow"
    return kwargs["data"]


def test_typed_columns_are_sent_by_insert_arrow_with_target_types() -> None:
    table = _table(
        ("id", "Int64"),
        ("int_null", "Nullable(Int32)"),
        ("flag", "Bool"),
        ("ratio", "Float64"),
        ("name", "String"),
        ("label", "LowCardinality(String)"),
        ("note", "Nullable(String)"),
        ("day", "Date"),
        ("seen", "DateTime"),
        ("seen_ms", "DateTime64(3, 'UTC')"),
        ("maybe", "Nullable(DateTime64(6))"),
        ("amount", "Decimal(18, 4)"),
    )
    naive = pd.Series(pd.to_datetime(["2024-03-01 10:20:30.456789", "2024-03-02 00:00:00.000000"]))
    pdf = pd.DataFrame(
        {
            "id": [1, 2],
            "int_null": [7.0, np.nan],
            "flag": [True, False],
            "ratio": [0.5, -1.25],
            "name": pd.Series(["a", "b"], dtype="str"),
            "label": ["x", "x"],
            "note": ["n", None],
            "day": naive,
            "seen": naive,
            "seen_ms": naive.dt.tz_localize("UTC").dt.tz_convert(_MSK),
            "maybe": [naive[0], pd.NaT],
            "amount": [1.5, -2.25],
        }
    )

    rows, calls = _insert(table, pdf)

    assert rows == 2
    [(method, kwargs)] = calls
    assert method == "insert_arrow"
    assert kwargs["table"] == "`db`.`events`"
    assert kwargs["settings"] == {"input_format_null_as_default": 1}
    data = kwargs["data"]
    types = dict(zip(data.column_names, data.schema.types, strict=True))
    assert types["id"] == pa.int64()
    assert types["int_null"] == pa.int32()
    assert types["flag"] == pa.bool_()
    assert types["day"] == pa.date32()
    assert types["seen"] == pa.timestamp("s", tz="UTC")
    assert types["seen_ms"] == pa.timestamp("ms", tz="UTC")
    assert types["maybe"] == pa.timestamp("us", tz="UTC")
    assert types["amount"] == pa.decimal128(18, 4)
    assert pa.types.is_large_string(types["name"]) or pa.types.is_string(types["name"])
    values = data.to_pydict()
    assert values["int_null"] == [7, None]
    assert values["note"] == ["n", None]
    assert values["day"] == [date(2024, 3, 1), date(2024, 3, 2)]
    assert values["seen"][0] == datetime(2024, 3, 1, 10, 20, 30, tzinfo=UTC)
    assert values["seen_ms"][0] == datetime(2024, 3, 1, 10, 20, 30, 456000, tzinfo=UTC)
    assert values["maybe"] == [datetime(2024, 3, 1, 10, 20, 30, 456789, tzinfo=UTC), None]
    assert values["amount"] == [Decimal("1.5000"), Decimal("-2.2500")]


def test_datetime_precision_is_floored_and_nanoseconds_are_kept() -> None:
    table = _table(("cs", "DateTime64(2)"), ("ns", "DateTime64(9)"), ("obj", "DateTime64(3)"))
    value = pd.Timestamp("2024-03-01 10:20:30.456789123")
    pdf = pd.DataFrame(
        {
            "cs": [value],
            "ns": [value],
            "obj": pd.Series([datetime(2024, 3, 1, 13, 20, 30, 456789, tzinfo=_MSK)], dtype=object),
        }
    )

    _, calls = _insert(table, pdf)

    data = _arrow_table(calls)
    assert data.column("cs").cast(pa.int64()).to_pylist() == [value.value // 10**7 * 10]
    assert data.column("ns").cast(pa.int64()).to_pylist() == [value.value]
    assert data.column("obj").to_pylist() == [
        datetime(2024, 3, 1, 10, 20, 30, 456000, tzinfo=UTC)
    ]


def test_aware_values_into_date_use_the_utc_date() -> None:
    table = _table(("from_ts", "Date"), ("from_obj", "Nullable(Date32)"))
    pdf = pd.DataFrame(
        {
            "from_ts": pd.Series(pd.to_datetime(["2024-03-01 01:00:00"])).dt.tz_localize(_MSK),
            "from_obj": pd.Series([datetime(2024, 3, 1, 1, tzinfo=_MSK)], dtype=object),
        }
    )

    _, calls = _insert(table, pdf.reindex([0, 1]))

    assert _arrow_table(calls).to_pydict() == {
        "from_ts": [date(2024, 2, 29), None],
        "from_obj": [date(2024, 2, 29), None],
    }


def test_decimal_keeps_driver_truncation_for_floats_objects_and_wide_types() -> None:
    table = _table(
        ("vectorised", "Decimal(10, 2)"),
        ("fallback", "Nullable(Decimal(10, 2))"),
        ("objects", "Decimal(10, 3)"),
        ("wide", "Decimal(50, 10)"),
    )
    wide = Decimal("1234567890123456789012345678901234567890.0123456789")
    pdf = pd.DataFrame(
        {
            "vectorised": [1.25, -3.5, 0.0],
            "fallback": [1.239, -1.239, 0.1 + 0.2],
            "objects": [Decimal("12.3456"), Decimal("-0.0019"), Decimal("1")],
            "wide": [wide, Decimal("0"), Decimal("-1.5")],
        }
    )
    pdf.loc[2, "fallback"] = np.nan

    _, calls = _insert(table, pdf)

    data = _arrow_table(calls)
    assert data.schema.field("wide").type == pa.decimal256(50, 10)
    assert data.to_pydict() == {
        "vectorised": [Decimal("1.25"), Decimal("-3.50"), Decimal("0.00")],
        "fallback": [Decimal("1.23"), Decimal("-1.23"), None],
        "objects": [Decimal("12.345"), Decimal("-0.001"), Decimal("1.000")],
        "wide": [wide, Decimal("0E-10"), Decimal("-1.5000000000")],
    }


def test_numbers_truncate_floats_and_map_bool_from_integers() -> None:
    table = _table(("as_int", "Int64"), ("as_bool", "Bool"), ("as_float", "Float32"))
    pdf = pd.DataFrame({"as_int": [1.9, -1.9], "as_bool": [0, 2], "as_float": [1, 2]})

    _, calls = _insert(table, pdf)

    assert _arrow_table(calls).to_pydict() == {
        "as_int": [1, -1],
        "as_bool": [False, True],
        "as_float": [1.0, 2.0],
    }


def test_strings_normalise_non_string_objects_and_keep_bytes() -> None:
    table = _table(("text", "Nullable(String)"), ("raw", "String"))
    pdf = pd.DataFrame(
        {
            "text": pd.Series([1, None, "x"], dtype=object),
            "raw": pd.Series([b"\x00\xff", "y", b"z"], dtype=object),
        }
    )

    _, calls = _insert(table, pdf)

    data = _arrow_table(calls)
    assert data.column("text").to_pylist() == ["1", None, "x"]
    assert data.schema.field("raw").type == pa.binary()
    assert data.column("raw").to_pylist() == [b"\x00\xff", b"y", b"z"]


@pytest.mark.parametrize(
    ("spec", "values", "message"),
    [
        ("DateTime", [pd.Timestamp("2107-01-01")], "out of range for ClickHouse DateTime"),
        ("DateTime", [pd.Timestamp("1969-12-31 23:59:59")], "out of range for ClickHouse DateTime"),
        ("Date", [pd.Timestamp("2150-01-01")], "out of range for ClickHouse Date"),
        ("Decimal(5, 2)", [1234.5], "out of range for Decimal"),
        ("UInt8", [300], "cannot be converted"),
    ],
)
def test_out_of_range_values_fail_instead_of_wrapping(spec, values, message) -> None:
    table = _table(("value", spec))

    with pytest.raises(WriteV4ExecutionError, match=message):
        _insert(table, pd.DataFrame({"value": values}))


def test_unsupported_column_type_uses_native_insert_for_the_whole_chunk() -> None:
    table = _table(("id", "Int64"), ("tags", "Array(String)"), ("seen", "Nullable(DateTime64(3))"))
    pdf = pd.DataFrame(
        {
            "id": [1, 2],
            "tags": [["a"], []],
            "seen": [pd.Timestamp("2024-03-01 10:20:30.4567"), pd.NaT],
        }
    )

    _, calls = _insert(table, pdf)

    [(method, kwargs)] = calls
    assert method == "insert"
    assert kwargs["table"] == "events"
    assert kwargs["database"] == "db"
    assert kwargs["column_oriented"] is True
    assert kwargs["column_type_names"] == ["Int64", "Array(String)", "Nullable(DateTime64(3))"]
    seen_ms = pd.Timestamp("2024-03-01 10:20:30.456").value // 10**6
    assert kwargs["data"] == [[1, 2], [["a"], []], [seen_ms, None]]


def test_extra_columns_are_dropped_and_missing_nullable_columns_are_omitted() -> None:
    table = _table(("id", "Int64"), ("note", "Nullable(String)"), ("name", "String"))
    pdf = pd.DataFrame({"name": ["a"], "junk": [1], "id": [5]})

    _, calls = _insert(table, pdf, on_extra_df_columns="ignore")

    data = _arrow_table(calls)
    assert data.column_names == ["id", "name"]
    assert data.to_pydict() == {"id": [5], "name": ["a"]}


def test_empty_partition_sends_nothing() -> None:
    table = _table(("id", "Int64"))

    rows, calls = _insert(table, pd.DataFrame({"id": pd.Series([], dtype="int64")}))

    assert rows == 0
    assert calls == []


def test_chunks_follow_rows_per_batch_and_async_settings_are_opt_in() -> None:
    table = _table(("id", "Int64"))

    rows, calls = _insert(
        table, pd.DataFrame({"id": range(5)}), rows_per_batch=2, use_async_insert=True
    )

    assert rows == 5
    assert [kwargs["data"].num_rows for _, kwargs in calls] == [2, 2, 1]
    assert calls[0][1]["settings"] == {
        "input_format_null_as_default": 1,
        "async_insert": 1,
        "wait_for_async_insert": 1,
    }


def test_automatic_chunks_hold_the_byte_target_of_the_row_width(monkeypatch) -> None:
    monkeypatch.setattr(ch_module, "CLICKHOUSE_BATCH_BYTES", 340)
    table = _table(("id", "Int64"), ("note", "String"))
    narrow = pd.DataFrame({"id": range(60), "note": ["x"] * 60})
    wide = pd.DataFrame({"id": range(9), "note": ["x" * 92] * 9})

    _, narrow_calls = _insert(table, narrow)
    _, wide_calls = _insert(table, wide)

    # Arrow bytes per row: 8 (id) + 8 (string offset) + the text, so 17 narrow and 108 wide.
    assert [kwargs["data"].num_rows for _, kwargs in narrow_calls] == [20] * 3
    assert [kwargs["data"].num_rows for _, kwargs in wide_calls] == [3] * 3


def test_automatic_chunks_stop_at_the_row_cap(monkeypatch) -> None:
    monkeypatch.setattr(ch_module, "CLICKHOUSE_MAX_BATCH_ROWS", 4)
    table = _table(("id", "Int64"))

    rows, calls = _insert(table, pd.DataFrame({"id": range(10)}))

    assert rows == 10
    assert [kwargs["data"].num_rows for _, kwargs in calls] == [4, 4, 2]
