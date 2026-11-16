from __future__ import annotations

import math
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import dask.dataframe as dd
import numpy as np
import pandas as pd
import psycopg
import pyarrow as pa
import pytest
import sqlalchemy as sa

from core.db.write_v4 import WriteMode, WriteRequest, WriteTarget
from core.db.write_v4.dialects import PostgresWriteDialect
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors import pg as pg_module, sql as sql_executor_module
from core.db.write_v4.executors.pg import (
    COPY_TYPE_KINDS,
    CopySession,
    CopyTarget,
    PostgresWriteExecutor,
    build_copy_table,
    build_copy_target,
    copy_buffer_rows,
    copy_data_error,
    copy_type_kind,
    float8_numeric_text,
    iter_csv_buffers,
)
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.resolver import resolve_executor

_UTC = CopySession(timezone="UTC")


def _csv(frame: pd.DataFrame, kinds: dict[str, str], session: CopySession = _UTC) -> str:
    columns = list(frame.columns)
    table = build_copy_table(frame, columns, kinds, session, "public.t")
    return b"".join(bytes(buffer) for buffer in iter_csv_buffers(table, 1_000)).decode()


def _lines(frame: pd.DataFrame, kind: str, session: CopySession = _UTC) -> list[str]:
    return _csv(frame, dict.fromkeys(frame.columns, kind), session).splitlines()


# --- type allow-list ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("int2", "int"),
        ("int4", "int"),
        ("int8", "int"),
        ("float4", "float4"),
        ("float8", "float8"),
        ("numeric", "numeric"),
        ("bool", "bool"),
        ("text", "text"),
        ("varchar", "text"),
        ("bpchar", "text"),
        ("date", "date"),
        ("timestamp", "timestamp"),
        ("timestamptz", "timestamptz"),
        ("uuid", "uuid"),
        ("json", None),
        ("jsonb", None),
        ("bytea", None),
        ("interval", None),
        ("time", None),
        ("timetz", None),
        ("_int4", None),
        ("money", None),
        ("unknown", None),
    ],
)
def test_copy_type_kind_allows_only_listed_pg_catalog_base_types(type_name, expected) -> None:
    assert copy_type_kind(type_name, "b", "pg_catalog") == expected


@pytest.mark.parametrize(
    ("type_name", "type_type", "type_schema"),
    [
        ("positive_int", "d", "public"),  # domain over int4
        ("mood", "e", "public"),  # enum
        ("int4range", "r", "pg_catalog"),  # range
        ("hstore", "b", "public"),  # extension base type
        ("int4", "b", "public"),  # shadowing user type
    ],
)
def test_copy_type_kind_rejects_domains_enums_ranges_and_non_catalog_types(
    type_name, type_type, type_schema
) -> None:
    assert copy_type_kind(type_name, type_type, type_schema) is None


def _catalog_row(
    column, type_name, *, relkind="r", rules=False, type_type="b", schema="pg_catalog"
):
    return {
        "relkind": relkind,
        "has_insert_rules": rules,
        "column_name": column,
        "type_name": type_name,
        "type_type": type_type,
        "type_schema": schema,
    }


def test_build_copy_target_lists_unsupported_columns() -> None:
    target = build_copy_target(
        [
            _catalog_row("id", "int8"),
            _catalog_row("payload", "jsonb"),
            _catalog_row("tags", "_text"),
        ]
    )

    assert target.reason is None
    assert target.kinds == {"id": "int"}
    assert target.unsupported_columns(["id", "payload", "tags"]) == ["payload", "tags"]
    assert target.unsupported_columns(["id"]) == []


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([], "not found"),
        ([_catalog_row("id", "int8", relkind="v")], "relation kind 'v'"),
        ([_catalog_row("id", "int8", relkind="f")], "relation kind 'f'"),
        ([_catalog_row("id", "int8", rules=True)], "INSERT rules"),
    ],
)
def test_build_copy_target_rejects_views_foreign_tables_and_rules(rows, reason) -> None:
    target = build_copy_target(rows)

    assert reason in target.reason
    assert target.kinds == {}


def test_build_copy_target_accepts_partitioned_tables() -> None:
    assert build_copy_target([_catalog_row("id", "int4", relkind="p")]).kinds == {"id": "int"}


# --- CSV encoding ------------------------------------------------------------------------------


def test_strings_are_always_quoted_so_empty_and_null_differ() -> None:
    values = ["", "a", 'q"x', "c,d", "n\nl", "r\rx", "b\\s", "Привет", "\\N", "\\.", None, " x "]
    frame = pd.DataFrame({"s": pd.Series(values, dtype=object)})

    assert _csv(frame, {"s": "text"}) == (
        '""\n"a"\n"q""x"\n"c,d"\n"n\nl"\n"r\rx"\n"b\\s"\n"Привет"\n"\\N"\n"\\."\n\n" x "\n'
    )


@pytest.mark.parametrize("dtype", [object, "string", pd.StringDtype("pyarrow")])
def test_string_dtypes_encode_alike(dtype) -> None:
    frame = pd.DataFrame({"s": pd.Series(["x", None, ""], dtype=dtype)})

    assert _lines(frame, "text") == ['"x"', "", '""']


def test_nul_character_is_an_error_not_a_fallback() -> None:
    frame = pd.DataFrame({"s": pd.Series(["ok", "a\x00b"], dtype=object)})

    with pytest.raises(WriteV4ExecutionError, match=r"NUL \(0x00\).*row 2"):
        _csv(frame, {"s": "text"})


def test_integers_with_nulls_and_float_rounding_half_to_even() -> None:
    frame = pd.DataFrame(
        {
            "i": pd.array([1, None, -(2**63)], dtype="Int64"),
            "f": [2.5, np.nan, -0.5],
        }
    )

    assert _csv(frame, {"i": "int", "f": "int"}).splitlines() == [
        "1,2",
        ",",
        "-9223372036854775808,0",
    ]


@pytest.mark.parametrize("values", [[float("inf")], [1e19]])
def test_floats_without_an_integer_value_keep_executemany(values) -> None:
    frame = pd.DataFrame({"f": values})

    with pytest.raises(pg_module._CopyConversionError, match="integer column"):
        _csv(frame, {"f": "int"})


def test_float8_uses_shortest_round_trip_text_and_nan_is_null() -> None:
    values = [0.1, 1 / 3, 1e-7, -0.0, float("inf"), float("nan"), 5e-324]
    lines = _lines(pd.DataFrame({"f": values}), "float8")

    assert lines == ["0.1", "0.3333333333333333", "1e-7", "-0", "inf", "", "5e-324"]
    assert [float(line) for line in lines if line] == [v for v in values if not math.isnan(v)]


def test_float32_source_widens_exactly_for_float8_and_stays_single_for_real() -> None:
    frame = pd.DataFrame({"f": pd.Series([0.1], dtype="float32")})

    assert _lines(frame, "float8") == ["0.10000000149011612"]
    assert _lines(frame, "float4") == ["0.1"]


def test_real_rounds_to_float32_and_rejects_overflow_and_underflow() -> None:
    assert _lines(pd.DataFrame({"f": [16777217.0, 1e-40]}), "float4") == ["16777216", "1e-40"]
    for value in (1e39, 1e-50):
        with pytest.raises(pg_module._CopyConversionError, match="real range"):
            _csv(pd.DataFrame({"f": [value]}), {"f": "float4"})


def test_numeric_from_float_keeps_fifteen_significant_digits() -> None:
    values = np.array(
        [1.2345678901234567, 0.1 + 0.2, 1.005, 123456789012345678.0, 76577.65, 5e-324]
    )
    text = float8_numeric_text(values, np.zeros(len(values), dtype=bool)).to_pylist()

    assert [Decimal(item) for item in text] == [Decimal(format(value, ".15g")) for value in values]
    assert text[1] == "0.3"
    assert text[4] == "76577.65"


def test_numeric_from_float_matches_printf_on_random_values() -> None:
    rng = np.random.default_rng(1)
    values = rng.standard_normal(5_000) * 10.0 ** rng.integers(-300, 300, 5_000)
    values = np.concatenate([values, np.round(rng.random(5_000) * 1e5, 2)])
    text = float8_numeric_text(values, np.zeros(len(values), dtype=bool)).to_pylist()

    assert [Decimal(item) for item in text] == [Decimal(format(value, ".15g")) for value in values]


def test_numeric_from_float_with_infinity_keeps_executemany() -> None:
    with pytest.raises(pg_module._CopyConversionError, match="non-finite"):
        _csv(pd.DataFrame({"f": [1.0, float("inf")]}), {"f": "numeric"})


def test_decimal_objects_keep_their_exact_text_and_nan_is_null() -> None:
    values = [Decimal("1.50"), Decimal("1E+2"), Decimal("NaN"), None, Decimal("-0.000001")]
    frame = pd.DataFrame({"n": pd.Series(values, dtype=object)})

    assert _lines(frame, "numeric") == ['"1.50"', '"1E+2"', "", "", '"-0.000001"']


def test_bool_columns_and_bool_into_text() -> None:
    frame = pd.DataFrame({"b": pd.array([True, None, False], dtype="boolean")})

    assert _lines(frame, "bool") == ["true", "", "false"]
    assert _lines(frame, "text") == ["true", "", "false"]


def test_naive_datetimes_floor_to_microseconds_for_timestamp_date_and_timestamptz() -> None:
    values = pd.to_datetime(
        ["2020-01-01 00:00:00.0000017", "1969-12-31 23:59:59.9999995", None], format="ISO8601"
    )
    frame = pd.DataFrame({"ts": values})

    assert _lines(frame, "timestamp") == [
        "2020-01-01 00:00:00.000001",
        "1969-12-31 23:59:59.999999",
        "",
    ]
    # Naive text: PostgreSQL applies the session time zone to timestamptz like executemany.
    assert _lines(frame, "timestamptz") == _lines(frame, "timestamp")
    assert _lines(frame, "date") == ["2020-01-01", "1969-12-31", ""]


def test_aware_datetimes_use_utc_offset_for_timestamptz_and_session_zone_otherwise() -> None:
    values = pd.to_datetime(["2020-01-01 00:30:00.5", None], format="ISO8601").tz_localize(
        "Europe/Moscow"
    )
    frame = pd.DataFrame({"ts": values})
    kolkata = CopySession(timezone="Asia/Kolkata")

    assert _lines(frame, "timestamptz", kolkata) == ['"2019-12-31 21:30:00.500000+00"', ""]
    assert _lines(frame, "timestamp", kolkata) == ["2020-01-01 03:00:00.500000", ""]
    assert _lines(frame, "date", _UTC) == ["2019-12-31", ""]


@pytest.mark.parametrize("timezone_name", [None, "<+03>-03", "Not/AZone"])
def test_aware_datetimes_into_timestamp_need_a_known_session_zone(timezone_name) -> None:
    frame = pd.DataFrame({"ts": pd.to_datetime(["2020-01-01"]).tz_localize("UTC")})

    with pytest.raises(pg_module._CopyConversionError, match="TimeZone"):
        _csv(frame, {"ts": "timestamp"}, CopySession(timezone=timezone_name))


def test_object_dates_datetimes_and_uuids() -> None:
    frame = pd.DataFrame(
        {
            "d": pd.Series([date(2020, 1, 2), None], dtype=object),
            "t": pd.Series([datetime(2020, 1, 2, 3, 4, 5, 6), None], dtype=object),
            "z": pd.Series(
                [datetime(2020, 1, 2, 5, tzinfo=timezone(timedelta(hours=5))), None], dtype=object
            ),
            "u": pd.Series([uuid.UUID(int=1), None], dtype=object),
        }
    )
    kinds = {"d": "timestamp", "t": "timestamp", "z": "timestamptz", "u": "uuid"}

    assert _csv(frame, kinds).splitlines() == [
        '2020-01-02,2020-01-02 03:04:05.000006,"2020-01-02 00:00:00.000000+00",'
        '"00000000-0000-0000-0000-000000000001"',
        ",,,",
    ]


def test_strings_pass_through_to_every_type_input_function() -> None:
    frame = pd.DataFrame({"v": pd.Series([" 5 ", None], dtype=object)})

    for kind in ("int", "float8", "numeric", "date", "timestamptz", "uuid"):
        assert _lines(frame, kind) == ['" 5 "', ""]


@pytest.mark.parametrize(
    ("values", "dtype", "kind"),
    [
        ([True, False], "bool", "int"),
        ([True, False], "bool", "numeric"),
        ([1, 0], "int64", "bool"),
        (["yes"], object, "bool"),
        ([Decimal("2.5")], object, "int"),
        ([0.5], "float64", "text"),
        ([Decimal("1.5")], object, "text"),
        ([date(2020, 1, 1)], object, "text"),
        ([1, "a"], object, "int"),
        ([b"x"], object, "text"),
        ([timedelta(1)], "timedelta64[ns]", "timestamp"),
    ],
)
def test_combinations_without_parity_keep_executemany(values, dtype, kind) -> None:
    frame = pd.DataFrame({"v": pd.Series(values, dtype=dtype)})

    with pytest.raises(pg_module._CopyConversionError):
        _csv(frame, {"v": kind})


def test_copy_buffer_rows_follow_rows_per_batch_or_the_byte_target(monkeypatch) -> None:
    monkeypatch.setattr(pg_module, "COPY_BUFFER_BYTES", 80)
    ids = pa.table({"id": pa.array(range(100), pa.int64())})

    assert copy_buffer_rows(1_000, ids) == 1_000
    assert copy_buffer_rows(1, ids) == 1
    # 8 Arrow bytes per row: 10 rows per 80-byte buffer, at most the whole partition.
    assert copy_buffer_rows(None, ids) == 10
    assert copy_buffer_rows(None, ids.slice(0, 4)) == 4
    assert copy_buffer_rows(None, ids.slice(0, 0)) == 1


# --- error wrapping ----------------------------------------------------------------------------


class _FakeCopyError(psycopg.errors.UniqueViolation):
    def __init__(self, *, context=None, column=None, detail=None, primary="duplicate key") -> None:
        super().__init__(primary)
        self._fake_diag = SimpleNamespace(
            context=context, column_name=column, message_detail=detail, message_primary=primary
        )

    @property
    def diag(self):
        return self._fake_diag


def test_copy_data_error_names_the_partition_row_and_column() -> None:
    exc = _FakeCopyError(
        context='COPY t, line 7, column we:ird, col: "abcd"', primary="value too long"
    )

    error = copy_data_error(exc, "public.t", ["id", "we:ird, col"])

    assert isinstance(error, WriteV4ExecutionError)
    assert "row 7 of the partition, column 'we:ird, col'" in str(error)
    assert "value too long" in str(error)
    assert "rolled back" in str(error)


def test_copy_data_error_prefers_diag_column_and_finds_line_below_trigger_context() -> None:
    exc = _FakeCopyError(
        context='PL/pgSQL function f() line 3 at RAISE\nCOPY t, line 2: "1,,2"',
        column="v",
        detail="Failing row contains (1, null).",
    )

    message = str(copy_data_error(exc, "public.t", ["id", "v"]))

    assert "row 2 of the partition, column 'v'" in message
    assert "(Failing row contains (1, null).)" in message


# --- executor wiring ---------------------------------------------------------------------------


def _pg_engine(driver: str) -> sa.Engine:
    return sa.create_engine(f"postgresql+{driver}://user:password@localhost:1/db")


def test_resolver_selects_copy_only_for_psycopg3_with_the_switch_on() -> None:
    assert type(resolve_executor(_pg_engine("psycopg"))) is PostgresWriteExecutor
    assert type(resolve_executor(_pg_engine("psycopg"), pg_copy=False)) is SQLWriteExecutor
    # psycopg2 cannot be imported where the system libpq is missing (the Docker images), and the
    # resolver reads only the driver name, so another driver is emulated on a psycopg 3 engine.
    other_driver_engine = _pg_engine("psycopg")
    other_driver_engine.dialect.driver = "psycopg2"
    assert type(resolve_executor(other_driver_engine)) is SQLWriteExecutor
    assert type(resolve_executor(sa.create_engine("sqlite://"))) is SQLWriteExecutor


def test_write_request_enables_pg_copy_by_default() -> None:
    request = WriteRequest(mode=WriteMode.APPEND, target=WriteTarget(table_name="t"))

    assert request.pg_copy is True


class _FakeCopy:
    def __init__(self, log: dict, enter_error: Exception | None) -> None:
        self._log = log
        self._enter_error = enter_error

    def __enter__(self):
        if self._enter_error is not None:
            raise self._enter_error
        return self

    def __exit__(self, *exc_info) -> None:
        self._log["copies_closed"] += 1

    def write(self, buffer) -> None:
        self._log["buffers"].append(bytes(buffer))


class _FakeDriver:
    def __init__(self, log: dict, enter_error: Exception | None = None) -> None:
        self._log = log
        self._enter_error = enter_error
        self.info = SimpleNamespace(
            encoding="utf-8", parameter_status=lambda name: "UTC" if name == "TimeZone" else None
        )

    @contextmanager
    def cursor(self):
        yield SimpleNamespace(copy=self._copy)

    def _copy(self, statement: str) -> _FakeCopy:
        self._log["statements"].append(statement)
        return _FakeCopy(self._log, self._enter_error)


class _FakeEngine:
    def __init__(self, enter_error: Exception | None = None) -> None:
        self.log = {"statements": [], "buffers": [], "copies_closed": 0, "transactions": 0}
        self._driver = _FakeDriver(self.log, enter_error)

    @contextmanager
    def begin(self):
        self.log["transactions"] += 1
        yield SimpleNamespace(connection=SimpleNamespace(driver_connection=self._driver))


def _table() -> sa.Table:
    return sa.Table(
        "events",
        sa.MetaData(),
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Text),
        schema="public",
    )


def _executor(engine) -> PostgresWriteExecutor:
    executor = PostgresWriteExecutor(engine, PostgresWriteDialect())
    executor._copy_targets["public.events"] = CopyTarget(
        {"id": "int", "name": "text"}, {"id": "int8", "name": "text"}
    )
    return executor


def _request(rows_per_batch: int | None = 2) -> WriteRequest:
    return WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        rows_per_batch=rows_per_batch,
    )


def _frame(rows: int = 5) -> pd.DataFrame:
    return pd.DataFrame({"id": range(rows), "name": [f"n{i}" for i in range(rows)]})


def test_one_copy_and_one_transaction_per_partition_with_several_buffers(monkeypatch) -> None:
    engine = _FakeEngine()

    written = _executor(engine)._insert_partition(_table(), _frame(5), _request(rows_per_batch=2))

    assert written == 5
    assert engine.log["transactions"] == 1
    assert engine.log["statements"] == [
        'COPY "public"."events" ("id", "name") FROM STDIN '
        "(FORMAT csv, DELIMITER ',', QUOTE '\"', NULL '', ENCODING 'UTF8')"
    ]
    assert [buffer.decode() for buffer in engine.log["buffers"]] == [
        '0,"n0"\n1,"n1"\n',
        '2,"n2"\n3,"n3"\n',
        '4,"n4"\n',
    ]


def _record_fallback(monkeypatch) -> list[pd.DataFrame]:
    calls: list[pd.DataFrame] = []

    def fallback(self, table, pdf, request):
        calls.append(pdf)
        return len(pdf)

    monkeypatch.setattr(SQLWriteExecutor, "_insert_partition", fallback)
    return calls


def test_unsupported_column_type_sends_partitions_to_executemany(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    executor = _executor(engine)
    executor._copy_targets["public.events"] = CopyTarget(
        {"id": "int"}, {"id": "int8", "name": "jsonb"}
    )

    assert executor._insert_partition(_table(), _frame(3), _request()) == 3
    assert len(calls) == 1
    assert engine.log["statements"] == []


def test_conversion_without_parity_sends_only_that_partition_to_executemany(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    executor = _executor(engine)
    bad = pd.DataFrame({"id": [1.5, float("inf")], "name": ["a", "b"]})

    assert executor._insert_partition(_table(), bad, _request()) == 2
    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert len(calls) == 1
    assert len(engine.log["statements"]) == 1


@pytest.mark.parametrize(
    "sqlstate_error", [psycopg.errors.FeatureNotSupported, psycopg.errors.SyntaxError]
)
def test_server_rejecting_copy_disables_it_for_the_rest_of_the_write(
    monkeypatch, sqlstate_error
) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine(enter_error=sqlstate_error("COPY FROM STDIN is not supported"))
    executor = _executor(engine)

    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert executor._insert_partition(_table(), _frame(3), _request()) == 3
    assert len(calls) == 2
    assert len(engine.log["statements"]) == 1


def test_other_statement_errors_are_wrapped_not_retried(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine(enter_error=psycopg.errors.InsufficientPrivilege("permission denied"))

    with pytest.raises(WriteV4ExecutionError, match="permission denied"):
        _executor(engine)._insert_partition(_table(), _frame(2), _request())
    assert calls == []


def test_sql_ascii_client_encoding_disables_copy(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    engine._driver.info.encoding = "ascii"
    executor = _executor(engine)

    assert executor._insert_partition(_table(), _frame(2), _request()) == 2
    assert executor._copy_disabled_reason == "client_encoding SQL_ASCII"
    assert len(calls) == 1


def test_default_only_insert_keeps_executemany(monkeypatch) -> None:
    calls = _record_fallback(monkeypatch)
    engine = _FakeEngine()
    table = sa.Table(
        "events",
        sa.MetaData(),
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        schema="public",
    )
    # Rows without columns: every target column takes its default.
    rows = pd.DataFrame(index=range(2))

    assert _executor(engine)._insert_partition(table, rows, _request()) == 2
    assert len(calls) == 1
    assert engine.log["statements"] == []


def test_execute_appends_every_partition_through_copy(monkeypatch) -> None:
    engine = _FakeEngine()
    executor = _executor(engine)
    monkeypatch.setattr(executor, "_reflect_table", lambda name, schema: _table())
    request = _request(rows_per_batch=None)
    ddf = dd.from_pandas(_frame(6), npartitions=3)
    plan = SimpleNamespace(mode="append")

    result = executor.execute(ddf, request, plan)

    assert result.rows_written == 6
    assert engine.log["transactions"] == 3
    assert len(engine.log["statements"]) == 3
    rows = b"".join(engine.log["buffers"]).decode().splitlines()
    assert sorted(rows) == sorted(f'{i},"n{i}"' for i in range(6))


_COPY_TYPES = {"id": "int8", "name": "text"}


@pytest.mark.parametrize(
    ("type_names", "requested", "bulk", "disabled", "expected"),
    [
        (_COPY_TYPES, 1, 4, False, 4),
        # None: an explicit worker setting (project, operator override) keeps the write workers.
        (_COPY_TYPES, 1, None, False, 1),
        (_COPY_TYPES, 2, 3, False, 3),
        (_COPY_TYPES, 8, 4, False, 8),
        ({"id": "int8", "name": "jsonb"}, 1, 4, False, 1),
        (_COPY_TYPES, 1, 4, True, 1),
    ],
)
def test_execute_uses_bulk_workers_only_when_the_target_takes_copy(
    monkeypatch, type_names, requested, bulk, disabled, expected
) -> None:
    executor = _executor(_FakeEngine())
    executor._copy_targets["public.events"] = CopyTarget(
        {name: COPY_TYPE_KINDS[t] for name, t in type_names.items() if t in COPY_TYPE_KINDS},
        type_names,
    )
    if disabled:
        executor._copy_disabled_reason = "client_encoding SQL_ASCII"
    monkeypatch.setattr(executor, "_reflect_table", lambda name, schema: _table())
    workers: list[int] = []

    def process(ddf, handler, *, max_workers):
        workers.append(max_workers)
        return 0

    monkeypatch.setattr(sql_executor_module, "process_partitions_bounded", process)
    request = _request().model_copy(update={"write_workers": requested, "bulk_write_workers": bulk})

    executor.execute(
        dd.from_pandas(_frame(4), npartitions=2), request, SimpleNamespace(mode="append")
    )

    assert workers == [expected]
    assert request.write_workers == requested


def test_arrow_decimal_and_nullable_float_sources() -> None:
    frame = pd.DataFrame(
        {
            "a": pd.array([Decimal("1.50"), None], dtype=pd.ArrowDtype(pa.decimal128(10, 2))),
            "f": pd.array([0.25, None], dtype="Float64"),
        }
    )

    assert _csv(frame, {"a": "numeric", "f": "float8"}).splitlines() == ["1.50,0.25", ","]
