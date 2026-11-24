from __future__ import annotations

import json
import logging
import math
import threading
import time
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
import sqlalchemy as sa

from core.db.read_v3 import resolver
from core.db.read_v3.executors import pg as pg_executor
from core.db.read_v3.executors.pg import (
    PostgresReadExecutor,
    _AdbcConnectionPool,
    _arrow_table_to_frame,
    _ArrowPlan,
    _ConnectionFailure,
    _converter_for,
    _differing_options,
    _float4_to_float64,
    _schema_signature,
    _SessionInfo,
    _uuid_strings,
    _with_connect_timeout,
)
from core.db.read_v3.executors.sql import SQLReadExecutor
from core.db.read_v3.models import (
    PartitionStrategy,
    ReadMode,
    ReadSegment,
    ReadV3Plan,
    SegmentDivision,
    ValueKind,
)

_FINGERPRINT = {"server_version_num": "150003", "client_encoding": "UTF8"}
_SESSION = _SessionInfo(
    conninfo="host=localhost password=secret",
    fingerprint=_FINGERPRINT,
    float4_text_ok=True,
    float8_text_ok=True,
)
_KINDS = {
    "int2": ValueKind.NUMERIC,
    "int8": ValueKind.NUMERIC,
    "numeric": ValueKind.NUMERIC,
    "NUMERIC(12, 0)": ValueKind.NUMERIC,
    "float4": ValueKind.NUMERIC,
    "float8": ValueKind.NUMERIC,
    "interval": ValueKind.NUMERIC,
    "bool": ValueKind.BOOL,
    "text": ValueKind.STRING,
    "mood": ValueKind.STRING,
    "date": ValueKind.DATE,
    "timestamp": ValueKind.DATETIME,
    "timestamptz": ValueKind.DATETIME,
    "uuid": ValueKind.UUID,
    "json": ValueKind.JSON,
}


def _field(name: str, arrow_type: pa.DataType, pg_type: str) -> pa.Field:
    return pa.field(name, arrow_type, metadata={b"POSTGRESQL:type": pg_type.encode()})


def _plan(types: dict[str, str], **kwargs) -> ReadV3Plan:
    columns = list(types)
    defaults = {
        "mode": ReadMode.QUERY,
        "dialect": "postgresql",
        "cte_prefix_sql": None,
        "relation_sql": 'FROM "events"',
        "select_exprs": [f'"{column}"' for column in columns],
        "output_columns": columns,
        "partition_key_name": columns[0],
        "partition_key_kind": ValueKind.NUMERIC,
        "strategy": PartitionStrategy.RANGE,
        "segments": [
            ReadSegment(
                label=f"p{index}",
                predicate_sql=f'"{columns[0]}" >= {index * 50}',
                order_by_sql=f'ORDER BY "{columns[0]}" ASC',
                division=SegmentDivision(start=index * 50, end=index * 50 + 49, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
            for index in range(2)
        ],
        "divisions": (0, 50, 99),
        "max_rows_per_partition": 100,
        "partition_key_type_repr": types[columns[0]],
        "index_column_name": columns[0],
        "output_column_kinds": {column: _KINDS[types[column]] for column in columns},
        "output_column_type_repr": dict(types),
        "output_column_sql_names": {column: column for column in columns},
    }
    defaults.update(kwargs)
    return ReadV3Plan(**defaults)


def _strict_values(series: pd.Series) -> list[tuple[str, object]]:
    def _key(value: object) -> tuple[str, object]:
        if value is None or value is pd.NA or value is pd.NaT:
            return (repr(value), None)
        if isinstance(value, float) and math.isnan(value):
            return ("nan", None)
        if isinstance(value, float):
            return ("float", (value, math.copysign(1, value)))
        if isinstance(value, (dict, list)):
            return (type(value).__name__, json.dumps(value))
        return (type(value).__name__, value)

    return [_key(value) for value in series.tolist()]


def _current_and_fast(
    pg_type: str,
    type_repr: str,
    arrow_values: pa.Array,
    python_values: list,
    *,
    enum_types: frozenset[str] = frozenset(),
) -> tuple[pd.Series, pd.Series]:
    """The current path (psycopg values -> DataFrame -> hints) vs the Arrow path (-> hints)."""
    plan = _plan({"id": "int8", "c": type_repr})
    ids = list(range(len(python_values)))
    current = pd.DataFrame(list(zip(ids, python_values, strict=True)), columns=["id", "c"])
    current = SQLReadExecutor._apply_output_type_hints(current, plan, stage="test")
    schema = pa.schema([_field("id", pa.int64(), "int8"), _field("c", arrow_values.type, pg_type)])
    table = pa.table([pa.array(ids, pa.int64()), arrow_values], schema=schema)
    converter = _converter_for(
        schema.field("c"),
        SQLReadExecutor._dtype_for_column(plan, "c"),
        index_helper=False,
        enum_types=enum_types,
        session=_SESSION,
        json_ok=True,
    )
    assert converter is not None
    arrow_plan = _ArrowPlan(
        signature=_schema_signature(schema),
        converters={"id": ("int", "Int64"), "c": (converter, SQLReadExecutor._dtype_for_column(plan, "c"))},
    )
    fast = _arrow_table_to_frame(table, arrow_plan)
    fast = SQLReadExecutor._apply_output_type_hints(fast, plan, stage="test")
    return current["c"], fast["c"]


_ST_JOHNS = ZoneInfo("America/St_Johns")
_UUIDS = [uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"), None, uuid.UUID(int=0)]


@pytest.mark.parametrize(
    ("pg_type", "type_repr", "arrow_values", "python_values"),
    [
        ("int2", "int2", pa.array([1, None, -32768], pa.int16()), [1, None, -32768]),
        ("int8", "int8", pa.array([3, 2**53, -7], pa.int64()), [3, 2**53, -7]),
        (
            "numeric",
            "numeric",
            pa.ExtensionArray.from_storage(
                pa.opaque(pa.string(), "numeric", "PostgreSQL"),
                pa.array(["1.5000", "nan", "-inf", None, "0.1", "1" + "0" * 400]),
            ),
            [Decimal("1.5000"), Decimal("NaN"), Decimal("-Infinity"), None, Decimal("0.1"),
             Decimal("1" + "0" * 400)],
        ),
        (
            "numeric",
            "NUMERIC(12, 0)",
            pa.ExtensionArray.from_storage(
                pa.opaque(pa.string(), "numeric", "PostgreSQL"),
                pa.array(["12", "nan", None, "-999999999999"]),
            ),
            [Decimal("12"), Decimal("NaN"), None, Decimal("-999999999999")],
        ),
        (
            "float4",
            "float4",
            pa.array(np.array([1.1, 15125440512, np.nan, 0, -0.0, np.inf], np.float32)).cast(
                pa.float32()
            ),
            [1.1, 1.5125441e10, float("nan"), 0.0, -0.0, float("inf")],
        ),
        ("float8", "float8", pa.array([0.1, None, -0.0]), [0.1, None, -0.0]),
        ("bool", "bool", pa.array([True, None, False]), [True, None, False]),
        ("bool", "bool", pa.array([True, False]), [True, False]),
        ("text", "text", pa.array(["a", None, "ñ€😀", ""]), ["a", None, "ñ€😀", ""]),
        ("mood", "mood", pa.array(["ok", None]), ["ok", None]),
        (
            "date",
            "date",
            pa.array([date(2024, 1, 1), None, date(1, 1, 1), date(9999, 12, 31)]),
            [date(2024, 1, 1), None, date(1, 1, 1), date(9999, 12, 31)],
        ),
        (
            "timestamp",
            "timestamp",
            pa.array([datetime(1969, 12, 31, 23, 59, 59, 999999), None], pa.timestamp("us")),
            [datetime(1969, 12, 31, 23, 59, 59, 999999), None],
        ),
        (
            "timestamptz",
            "timestamptz",
            pa.array(
                [datetime(2024, 3, 31, 1, 30, tzinfo=UTC), None],
                pa.timestamp("us", tz="UTC"),
            ),
            [datetime(2024, 3, 31, 1, 30, tzinfo=UTC).astimezone(_ST_JOHNS), None],
        ),
        (
            "uuid",
            "uuid",
            pa.ExtensionArray.from_storage(
                pa.uuid(), pa.array([u.bytes if u else None for u in _UUIDS], pa.binary(16))
            ),
            _UUIDS,
        ),
        (
            "json",
            "json",
            pa.ExtensionArray.from_storage(
                pa.json_(pa.string()), pa.array(['{"b": 1, "a": [1, 2]}', None, "null", "[]"])
            ),
            [{"b": 1, "a": [1, 2]}, None, None, []],
        ),
        (
            "json",
            "json",
            pa.ExtensionArray.from_storage(pa.json_(pa.string()), pa.array(["1", None, "2.5"])),
            [1, None, 2.5],
        ),
        (
            "json",
            "json",
            pa.ExtensionArray.from_storage(pa.json_(pa.string()), pa.array(['"x"', None])),
            ["x", None],
        ),
    ],
)
def test_arrow_conversion_matches_current_path(pg_type, type_repr, arrow_values, python_values):
    current, fast = _current_and_fast(
        pg_type, type_repr, arrow_values, python_values, enum_types=frozenset({"mood"})
    )
    assert repr(fast.dtype) == repr(current.dtype)
    assert _strict_values(fast) == _strict_values(current)


@pytest.mark.parametrize(
    ("arrow_field", "target"),
    [
        (_field("c", pa.int32(), "int4"), "float64"),
        (_field("c", pa.int64(), "int4"), "Int64"),
        (_field("c", pa.month_day_nano_interval(), "interval"), "Int64"),
        (_field("c", pa.binary(), "bytea"), "string"),
        (_field("c", pa.time64("us"), "time"), "string"),
        (_field("c", pa.list_(pa.int32()), "_int4"), "Int64"),
        (_field("c", pa.string(), "char"), "string"),
        (_field("c", pa.string(), "unknown_type"), "string"),
        (_field("c", pa.timestamp("us", tz="UTC"), "timestamptz"), "datetime64[ns, UTC]"),
        (_field("c", pa.string(), "json"), "string"),
        (_field("c", pa.float32(), "float4"), "float64"),
    ],
)
def test_converter_rejects_combinations_outside_the_allow_list(arrow_field, target):
    session = _SessionInfo("", _FINGERPRINT, float4_text_ok=False, float8_text_ok=True)
    assert (
        _converter_for(
            arrow_field, target, index_helper=False, enum_types=frozenset(), session=session,
            json_ok=True,
        )
        is None
    )


def test_converter_requires_integer_helper_index_and_default_json_loads():
    def _convert(arrow_field, target, **kwargs):
        options = {"index_helper": False, "json_ok": True, **kwargs}
        return _converter_for(
            arrow_field, target, enum_types=frozenset(), session=_SESSION, **options
        )

    assert _convert(_field("k", pa.int32(), "int4"), "int64", index_helper=True) == "int_index"
    assert _convert(_field("k", pa.string(), "text"), "int64", index_helper=True) is None
    assert _convert(_field("k", pa.date32(), "date"), "int64", index_helper=True) is None
    assert _convert(_field("c", pa.string(), "jsonb"), "object", json_ok=False) is None


def test_static_ineligibility_covers_type_reprs_and_index_rules():
    executor = PostgresReadExecutor(sa.create_engine("postgresql+psycopg://u:p@localhost/db"))
    assert executor._static_ineligibility(_plan({"id": "int8", "c": "text"})) is None
    assert "interval" in executor._static_ineligibility(_plan({"id": "int8", "c": "interval"}))
    assert executor._static_ineligibility(
        _plan({"id": "int8", "c": "text"}, divisions=(Decimal("0.5"), Decimal("9.5")),
              partition_key_type_repr="numeric")
    ) is not None
    helper = _plan(
        {"c": "text"},
        partition_key_name="d",
        partition_key_kind=ValueKind.DATE,
        partition_key_type_repr="date",
        index_column_name="__dvt_partition_key",
    )
    assert "helper index" in executor._static_ineligibility(helper)


def test_build_arrow_plan_keeps_needed_columns_only():
    executor = PostgresReadExecutor(sa.create_engine("postgresql+psycopg://u:p@localhost/db"))
    plan = _plan(
        {"c": "text"},
        strategy=PartitionStrategy.HASH,
        index_column_name="__dvt_partition_bucket",
        partition_key_name="k",
    )
    schema = pa.schema(
        [
            _field("c", pa.string(), "text"),
            _field("__dvt_partition_key", pa.binary(), "bytea"),
            _field("__dvt_partition_bucket", pa.int32(), "int4"),
        ]
    )
    arrow_plan = executor._build_arrow_plan(plan, schema, _SESSION, frozenset())
    assert isinstance(arrow_plan, _ArrowPlan)
    assert dict(arrow_plan.converters) == {
        "c": ("string", "string"),
        "__dvt_partition_bucket": ("int_index", "int64"),
    }
    duplicated = pa.schema([_field("c", pa.string(), "text"), _field("c", pa.string(), "text")])
    assert "duplicate" in executor._build_arrow_plan(plan, duplicated, _SESSION, frozenset())


def test_float4_follows_postgres_bound_exclusive_shortest_text():
    pg_text = ["1.5125441e+10", "-2.2350941e+08", "4.0487088e+07", "1.16746496e+08", "1.1", "1e-45"]
    stored = pa.array(np.array([np.float32(text) for text in pg_text], dtype=np.float32))
    assert _float4_to_float64(pa.chunked_array([stored])).tolist() == [float(t) for t in pg_text]


def test_uuid_strings_handle_nulls_and_slices():
    values = [uuid.uuid4() for _ in range(5)]
    array = pa.array([v.bytes for v in values], pa.binary(16))
    with_null = pa.array([values[0].bytes, None, values[1].bytes], pa.binary(16))
    assert _uuid_strings(pa.chunked_array([array.slice(2)])).to_pylist() == [
        str(v) for v in values[2:]
    ]
    assert _uuid_strings(pa.chunked_array([with_null])).to_pylist() == [
        str(values[0]), None, str(values[1])
    ]


def test_conversion_rejects_values_psycopg_cannot_read():
    plan = _plan({"id": "int8", "c": "timestamp"})
    schema = pa.schema([_field("id", pa.int64(), "int8"), _field("c", pa.timestamp("us"), "timestamp")])
    table = pa.table(
        [pa.array([1, 2]), pa.array([0, np.iinfo(np.int64).max], pa.timestamp("us"))], schema=schema
    )
    arrow_plan = _ArrowPlan(
        _schema_signature(schema),
        {"id": ("int", "Int64"), "c": ("timestamp", SQLReadExecutor._dtype_for_column(plan, "c"))},
    )
    with pytest.raises(ValueError, match="outside the range"):
        _arrow_table_to_frame(table, arrow_plan)


def test_connect_timeout_from_connect_args_is_carried_into_the_url_conninfo():
    built = {"host": "h", "dbname": "d"}
    live = {"host": ("h", None, "PGHOST"), "connect_timeout": ("7", None, "PGCONNECT_TIMEOUT")}
    assert _with_connect_timeout(built, live) == {"host": "h", "dbname": "d", "connect_timeout": "7"}
    in_url = {**built, "connect_timeout": "3"}
    assert _with_connect_timeout(in_url, live) == in_url
    assert _with_connect_timeout(built, {"host": ("h", None, "PGHOST")}) == built


def test_differing_options_compares_with_the_url_only_connection():
    reference = {
        "host": ("h", None, "PGHOST"),
        "hostaddr": ("10.0.0.1", None, "PGHOSTADDR"),
        "password": ("p", None, "PGPASSWORD"),
        "port": ("5432", "5432", "PGPORT"),
        # A default libpq derives itself (no compiled default) is on both connections.
        "sslcertmode": ("allow", None, "PGSSLCERTMODE"),
        "options": (None, None, "PGOPTIONS"),
    }
    assert _differing_options(dict(reference), reference) == []
    assert _differing_options({**reference, "hostaddr": ("10.0.0.2", None, None)}, reference) == []
    with_options = {**reference, "options": ("-c TimeZone=Asia/Tokyo", None, "PGOPTIONS")}
    assert _differing_options(with_options, reference) == ["options"]
    extra = {**reference, "keepalives": ("0", None, None)}
    assert _differing_options(extra, reference) == ["keepalives"]
    assert _differing_options(reference, extra) == ["keepalives"]


# ----- executor with fake ADBC connections -------------------------------------------------


class _FakeCursor:
    def __init__(self, connection: _FakeConnection):
        self.connection = connection

    def execute(self, sql: str, parameters=None) -> None:
        self.connection.statements.append(sql)
        if sql == pg_executor._SESSION_SQL:
            self._result = pa.table({k: [v] for k, v in self.connection.fingerprint.items()})
            return
        if sql == pg_executor._ENUM_SQL:
            self._result = pa.table({"is_enum": [False]})
            return
        result = self.connection.results.pop(0)
        if isinstance(result, Exception):
            raise result
        self._result = result

    def adbc_execute_schema(self, sql: str) -> pa.Schema:
        self.connection.statements.append(f"describe {sql}")
        return self.connection.schema

    def fetch_arrow_table(self) -> pa.Table:
        return self._result

    def close(self) -> None:
        pass


class _FakeConnection:
    def __init__(self, schema: pa.Schema, results: list, fingerprint: dict | None = None):
        self.schema = schema
        self.results = results
        self.fingerprint = fingerprint or dict(_FINGERPRINT)
        self.statements: list[str] = []
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


def _segment_table(ids: list[int]) -> pa.Table:
    schema = pa.schema([_field("id", pa.int64(), "int8"), _field("c", pa.string(), "text")])
    return pa.table([pa.array(ids, pa.int64()), pa.array([f"v{i}" for i in ids])], schema=schema)


def _adbc_error(message: str) -> Exception:
    """The executor's ADBC error type: the driver's needs a status code, the placeholder not."""
    if pg_executor._adbc_dbapi is None:
        return pg_executor._AdbcError(message)
    import adbc_driver_manager

    return pg_executor._AdbcError(message, status_code=adbc_driver_manager.AdbcStatusCode.IO)


def _executor(monkeypatch, connections: list, **kwargs) -> PostgresReadExecutor:
    opened: list = []

    def _connect(conninfo: str, autocommit: bool):
        assert autocommit is True
        connection = connections[len(opened)]
        opened.append(connection)
        if isinstance(connection, Exception):
            raise connection
        return connection

    monkeypatch.setattr(pg_executor, "_adbc_dbapi", type("FakeAdbc", (), {"connect": staticmethod(_connect)}))
    monkeypatch.setattr(resolver, "adbc_available", lambda: True)
    engine = sa.create_engine("postgresql+psycopg://user:secret@localhost:5432/db")
    executor = resolver.resolve_executor(engine, **kwargs)
    assert isinstance(executor, PostgresReadExecutor)
    executor._arrow_off_reason = None
    monkeypatch.setattr(executor, "_probe_session", lambda: _SESSION)
    executor.query_df_calls = []

    def _query_df(sql: str) -> pd.DataFrame:
        executor.query_df_calls.append(sql)
        ids = [0, 1] if "__dvt_cap" in sql and ">= 0" in sql else [50, 51]
        return pd.DataFrame({"id": ids, "c": [f"v{i}" for i in ids]})

    monkeypatch.setattr(executor.sql_runner, "query_df", _query_df)
    executor.opened = opened
    return executor


def _read_all(executor: PostgresReadExecutor, plan: ReadV3Plan) -> list[pd.DataFrame]:
    return [executor.load_partition(plan, segment) for segment in plan.segments]


def test_eligible_plan_reads_segments_through_one_pooled_connection(monkeypatch):
    plan = _plan({"id": "int8", "c": "text"})
    connection = _FakeConnection(
        _segment_table([]).schema, [_segment_table([0, 1]), _segment_table([50])]
    )
    executor = _executor(monkeypatch, [connection])
    first, second = _read_all(executor, plan)
    assert executor.query_df_calls == []
    assert executor.opened == [connection]
    assert sum(s.startswith("describe") for s in connection.statements) == 1
    assert first["c"].tolist() == ["v0", "v1"] and str(first["c"].dtype) == "string"
    assert first.index.tolist() == [0, 1] and repr(first.index.dtype) == "Int64Dtype()"
    assert second["id"].tolist() == [50]


def test_failed_query_rereads_through_query_df_and_discards_the_connection(monkeypatch, caplog):
    plan = _plan({"id": "int8", "c": "text"})
    schema = _segment_table([]).schema
    broken = _FakeConnection(schema, [_adbc_error("server closed the connection")])
    fresh = _FakeConnection(schema, [_segment_table([50, 51])])
    executor = _executor(monkeypatch, [broken, fresh])
    # The describe call borrowed `broken` first; its next query fails.
    with caplog.at_level(logging.WARNING, logger=pg_executor.__name__):
        first, second = _read_all(executor, plan)
    assert len(executor.query_df_calls) == 1
    assert first["id"].tolist() == [0, 1]
    assert second["id"].tolist() == [50, 51]
    assert broken.closed is True
    assert executor.opened == [broken, fresh]
    assert "re-read through query_df" in caplog.text and "secret" not in caplog.text


def test_conversion_error_rereads_the_segment(monkeypatch):
    plan = _plan({"id": "int8", "c": "text"})
    bad = pa.table(
        [pa.array([0, 1], pa.int64()), pa.array([b"\xff", b"ok"], pa.binary()).cast(pa.string(), safe=False)],
        schema=_segment_table([]).schema,
    )
    connection = _FakeConnection(_segment_table([]).schema, [bad, _segment_table([50])])
    executor = _executor(monkeypatch, [connection])
    first, second = _read_all(executor, plan)
    assert len(executor.query_df_calls) == 1
    assert first["c"].tolist() == ["v0", "v1"]
    assert connection.closed is False
    assert second["c"].tolist() == ["v50"]


@pytest.mark.parametrize(
    "first_connection",
    [
        _adbc_error("could not connect to server: password=secret"),
        _FakeConnection(_segment_table([]).schema, [], fingerprint={"server_version_num": "1"}),
    ],
)
def test_connection_level_failure_switches_the_arrow_path_off(monkeypatch, caplog, first_connection):
    plan = _plan({"id": "int8", "c": "text"})
    executor = _executor(monkeypatch, [first_connection])
    with caplog.at_level(logging.WARNING, logger=pg_executor.__name__):
        _read_all(executor, plan)
        _read_all(executor, _plan({"id": "int8", "c": "text"}))
    assert len(executor.query_df_calls) == 4
    assert len(executor.opened) == 1
    assert "Arrow path is off" in caplog.text and "secret" not in caplog.text


def test_ineligible_plan_is_decided_once(monkeypatch):
    plan = _plan({"id": "int8", "c": "text"})
    schema = pa.schema([_field("id", pa.int64(), "int8"), _field("c", pa.string(), "char")])
    connection = _FakeConnection(schema, [])
    executor = _executor(monkeypatch, [connection])
    _read_all(executor, plan)
    assert len(executor.query_df_calls) == 2
    assert sum(s.startswith("describe") for s in connection.statements) == 1
    assert pg_executor._ENUM_SQL in connection.statements  # "char" is looked up, not an enum


def test_statically_ineligible_plan_never_connects(monkeypatch):
    executor = _executor(monkeypatch, [])
    plan = _plan({"id": "int8", "c": "interval"})
    executor._fetch_segment_df("SELECT 1 AS x /* >= 0 __dvt_cap */", plan)
    executor._fetch_segment_df("SELECT 1 AS x /* >= 50 __dvt_cap */", plan)
    assert executor.opened == [] and len(executor.query_df_calls) == 2


def test_small_read_uses_query_df_without_probing_or_connecting(monkeypatch, caplog):
    executor = _executor(monkeypatch, [])
    probes: list[int] = []
    monkeypatch.setattr(executor, "_probe_session", lambda: probes.append(1) or _SESSION)
    plan = _plan({"id": "int8", "c": "text"}, total_rows=pg_executor._MIN_ARROW_ROWS - 1)
    with caplog.at_level(logging.DEBUG, logger=pg_executor.__name__):
        first, second = _read_all(executor, plan)
    assert probes == [] and executor.opened == [] and len(executor.query_df_calls) == 2
    assert first["id"].tolist() == [0, 1] and second["id"].tolist() == [50, 51]
    decisions = [r for r in caplog.records if "read through query_df" in r.getMessage()]
    assert [r.levelno for r in decisions] == [logging.DEBUG]


@pytest.mark.parametrize("total_rows", [pg_executor._MIN_ARROW_ROWS, None])
def test_read_at_the_row_threshold_or_of_unknown_size_uses_arrow(monkeypatch, total_rows):
    plan = _plan({"id": "int8", "c": "text"}, total_rows=total_rows)
    connection = _FakeConnection(
        _segment_table([]).schema, [_segment_table([0, 1]), _segment_table([50])]
    )
    executor = _executor(monkeypatch, [connection])
    first, second = _read_all(executor, plan)
    assert executor.query_df_calls == [] and executor.opened == [connection]
    assert first["id"].tolist() == [0, 1] and second["id"].tolist() == [50]


def test_connection_pool_reuses_discards_and_closes_idle_connections():
    created: list[_FakeConnection] = []

    def _connect():
        created.append(_FakeConnection(pa.schema([]), []))
        return created[-1]

    pool = _AdbcConnectionPool(max_idle=1, idle_close_delay=0.5)
    pool.configure(_connect)
    with pool.acquire() as first:
        pass
    with pool.acquire() as again:
        assert again is first
    with pytest.raises(RuntimeError), pool.acquire() as failing:
        raise RuntimeError("query failed")
    assert failing.closed is True
    barrier = threading.Barrier(2)
    seen = []

    def _use():
        with pool.acquire() as connection:
            seen.append(connection)
            barrier.wait(timeout=5)

    threads = [threading.Thread(target=_use) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert seen[0] is not seen[1]
    assert sum(connection.closed for connection in seen) == 1  # max_idle=1 keeps one
    assert pool.idle_count() == 1
    time.sleep(1.0)
    assert pool.idle_count() == 0 and all(connection.closed for connection in created)


def test_pool_without_configuration_fails_as_a_connection_failure():
    pool = _AdbcConnectionPool(max_idle=1, idle_close_delay=1)
    with pytest.raises(_ConnectionFailure), pool.acquire():
        pass


def test_adbc_available_reflects_the_optional_import(monkeypatch):
    monkeypatch.setattr(pg_executor, "_adbc_dbapi", None)
    assert pg_executor.adbc_available() is False
    monkeypatch.setattr(pg_executor, "_adbc_dbapi", object())
    assert pg_executor.adbc_available() is True
