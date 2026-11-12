from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import dask.dataframe as dd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyodbc
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.mssql import pyodbc as mssql_pyodbc

from core.db.write_v4 import WriteMode, WriteRequest, WriteTarget
from core.db.write_v4.dialects import MssqlWriteDialect
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors import mssql as mssql_module
from core.db.write_v4.executors.mssql import (
    MSSQL_BATCH_BYTES,
    MSSQL_MIN_BATCH_ROWS,
    MssqlColumn,
    MssqlTarget,
    MssqlWriteExecutor,
    build_mssql_target,
    mssql_batch_rows,
    mssql_insert_error,
    mssql_param,
)
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.resolver import resolve_executor

_TIMESTAMP = (pyodbc.SQL_TYPE_TIMESTAMP, 27, 7)


def _param(values, spec: MssqlColumn, dtype=None):
    series = pd.Series(values, dtype=dtype)
    return mssql_param(series, spec)


def _column(type_name: str, length: int | None = None) -> MssqlColumn:
    return MssqlColumn(mssql_module.MSSQL_TYPE_FAMILIES[type_name], type_name, length)


# --- type allow-list ---------------------------------------------------------------------------


def _catalog_row(column, type_name, *, max_length=8, identity=False, object_type="U "):
    return {
        "object_type": object_type,
        "column_name": column,
        "type_name": type_name,
        "max_length": max_length,
        "precision": 0,
        "scale": 0,
        "is_identity": identity,
    }


def test_build_mssql_target_maps_families_and_character_lengths() -> None:
    target = build_mssql_target(
        [
            _catalog_row("id", "bigint"),
            _catalog_row("n", "nvarchar", max_length=64),
            _catalog_row("nm", "nvarchar", max_length=-1),
            _catalog_row("v", "varchar", max_length=20),
            _catalog_row("c", "nchar", max_length=10),
            _catalog_row("u", "uniqueidentifier", max_length=16),
        ]
    )

    assert target.reason is None
    assert target.columns == {
        "id": MssqlColumn("int", "bigint"),
        "n": MssqlColumn("nvarchar", "nvarchar", 32),
        "nm": MssqlColumn("nvarchar", "nvarchar", None),
        "v": MssqlColumn("varchar", "varchar", 20),
        "c": MssqlColumn("nvarchar", "nchar", 5),
        "u": MssqlColumn("uuid", "uniqueidentifier"),
    }


@pytest.mark.parametrize(
    "type_name",
    [
        "xml",
        "sql_variant",
        "geography",
        "geometry",
        "hierarchyid",
        "image",
        "text",
        "ntext",
        "timestamp",
        "binary",
        "varbinary",
        "money",
        "sysname",
        "my_alias_type",
    ],
)
def test_types_outside_the_allow_list_are_unsupported(type_name) -> None:
    target = build_mssql_target([_catalog_row("id", "int"), _catalog_row("x", type_name)])

    assert target.reason is None
    assert target.unsupported_columns(["id", "x"]) == ["x"]
    assert target.unsupported_columns(["id"]) == []


def test_identity_columns_are_unsupported_only_when_inserted() -> None:
    target = build_mssql_target(
        [_catalog_row("id", "int", identity=True), _catalog_row("v", "int")]
    )

    assert target.unsupported_columns(["id", "v"]) == ["id"]
    assert target.unsupported_columns(["v"]) == []
    assert target.type_names["id"] == "int IDENTITY"


@pytest.mark.parametrize(
    ("rows", "reason"),
    [([], "not found"), ([_catalog_row("id", "int", object_type="V ")], "'V' is not a table")],
)
def test_build_mssql_target_rejects_missing_objects_and_views(rows, reason) -> None:
    target = build_mssql_target(rows)

    assert reason in target.reason
    assert target.columns == {}


# --- parameter conversion ----------------------------------------------------------------------


def test_integers_are_bigint_with_nulls() -> None:
    assert _param([1, None, -(2**63)], _column("int"), "Int64").input_size == (
        pyodbc.SQL_BIGINT,
        0,
        0,
    )
    assert _param([1, None, -(2**63)], _column("int"), "Int64").values == [1, None, -(2**63)]
    assert _param(np.array([2**63 - 1], dtype="uint64"), _column("int")).values == [2**63 - 1]
    assert _param(pa.array([5, None]), _column("float"), pd.ArrowDtype(pa.int16())).values == [
        5,
        None,
    ]


@pytest.mark.parametrize(
    ("values", "dtype"),
    [(np.array([2**63], dtype="uint64"), None), ([2**63, None], object)],
)
def test_integers_outside_bigint_keep_the_inherited_path(values, dtype) -> None:
    with pytest.raises(mssql_module._ConversionError, match="outside bigint"):
        _param(values, _column("int"), dtype)


def test_floats_are_double_with_nan_as_null_and_float32_widened() -> None:
    param = _param([0.1, np.nan, -0.0], _column("decimal"))

    assert param.input_size == (pyodbc.SQL_DOUBLE, 0, 0)
    assert param.values[0] == 0.1 and param.values[1] is None
    assert str(param.values[2]) == "-0.0"
    assert _param(np.array([0.1], dtype="float32"), _column("float")).values == [
        float(np.float32(0.1))
    ]
    assert _param([1.5, None], _column("int"), "Float64").values == [1.5, None]


def test_infinite_floats_keep_the_inherited_path() -> None:
    with pytest.raises(mssql_module._ConversionError, match="infinite"):
        _param([1.0, float("inf")], _column("float"))


def test_decimals_are_numeric_38_with_the_largest_scale() -> None:
    values = [Decimal("1.5"), None, Decimal("-0.0005"), Decimal("1E+2")]
    param = _param(values, _column("decimal"), object)

    assert param.input_size == (pyodbc.SQL_NUMERIC, 38, 4)
    assert param.values == values
    arrow = _param([Decimal("1.50"), None], _column("float"), pd.ArrowDtype(pa.decimal128(10, 2)))
    assert arrow.input_size == (pyodbc.SQL_NUMERIC, 38, 2)
    assert arrow.values == [Decimal("1.50"), None]


def test_decimal_nan_is_null_like_on_the_inherited_path() -> None:
    assert _param([Decimal("NaN"), Decimal("1")], _column("decimal"), object).values == [
        None,
        Decimal("1"),
    ]


@pytest.mark.parametrize("value", [Decimal("Infinity"), Decimal("1E+40"), Decimal("1E-39")])
def test_decimals_beyond_numeric_38_keep_the_inherited_path(value) -> None:
    with pytest.raises(mssql_module._ConversionError):
        _param([Decimal("1"), value], _column("decimal"), object)


def test_bit_takes_booleans_and_integers_zero_and_one() -> None:
    param = _param([True, None, False], _column("bit"), "boolean")

    assert param.input_size == (pyodbc.SQL_BIT, 0, 0)
    assert param.values == [True, None, False]
    assert _param([1, 0, None], _column("bit"), "Int64").values == [True, False, None]
    assert _param([True, False], _column("int")).values == [True, False]


@pytest.mark.parametrize(("values", "dtype"), [([2, 0], "int64"), ([0.0, 1.0], "float64")])
def test_bit_rejects_what_sqlalchemy_rejects(values, dtype) -> None:
    with pytest.raises(mssql_module._ConversionError):
        _param(values, _column("bit"), dtype)


def test_strings_are_declared_with_the_column_length() -> None:
    nvarchar = _param(["", "abc", None], _column("nvarchar", 20), object)
    varchar = _param(["a", None], _column("varchar", 10), "string")

    assert nvarchar.input_size == (pyodbc.SQL_WVARCHAR, 20, 0)
    assert nvarchar.values == ["", "abc", None]
    assert varchar.input_size == (pyodbc.SQL_VARCHAR, 10, 0)
    assert varchar.values == ["a", None]


def test_longer_strings_raise_the_declaration_to_their_utf16_length() -> None:
    # The server trims trailing blanks or raises "would be truncated", as on the inherited path.
    assert _param(["abcdefg"], _column("nvarchar", 5), object).size == 7
    # Non-BMP characters take two UTF-16 code units.
    assert _param(["\U0001f600" * 10], _column("nvarchar", 15), object).size == 20
    assert _param(["ж" * 10], _column("nvarchar", 15), object).size == 15
    assert _param(["x" * 4001], _column("nvarchar", 15), object).size == 0


@pytest.mark.parametrize("length", [None, 2000, 4000])
def test_max_and_long_string_columns_are_declared_as_max(length) -> None:
    assert _param(["a", None], _column("nvarchar", length), object).input_size == (
        pyodbc.SQL_WVARCHAR,
        0,
        0,
    )


def test_strings_into_other_columns_are_nvarchar_sized_by_the_longest_value() -> None:
    for spec in (_column("int"), _column("datetime2"), _column("uniqueidentifier")):
        param = _param([" 5 ", None, "12"], spec, object)
        assert param.input_size == (pyodbc.SQL_WVARCHAR, 3, 0)
        assert param.values == [" 5 ", None, "12"]
    assert _param([None, None], _column("int"), "string").size == 1


def test_naive_datetimes_floor_to_microseconds() -> None:
    values = pd.to_datetime(
        ["2020-01-01 00:00:00.0000017", "1969-12-31 23:59:59.9999995", None], format="ISO8601"
    )
    param = _param(values, _column("datetime2"))

    assert param.input_size == _TIMESTAMP
    assert param.values == [
        datetime(2020, 1, 1, 0, 0, 0, 1),
        datetime(1969, 12, 31, 23, 59, 59, 999999),
        None,
    ]
    assert _param(values, _column("datetimeoffset")).values == param.values


def test_aware_datetimes_keep_wall_time_except_into_datetimeoffset() -> None:
    values = pd.to_datetime(["2020-01-01 00:30:00.5", None], format="ISO8601").tz_localize(
        "Asia/Kolkata"
    )

    assert _param(values, _column("datetime")).values == [
        datetime(2020, 1, 1, 0, 30, 0, 500000),
        None,
    ]
    offset = _param(values, _column("datetimeoffset"))
    assert offset.input_size == (pyodbc.SQL_WVARCHAR, 33, 0)
    assert offset.values == ["2020-01-01 00:30:00.500000 +05:30", None]


def test_object_dates_datetimes_times_and_uuids() -> None:
    dates = _param([date(2020, 1, 2), None], _column("date"), object)
    datetimes = _param([datetime(2020, 1, 2, 3, 4, 5, 6), None], _column("datetime"), object)
    aware = _param(
        [datetime(2020, 1, 2, 5, tzinfo=timezone(timedelta(hours=5))), None],
        _column("datetimeoffset"),
        object,
    )
    times = _param([time(1, 2, 3, 4), None], _column("time"), object)
    uuids = _param([uuid.UUID(int=1), None], _column("uniqueidentifier"), object)

    assert dates.input_size == _TIMESTAMP and dates.values == [datetime(2020, 1, 2), None]
    assert datetimes.values == [datetime(2020, 1, 2, 3, 4, 5, 6), None]
    assert aware.values == ["2020-01-02 05:00:00.000000 +05:00", None]
    assert times.input_size == (pyodbc.SQL_WVARCHAR, 15, 0)
    assert times.values == ["01:02:03.000004", None]
    assert uuids.input_size == (pyodbc.SQL_GUID, 16, 0)
    assert uuids.values == [uuid.UUID(int=1), None]
    arrow_dates = _param([date(2020, 1, 2), None], _column("datetime2"), pd.ArrowDtype(pa.date32()))
    assert arrow_dates.values == [datetime(2020, 1, 2), None]


@pytest.mark.parametrize(
    ("values", "dtype", "type_name"),
    [
        ([0.5], "float64", "nvarchar"),
        ([1], "int64", "varchar"),
        ([True], "bool", "float"),
        ([date(2020, 1, 1)], object, "datetimeoffset"),
        ([date(2020, 1, 1)], object, "time"),
        ([1, "a"], object, "int"),
        ([b"x"], object, "nvarchar"),
        ([timedelta(1)], "timedelta64[ns]", "time"),
        ([uuid.UUID(int=1)], object, "nvarchar"),
        (
            [
                datetime(2020, 1, 1, tzinfo=UTC),
                datetime(2020, 1, 1, tzinfo=timezone(timedelta(hours=1))),
            ],
            object,
            "datetime2",
        ),
        (np.array(["10000-01-01"], dtype="datetime64[s]"), None, "datetime2"),
    ],
)
def test_combinations_without_parity_keep_the_inherited_path(values, dtype, type_name) -> None:
    with pytest.raises(mssql_module._ConversionError):
        _param(values, _column(type_name), dtype)


def test_batch_rows_floor_cap_and_whole_partition() -> None:
    assert mssql_batch_rows(1_000, 62_500, 100) == MSSQL_MIN_BATCH_ROWS
    assert mssql_batch_rows(1_000, 500, 100) == 500
    assert mssql_batch_rows(None, 62_500, 100) == 62_500
    assert mssql_batch_rows(10**6, 10**6, 10_000) == MSSQL_BATCH_BYTES // 10_000
    assert mssql_batch_rows(1, 1, 10**12) == 1


# --- error wrapping ----------------------------------------------------------------------------


def test_insert_error_names_table_rows_and_server_message() -> None:
    exc = pyodbc.IntegrityError(
        "23000", "[23000] [Microsoft][ODBC Driver 18 for SQL Server]Violation of PRIMARY KEY"
    )

    message = str(mssql_insert_error(exc, "dbo.t", 10_000, 20_000))

    assert "MSSQL INSERT into 'dbo.t'" in message
    assert "partition rows 10001-20000" in message
    assert "does not report the failing row" in message
    assert "Violation of PRIMARY KEY" in message and "'23000'" not in message
    assert "rolled back" in message


# --- executor wiring ---------------------------------------------------------------------------


def _engine_stub(name: str, driver: str):
    return SimpleNamespace(dialect=SimpleNamespace(name=name, driver=driver))


def test_resolver_selects_fast_executemany_only_for_pyodbc_with_the_switch_on() -> None:
    engine = sa.create_engine("mssql+pyodbc://user:password@localhost:1/db?driver=x")

    assert type(resolve_executor(engine)) is MssqlWriteExecutor
    assert type(resolve_executor(engine, mssql_fast_executemany=False)) is SQLWriteExecutor
    assert type(resolve_executor(_engine_stub("mssql", "pymssql"))) is SQLWriteExecutor


def test_write_request_enables_both_bulk_switches_by_default() -> None:
    request = WriteRequest(mode=WriteMode.APPEND, target=WriteTarget(table_name="t"))

    assert request.mssql_fast_executemany is True
    assert request.mysql_bulk_insert is True


class _FakeCursor:
    def __init__(self, log: dict, error: Exception | None) -> None:
        self._log = log
        self._error = error
        self.fast_executemany = False

    def setinputsizes(self, sizes) -> None:
        self._log["sizes"].append(list(sizes))

    def executemany(self, statement: str, rows) -> None:
        self._log["calls"].append((statement, self.fast_executemany, list(rows)))
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        self._log["closed"] += 1


class _FakeEngine:
    def __init__(
        self,
        error: Exception | None = None,
        *,
        catalog_rows=(),
        driver_name="libmsodbcsql-18.4.so.1.1",
        connect_error: Exception | None = None,
    ) -> None:
        self.dialect = mssql_pyodbc.dialect()
        self.log = {"sizes": [], "calls": [], "closed": 0, "commits": 0, "rollbacks": 0}
        self._error = error
        self._catalog_rows = list(catalog_rows)
        self._driver_name = driver_name
        self._connect_error = connect_error
        self.catalog_lookups = 0

    @contextmanager
    def begin(self):
        driver = SimpleNamespace(cursor=lambda: _FakeCursor(self.log, self._error))
        try:
            yield SimpleNamespace(connection=SimpleNamespace(driver_connection=driver))
        except BaseException:
            self.log["rollbacks"] += 1
            raise
        self.log["commits"] += 1

    @contextmanager
    def connect(self):
        self.catalog_lookups += 1
        if self._connect_error is not None:
            raise self._connect_error
        rows = [SimpleNamespace(_mapping=row) for row in self._catalog_rows]
        driver = SimpleNamespace(getinfo=lambda info: self._driver_name)
        yield SimpleNamespace(
            connection=SimpleNamespace(driver_connection=driver),
            execute=lambda statement, params: rows,
        )


def _table() -> sa.Table:
    return sa.Table(
        "events",
        sa.MetaData(),
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Unicode(20)),
        schema="dbo",
    )


_EVENTS = MssqlTarget(
    {"id": MssqlColumn("int", "bigint"), "name": MssqlColumn("nvarchar", "nvarchar", 20)},
    {"id": "bigint", "name": "nvarchar"},
)


def _executor(engine, target: MssqlTarget | None = _EVENTS) -> MssqlWriteExecutor:
    executor = MssqlWriteExecutor(engine, MssqlWriteDialect())
    if target is not None:
        executor._targets["dbo.events"] = target
    return executor


def _request(chunksize: int = 2) -> WriteRequest:
    return WriteRequest(
        mode=WriteMode.APPEND, target=WriteTarget(table_name="events"), chunksize=chunksize
    )


def _frame(rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame({"id": range(rows), "name": [f"n{i}" for i in range(rows)]})


def test_one_transaction_per_partition_with_several_executemany_calls(monkeypatch) -> None:
    monkeypatch.setattr(mssql_module, "MSSQL_MIN_BATCH_ROWS", 1)
    engine = _FakeEngine()

    written = _executor(engine)._insert_partition(_table(), _frame(5), _request(chunksize=2))

    assert written == 5
    assert (engine.log["commits"], engine.log["rollbacks"], engine.log["closed"]) == (1, 0, 1)
    statement = "INSERT INTO dbo.events (id, name) VALUES (?, ?)"
    assert engine.log["calls"] == [
        (statement, True, [(0, "n0"), (1, "n1")]),
        (statement, True, [(2, "n2"), (3, "n3")]),
        (statement, True, [(4, "n4")]),
    ]
    # Every call declares every parameter; the declaration does not follow the values.
    declaration = [(pyodbc.SQL_BIGINT, 0, 0), (pyodbc.SQL_WVARCHAR, 20, 0)]
    assert engine.log["sizes"] == [declaration] * 3


def test_chunksize_below_the_floor_sends_one_call(monkeypatch) -> None:
    engine = _FakeEngine()

    assert _executor(engine)._insert_partition(_table(), _frame(5), _request(chunksize=2)) == 5
    assert len(engine.log["calls"]) == 1


def test_driver_errors_are_wrapped_not_retried_and_roll_back_the_partition(
    monkeypatch,
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine(error=pyodbc.DataError("22003", "Arithmetic overflow error"))

    with pytest.raises(WriteV4ExecutionError, match=r"partition rows 1-5.*Arithmetic overflow"):
        _executor(engine)._insert_partition(_table(), _frame(5), _request())

    assert (engine.log["commits"], engine.log["rollbacks"]) == (0, 1)
    assert len(engine.log["calls"]) == 1
    assert calls == []


def _record_fallback(monkeypatch) -> list[pd.DataFrame]:
    calls: list[pd.DataFrame] = []

    def fallback(self, table, pdf, request):
        calls.append(pdf)
        return len(pdf)

    monkeypatch.setattr(SQLWriteExecutor, "_insert_partition", fallback)
    return calls


def test_unsupported_column_type_sends_partitions_to_the_inherited_path(
    monkeypatch, caplog
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    executor = _executor(
        engine, MssqlTarget({"id": MssqlColumn("int", "bigint")}, {"id": "bigint", "name": "xml"})
    )

    with caplog.at_level(logging.WARNING, logger=mssql_module.__name__):
        assert executor._insert_partition(_table(), _frame(3), _request()) == 3
        assert executor._insert_partition(_table(), _frame(2), _request()) == 2

    assert len(calls) == 2
    assert engine.log["calls"] == []
    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1 and "name (xml)" in warnings[0]


def test_conversion_without_parity_sends_only_that_partition_to_the_inherited_path(
    monkeypatch,
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    executor = _executor(engine)
    bad = pd.DataFrame({"id": [1, 2], "name": [0.5, 1.5]})

    assert executor._insert_partition(_table(), bad, _request()) == 2
    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert len(calls) == 1
    assert len(engine.log["calls"]) == 1


def test_catalog_lookup_reads_the_table_once() -> None:
    engine = _FakeEngine(
        catalog_rows=[
            _catalog_row("id", "bigint"),
            _catalog_row("name", "nvarchar", max_length=40),
        ]
    )
    executor = _executor(engine, target=None)

    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert executor._insert_partition(_table(), _frame(3), _request()) == 3
    assert engine.catalog_lookups == 1
    assert len(engine.log["calls"]) == 2


@pytest.mark.parametrize(
    ("engine_kwargs", "reason"),
    [
        ({"driver_name": "libtdsodbc.so"}, "is not Microsoft ODBC Driver"),
        (
            {"connect_error": sa.exc.DBAPIError("SELECT", {}, pyodbc.Error("42000", "denied"))},
            "catalog lookup failed",
        ),
    ],
)
def test_unknown_driver_or_failed_catalog_lookup_disables_the_fast_path(
    monkeypatch, engine_kwargs, reason
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine(
        catalog_rows=[_catalog_row("id", "bigint"), _catalog_row("name", "nvarchar")],
        **engine_kwargs,
    )
    executor = _executor(engine, target=None)

    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert executor._insert_partition(_table(), _frame(3), _request()) == 3
    assert reason in executor._disabled_reason
    assert engine.catalog_lookups == 1
    assert len(calls) == 2
    assert engine.log["calls"] == []


def test_default_only_insert_keeps_the_inherited_path(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    table = sa.Table(
        "events",
        sa.MetaData(),
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        schema="dbo",
    )

    assert _executor(engine)._insert_partition(table, pd.DataFrame(index=range(2)), _request()) == 2
    assert len(calls) == 1
    assert engine.log["calls"] == []


def test_execute_appends_every_partition_through_fast_executemany(monkeypatch) -> None:
    engine = _FakeEngine()
    executor = _executor(engine)
    monkeypatch.setattr(executor, "_reflect_table", lambda name, schema: _table())

    result = executor.execute(
        dd.from_pandas(_frame(6), npartitions=3),
        _request(chunksize=10),
        SimpleNamespace(mode="append"),
    )

    assert result.rows_written == 6
    assert engine.log["commits"] == 3
    rows = [row for _statement, _fast, batch in engine.log["calls"] for row in batch]
    assert sorted(rows) == [(i, f"n{i}") for i in range(6)]
