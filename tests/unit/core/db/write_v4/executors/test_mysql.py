from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

import dask.dataframe as dd
import numpy as np
import pandas as pd
import pyarrow as pa
import pymysql
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import pymysql as mysql_pymysql

from core.db.write_v4 import WriteMode, WriteRequest, WriteTarget
from core.db.write_v4.dialects import MySQLWriteDialect
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors import mysql as mysql_module
from core.db.write_v4.executors.mysql import (
    MYSQL_BATCH_BYTES,
    MYSQL_MAX_BATCH_ROWS,
    MYSQL_STATEMENT_BYTES,
    MysqlTarget,
    MysqlWriteExecutor,
    build_mysql_columns,
    build_mysql_target,
    inherited_values,
    mysql_batch_rows,
    mysql_column_values,
    mysql_insert_error,
    mysql_statement_bytes,
    timestamp_text,
)
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.resolver import resolve_executor


def _literal_renderer():
    connection = pymysql.Connection(defer_connect=True)
    connection.server_status = 0
    return connection.literal


_LITERAL = _literal_renderer()


def _old_path_values(series: pd.Series) -> list:
    """Values ``SQLWriteExecutor`` hands to PyMySQL for one column (normalize + to_dict)."""
    frame = series.to_frame("v")
    records = frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")
    return [record["v"] for record in records]


# --- type allow-list ---------------------------------------------------------------------------


def _catalog_row(column, data_type, *, table_type="BASE TABLE", extra=""):
    return {"table_type": table_type, "column_name": column, "data_type": data_type, "extra": extra}


def test_build_mysql_target_maps_families_and_excludes_generated_columns() -> None:
    target = build_mysql_target(
        [
            _catalog_row("id", "bigint", extra="auto_increment"),
            _catalog_row("name", "varchar"),
            _catalog_row("doc", "json"),
            _catalog_row("kind", "enum"),
            _catalog_row("tags", "set"),
            _catalog_row("pos", "point"),
            _catalog_row("total", "int", extra="VIRTUAL GENERATED"),
            _catalog_row("payload", "blob"),
        ],
        max_allowed_packet=64 * 1024 * 1024,
    )

    assert target.reason is None
    assert target.families == {"id": "int", "name": "string", "payload": "binary"}
    assert target.unsupported_columns(["id", "doc", "kind", "tags", "pos", "total"]) == [
        "doc",
        "kind",
        "tags",
        "pos",
        "total",
    ]


@pytest.mark.parametrize(
    ("rows", "reason"),
    [([], "not found"), ([_catalog_row("id", "int", table_type="VIEW")], "VIEW is not a table")],
)
def test_build_mysql_target_rejects_missing_tables_and_views(rows, reason) -> None:
    target = build_mysql_target(rows, max_allowed_packet=64 * 1024 * 1024)

    assert reason in target.reason
    assert target.families == {}


def test_statement_bytes_stay_below_max_allowed_packet() -> None:
    assert mysql_statement_bytes(64 * 1024 * 1024) == MYSQL_STATEMENT_BYTES
    assert mysql_statement_bytes(1024 * 1024) == 1024 * 1024 - 1024
    assert mysql_statement_bytes(1500) == 1024


# --- value parity with the inherited path ------------------------------------------------------

_NS = pd.to_datetime(
    [
        "2020-01-01 00:00:00.0000017",
        "1969-12-31 23:59:59.9999995",
        None,
        "2024-02-29 23:30:00",
        "1999-12-31 23:59:59.999",
        "2020-06-01 12:00:00.000001",
    ],
    format="ISO8601",
).astype("datetime64[ns]")

_PARITY_SERIES = {
    "int64": pd.Series([0, -(2**63), 2**63 - 1], dtype="int64"),
    "int8": pd.Series([-128, 0, 127], dtype="int8"),
    "uint64": pd.Series([0, 2**64 - 1, 5], dtype="uint64"),
    "bool": pd.Series([True, False, True]),
    "float64": pd.Series([0.1, np.nan, -0.0, 1e300, 5e-324, 1 / 3]),
    "float32": pd.Series([0.1, np.nan, 16777217.0], dtype="float32"),
    "Int64": pd.Series([1, None, -5], dtype="Int64"),
    "boolean": pd.Series([True, None, False], dtype="boolean"),
    "Float64": pd.Series([0.5, None, 2.0], dtype="Float64"),
    "string": pd.Series(["a", None, "", "it's \\ %s"], dtype="string"),
    "string_pyarrow": pd.Series(["a", None, "\U0001f600"], dtype=pd.StringDtype("pyarrow")),
    "str_default": pd.Series(["a", None, "b"]),
    "object_str": pd.Series(["a", None, np.nan, ""], dtype=object),
    "decimal": pd.Series([Decimal("1.50"), None, Decimal("1E+2")], dtype=object),
    "date": pd.Series([date(2020, 1, 2), None], dtype=object),
    "datetime_object": pd.Series([datetime(2020, 1, 2, 3, 4, 5, 6), None], dtype=object),
    "time": pd.Series([time(1, 2, 3, 4), None], dtype=object),
    "timedelta_object": pd.Series([timedelta(days=1, microseconds=5), None], dtype=object),
    "datetime64_ns": pd.Series(_NS),
    "datetime64_us": pd.Series(_NS.astype("datetime64[us]")),
    "datetime64_ms": pd.Series(_NS.astype("datetime64[ms]")),
    "datetime64_s": pd.Series(_NS.astype("datetime64[s]")),
    "datetime64_us_wide": pd.Series(
        np.array(["1000-01-01T00:00:00.5", "9999-12-31T23:59:59.999999", "NaT"], dtype="M8[us]")
    ),
    "datetime64_s_old": pd.Series(np.array(["0999-12-31T00:00:00", "NaT"], dtype="M8[s]")),
    "datetime_tz": pd.Series(_NS.tz_localize("Europe/Moscow")),
    "timedelta64": pd.Series(pd.to_timedelta(["1s", None])),
    "arrow_int": pd.Series([1, None], dtype=pd.ArrowDtype(pa.int64())),
    "arrow_decimal": pd.Series([Decimal("1.50"), None], dtype=pd.ArrowDtype(pa.decimal128(10, 2))),
    "arrow_date": pd.Series([date(2020, 1, 2), None], dtype=pd.ArrowDtype(pa.date32())),
    "arrow_timestamp": pd.Series(
        [datetime(2020, 1, 2, 3, 4, 5, 6), None], dtype=pd.ArrowDtype(pa.timestamp("us"))
    ),
    "category": pd.Series(["x", None, "y"], dtype="category"),
    "uuid": pd.Series([uuid.UUID(int=1), None], dtype=object),
    "bytes": pd.Series([b"a\x00", None, bytearray(b"x")], dtype=object),
}


@pytest.mark.parametrize("name", list(_PARITY_SERIES))
def test_column_values_render_the_same_literals_as_the_inherited_path(name) -> None:
    series = _PARITY_SERIES[name]
    old = _old_path_values(series)

    assert [_LITERAL(value) for value in mysql_column_values(series)] == [
        _LITERAL(value) for value in old
    ]
    assert [_LITERAL(value) for value in inherited_values(series)] == [
        _LITERAL(value) for value in old
    ]


def test_typed_columns_skip_object_boxing() -> None:
    assert mysql_column_values(pd.Series([1, 2], dtype="int32")) == [1, 2]
    assert type(mysql_column_values(pd.Series([1], dtype="int32"))[0]) is int
    assert mysql_column_values(pd.Series([0.5, np.nan])) == [0.5, None]
    assert mysql_column_values(pd.Series(["a", None], dtype="string")) == ["a", None]
    assert mysql_column_values(pd.Series(_NS[:3])) == [
        "2020-01-01 00:00:00.000001700",
        "1969-12-31 23:59:59.999999500",
        None,
    ]


@pytest.mark.parametrize("unit", ["ns", "us", "ms", "s"])
def test_timestamp_text_equals_str_of_timestamp(unit) -> None:
    rng = np.random.default_rng(7)
    low, high = (-(2**62), 2**62) if unit == "ns" else (-30_000_000_000, 250_000_000_000)
    scale = {"ns": 1, "us": 1_000_000, "ms": 1_000, "s": 1}[unit]
    ticks = rng.integers(low, high, 2_000) * (scale if unit != "ns" else 1)
    ticks[::7] = ticks[::7] // 1_000 * 1_000  # whole microseconds
    ticks[::11] = ticks[::11] // 10**9 * 10**9  # whole seconds for ns
    values = ticks.astype(f"datetime64[{unit}]")
    values[::13] = np.datetime64("NaT", unit)
    series = pd.Series(values)

    expected = [None if pd.isna(v) else str(v) for v in series.astype(object)]
    assert timestamp_text(series) == expected


def test_binary_columns_take_bytes_like_values_only() -> None:
    frame = pd.DataFrame(
        {
            "b": pd.Series([b"a", bytearray(b"b"), memoryview(b"c"), None], dtype=object),
            "s": pd.Series(["x", None, "z", "w"], dtype=object),
        }
    )

    assert build_mysql_columns(frame, ["b"], {"b": "binary"}) == [[b"a", b"b", b"c", None]]
    with pytest.raises(mysql_module._ConversionError, match="column 's'"):
        build_mysql_columns(frame, ["s"], {"s": "binary"})


# --- error wrapping ----------------------------------------------------------------------------


def test_insert_error_keeps_the_server_code_and_explains_row_numbers() -> None:
    message = str(
        mysql_insert_error(pymysql.err.IntegrityError(1062, "Duplicate entry '5'"), "events")
    )

    assert "MySQL INSERT into 'events' failed: (1062) Duplicate entry '5'" in message
    assert "multi-row INSERT statement" in message
    assert "rolled back" in message
    assert "TypeError: bad" in str(mysql_insert_error(TypeError("bad"), "events"))


# --- executor wiring ---------------------------------------------------------------------------


def _engine_stub(name: str, driver: str):
    return SimpleNamespace(dialect=SimpleNamespace(name=name, driver=driver))


def test_resolver_selects_bulk_insert_only_for_pymysql_with_the_switch_on() -> None:
    engine = sa.create_engine("mysql+pymysql://user:password@localhost:1/db")

    assert type(resolve_executor(engine)) is MysqlWriteExecutor
    assert type(resolve_executor(engine, mysql_bulk_insert=False)) is SQLWriteExecutor
    assert type(resolve_executor(sa.create_engine("mariadb+pymysql://u:p@h:1/db"))) is (
        MysqlWriteExecutor
    )
    assert type(resolve_executor(_engine_stub("mysql", "mysqldb"))) is SQLWriteExecutor


class _FakeCursor:
    def __init__(self, log: dict, error: Exception | None) -> None:
        self._log = log
        self._error = error
        self.max_stmt_length = 1024000

    def executemany(self, statement: str, rows) -> None:
        self._log["calls"].append((statement, self.max_stmt_length, list(rows)))
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
        connect_error: Exception | None = None,
    ) -> None:
        self.dialect = mysql_pymysql.dialect()
        self.log = {"calls": [], "closed": 0, "commits": 0, "rollbacks": 0}
        self._error = error
        self._catalog_rows = list(catalog_rows)
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
        packet = SimpleNamespace(scalar_one=lambda: 2 * 1024 * 1024)
        yield SimpleNamespace(
            execute=lambda statement, params: rows, exec_driver_sql=lambda statement: packet
        )


def _table(name_type: sa.types.TypeEngine | None = None) -> sa.Table:
    return sa.Table(
        "events",
        sa.MetaData(),
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.String(20) if name_type is None else name_type),
    )


_EVENTS = MysqlTarget({"id": "int", "name": "string"}, {"id": "bigint", "name": "varchar"}, 4096)


def _executor(engine, target: MysqlTarget | None = _EVENTS) -> MysqlWriteExecutor:
    executor = MysqlWriteExecutor(engine, MySQLWriteDialect())
    if target is not None:
        executor._targets["events"] = target
    return executor


def _request(rows_per_batch: int | None = 2) -> WriteRequest:
    return WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        rows_per_batch=rows_per_batch,
    )


def _frame(rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame({"id": range(rows), "name": [f"n{i}" for i in range(rows)]})


def test_one_transaction_per_partition_with_rows_per_batch_rows_per_executemany() -> None:
    engine = _FakeEngine()

    written = _executor(engine)._insert_partition(_table(), _frame(5), _request(rows_per_batch=2))

    assert written == 5
    assert (engine.log["commits"], engine.log["rollbacks"], engine.log["closed"]) == (1, 0, 1)
    statement = "INSERT INTO events (id, name) VALUES (%s, %s)"
    assert engine.log["calls"] == [
        (statement, 4096, [(0, "n0"), (1, "n1")]),
        (statement, 4096, [(2, "n2"), (3, "n3")]),
        (statement, 4096, [(4, "n4")]),
    ]


def test_automatic_executemany_calls_hold_the_byte_target(monkeypatch) -> None:
    engine = _FakeEngine()
    assert _executor(engine)._insert_partition(_table(), _frame(5), _request(None)) == 5
    assert len(engine.log["calls"]) == 1

    # 8 bytes of id plus an 8-byte string offset and 2 characters of name: 18 bytes per row.
    monkeypatch.setattr(mysql_module, "MYSQL_BATCH_BYTES", 36)
    engine = _FakeEngine()
    assert _executor(engine)._insert_partition(_table(), _frame(5), _request(None)) == 5
    assert [len(rows) for _statement, _max, rows in engine.log["calls"]] == [2, 2, 1]


def test_batch_rows_honour_rows_per_batch_or_the_byte_target_within_the_partition() -> None:
    assert mysql_batch_rows(1_000, 62_500, 200) == 1_000
    assert mysql_batch_rows(1, 62_500, 200) == 1
    assert mysql_batch_rows(1_000, 500, 200) == 500
    assert mysql_batch_rows(None, 10_000_000, 8_000) == MYSQL_BATCH_BYTES // 8_000
    assert mysql_batch_rows(None, 10_000_000, 100) == MYSQL_MAX_BATCH_ROWS
    assert mysql_batch_rows(None, 500, 100) == 500
    assert mysql_batch_rows(1, 0, 100) == 1


@pytest.mark.parametrize(
    "error",
    [
        pymysql.err.IntegrityError(1062, "Duplicate entry '3' for key 'PRIMARY'"),
        pymysql.err.ProgrammingError("inf can not be used with MySQL"),
        TypeError("not all arguments converted"),
    ],
)
def test_insert_errors_are_wrapped_not_retried_and_roll_back_the_partition(
    monkeypatch, error
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine(error=error)

    with pytest.raises(WriteV4ExecutionError, match="MySQL INSERT into 'events' failed"):
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
    executor = _executor(engine, MysqlTarget({"id": "int"}, {"id": "bigint", "name": "json"}, 4096))

    with caplog.at_level(logging.WARNING, logger=mysql_module.__name__):
        assert executor._insert_partition(_table(), _frame(3), _request()) == 3
        assert executor._insert_partition(_table(), _frame(2), _request()) == 2

    assert len(calls) == 2
    assert engine.log["calls"] == []
    warnings = [record.getMessage() for record in caplog.records]
    assert len(warnings) == 1 and "name (json)" in warnings[0]


@pytest.mark.parametrize("name_type", [sa.JSON(), sa.Enum("a", "b", name="kind")])
def test_columns_with_a_sqlalchemy_bind_processor_keep_the_inherited_path(
    monkeypatch, name_type
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()

    assert _executor(engine)._insert_partition(_table(name_type), _frame(2), _request()) == 2
    assert len(calls) == 1
    assert engine.log["calls"] == []


def test_conversion_without_parity_sends_only_that_partition_to_the_inherited_path(
    monkeypatch,
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    executor = _executor(
        engine, MysqlTarget({"id": "int", "name": "binary"}, {"name": "blob"}, 4096)
    )
    bad = pd.DataFrame({"id": [1], "name": pd.Series(["text"], dtype=object)})
    good = pd.DataFrame({"id": [2], "name": pd.Series([b"raw"], dtype=object)})

    assert executor._insert_partition(_table(sa.LargeBinary()), bad, _request()) == 1
    assert executor._insert_partition(_table(sa.LargeBinary()), good, _request()) == 1
    assert len(calls) == 1
    assert engine.log["calls"][0][2] == [(2, b"raw")]


def test_catalog_lookup_reads_the_table_once_and_caps_statements_by_the_packet() -> None:
    engine = _FakeEngine(
        catalog_rows=[_catalog_row("id", "bigint"), _catalog_row("name", "varchar")]
    )
    executor = _executor(engine, target=None)

    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert executor._insert_partition(_table(), _frame(3), _request()) == 3
    assert engine.catalog_lookups == 1
    assert {max_stmt for _statement, max_stmt, _rows in engine.log["calls"]} == {
        2 * 1024 * 1024 - 1024
    }


def test_failed_catalog_lookup_disables_the_bulk_path(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    error = sa.exc.DBAPIError("SELECT", {}, pymysql.err.OperationalError(1142, "denied"))
    engine = _FakeEngine(connect_error=error)
    executor = _executor(engine, target=None)

    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert executor._insert_partition(_table(), _frame(3), _request()) == 3
    assert "catalog lookup failed" in executor._disabled_reason
    assert engine.catalog_lookups == 1
    assert len(calls) == 2


def test_default_only_insert_keeps_the_inherited_path(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    table = sa.Table("events", sa.MetaData(), sa.Column("id", sa.BigInteger, primary_key=True))

    assert _executor(engine)._insert_partition(table, pd.DataFrame(index=range(2)), _request()) == 2
    assert len(calls) == 1
    assert engine.log["calls"] == []


def test_execute_appends_every_partition_through_the_bulk_path(monkeypatch) -> None:
    engine = _FakeEngine()
    executor = _executor(engine)
    monkeypatch.setattr(executor, "_reflect_table", lambda name, schema: _table())

    result = executor.execute(
        dd.from_pandas(_frame(6), npartitions=3),
        _request(rows_per_batch=None),
        SimpleNamespace(mode="append"),
    )

    assert result.rows_written == 6
    assert engine.log["commits"] == 3
    rows = [row for _statement, _max, batch in engine.log["calls"] for row in batch]
    assert sorted(rows) == [(i, f"n{i}") for i in range(6)]
