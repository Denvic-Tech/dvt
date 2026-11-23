"""PostgreSQL ADBC Arrow segment fetch vs the current psycopg path on a real server.

Every read runs twice, ``pg_arrow_read=True`` and ``False``, and the partitions must be identical:
columns, dtypes, index dtype and values, value types and missing-value kinds.
"""

from __future__ import annotations

import json
import math
import time

import dask
import numpy as np
import pandas as pd
import pytest
import sqlalchemy as sa

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.executors import pg as pg_executor
from core.db.read_v3.executors.pg import PostgresReadExecutor, adbc_available
from core.db.read_v3.executors.sql import SQLReadExecutor
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config

pytestmark = [
    pytest.mark.docker_required,
    pytest.mark.skipif(not adbc_available(), reason="adbc_driver_postgresql is not installed"),
]

_DEFAULT_MIN_ARROW_ROWS = pg_executor._MIN_ARROW_ROWS

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}

_COLUMNS_SQL = """
    id bigint PRIMARY KEY, c_int2 smallint, c_int4 integer, c_int8 bigint,
    c_num numeric(18,4), c_num_free numeric, c_num_int numeric(12,0), c_real real,
    c_double double precision, c_bool boolean, c_text text, c_varchar varchar(8), c_char char(4),
    c_name name, c_date date, c_ts timestamp, c_ts3 timestamp(3), c_tstz timestamptz, c_uuid uuid,
    c_json json, c_jsonb jsonb, c_json_num json, c_json_str jsonb, c_enum pgi_arrow_mood
"""
_TYPE_COLUMNS = [
    "id", "c_int2", "c_int4", "c_int8", "c_num", "c_num_free", "c_num_int", "c_real", "c_double",
    "c_bool", "c_text", "c_varchar", "c_char", "c_name", "c_date", "c_ts", "c_ts3", "c_tstz",
    "c_uuid", "c_json", "c_jsonb", "c_json_num", "c_json_str", "c_enum",
]
_EDGE_ROWS_SQL = f"""
INSERT INTO pgi_arrow_types ({", ".join(_TYPE_COLUMNS)}) VALUES
 (1, 1, 2, 3, 1.5, 1.25, 12, 1.1, 0.1, true, 'a', 'b', 'c', 'n', '2024-01-01',
  '2024-01-01 00:00:01.123456', '2024-01-01 00:00:01.123', '2024-03-31 01:30:00+00',
  'A0EEBC99-9C0B-4EF8-BB6D-6BB9BD380A11', '{{"b":1,"a":[1,2]}}', '{{"b":1,"a":2}}', '1', '"x"',
  'ok'),
 (2, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
  NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL),
 (3, 0, 0, 0, 'NaN', 'NaN', 'NaN', 'NaN', 'NaN', false, '', '', '', '', '1970-01-01',
  '1970-01-01', '1970-01-01', '1970-01-01 00:00:00+00', '00000000-0000-0000-0000-000000000000',
  'null', 'null', '2.5', '""', 'sad'),
 (4, -32768, -2147483648, -9007199254740992, -99999999999999.9999, 'Infinity', -999999999999,
  'Infinity', '-Infinity', true, 'ñ€😀', 'ñ€😀', 'x', 'pgi', '0001-01-01', '0001-01-01 00:00:00',
  '1969-12-31 23:59:59.999', '0001-01-02 00:00:00+00', 'ffffffff-ffff-ffff-ffff-ffffffffffff',
  '[]', '[1, "a", null]', '-0', '"y"', 'happy'),
 (5, 32767, 2147483647, 9007199254740992, 99999999999999.9999, '-Infinity', 999999999999,
  '-0', '-0', false, 'line
break', 'tab	x', 'ab', 'nm', '9999-12-31', '9999-12-31 23:59:59.999999',
  '9999-12-31 23:59:59.999', '9999-12-30 23:59:59.999999+00',
  '123e4567-e89b-12d3-a456-426614174000', '"just a string"', '{{"nested":{{"k":[1.5,2]}}}}',
  '1e300', '"z"', 'ok'),
 (6, 7, 7, 7, 0.0001, '0.{"0" * 400}1', 0, 15125440512, 0.30000000000000004, true, 'x', 'y',
  'z', 'w', '2000-02-29', '1900-01-01 12:00:00.5', '2262-04-11 23:47:16.854',
  '1918-03-31 21:59:59.999999+03', 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12', '123', '12345678901234567890',
  '0.1', '"\\u00e9"', 'sad'),
 (7, 8, 8, 8, -0.0001, '1{"0" * 400}', -0, 3.4028235e38, 1.7976931348623157e308, false,
  repeat('long', 500), 'v', 'v', 'v', '1582-10-04', '1582-10-15 00:00:00',
  '2024-02-29 23:59:59.999', '2024-10-27 01:30:00+01', 'b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13',
  'true', 'false', '-7', '"\\""', 'happy'),
 (8, 9, 9, 9, 123.4567, '123456789012345678901234567890.123456789012345678901234567890',
  123456789012, 1e-45, 5e-324, true, 'q', 'q', 'q', 'q', '2024-12-31', '2024-12-31 23:59:59',
  '2024-12-31 23:59:59', '2024-12-31 23:59:59-12', 'c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a14',
  '{{"a": 1, "a": 2}}', '{{"a": 1, "a": 2}}', '3', '"q"', 'ok')
"""
_GENERATED_ROWS_SQL = """
INSERT INTO pgi_arrow_types (id, c_int2, c_int4, c_int8, c_num, c_num_free, c_num_int, c_real,
  c_double, c_bool, c_text, c_varchar, c_char, c_name, c_date, c_ts, c_ts3, c_tstz, c_uuid,
  c_json, c_jsonb, c_json_num, c_json_str, c_enum)
SELECT g, mod(g, 30000)::smallint, g * 7, g::bigint * 1000003, (g * 1.2345)::numeric(18,4),
  (g / 7.0)::numeric, g * 11, (g * 0.37)::real, g / 7.0, mod(g, 3) = 0, md5(g::text),
  left(md5(g::text), 8), left(md5(g::text), 3), md5(g::text)::name, '2000-01-01'::date + g,
  '2000-01-01'::timestamp + g * interval '1 second 1 microsecond',
  '2000-01-01'::timestamp + g * interval '1 millisecond',
  '2000-01-01 00:00:00+00'::timestamptz + g * interval '1 hour 1 microsecond',
  md5(g::text)::uuid, json_build_object('g', g), jsonb_build_object('g', g, 'h', g / 3.0),
  NULL, NULL, (ARRAY['sad', 'ok', 'happy'])[mod(g, 3) + 1]::pgi_arrow_mood
FROM generate_series(100, 2099) AS g
"""


def _missing_kind(value: object) -> str | None:
    if value is None:
        return "None"
    if value is pd.NA:
        return "NA"
    if value is pd.NaT:
        return "NaT"
    if isinstance(value, float) and math.isnan(value):
        return "NaN"
    return None


def _same(left: object, right: object) -> bool:
    left_kind, right_kind = _missing_kind(left), _missing_kind(right)
    if left_kind or right_kind:
        return left_kind == right_kind
    if type(left) is not type(right):
        return False
    if isinstance(left, float):
        return left == right and math.copysign(1, left) == math.copysign(1, right)
    if isinstance(left, (dict, list)):
        return json.dumps(left) == json.dumps(right)
    return bool(left == right)


def _assert_same_partition(actual: pd.DataFrame, expected: pd.DataFrame, label: str) -> None:
    assert list(actual.columns) == list(expected.columns), label
    assert {c: repr(t) for c, t in actual.dtypes.items()} == {
        c: repr(t) for c, t in expected.dtypes.items()
    }, label
    assert repr(actual.index.dtype) == repr(expected.index.dtype), label
    assert actual.index.name == expected.index.name, label
    pairs = [("<index>", actual.index.tolist(), expected.index.tolist())]
    pairs += [(c, actual[c].tolist(), expected[c].tolist()) for c in expected.columns]
    for column, left, right in pairs:
        assert len(left) == len(right), (label, column)
        bad = [(i, a, b) for i, (a, b) in enumerate(zip(left, right, strict=True)) if not _same(a, b)]
        assert not bad, (label, column, bad[:3])


@pytest.fixture(scope="module")
def pg_url(postgres_container) -> sa.URL:
    return sa.make_url(postgres_container.get_connection_url())


def _engine(url: sa.URL, application_name: str, **query: str) -> sa.Engine:
    return sa.create_engine(url.update_query_dict({"application_name": application_name, **query}))


@pytest.fixture(scope="module")
def pg_tables(pg_url):
    engine = _engine(pg_url, "pgi_arrow_setup")
    drop = (
        "DROP TABLE IF EXISTS pgi_arrow_types, pgi_arrow_small, pgi_arrow_nulls, pgi_arrow_empty, "
        "pgi_arrow_inelig, pgi_arrow_bad_ts, pgi_arrow_bad_date, pgi_arrow_bigint; "
        "DROP TYPE IF EXISTS pgi_arrow_mood"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(drop)
        connection.exec_driver_sql("CREATE TYPE pgi_arrow_mood AS ENUM ('sad', 'ok', 'happy')")
        for table in ("pgi_arrow_types", "pgi_arrow_small", "pgi_arrow_nulls", "pgi_arrow_empty"):
            connection.exec_driver_sql(f"CREATE TABLE {table} ({_COLUMNS_SQL})")
        connection.exec_driver_sql(_EDGE_ROWS_SQL)
        connection.exec_driver_sql(_GENERATED_ROWS_SQL)
        connection.exec_driver_sql(
            "INSERT INTO pgi_arrow_small SELECT * FROM pgi_arrow_types WHERE id IN (1, 2, 3, 5)"
        )
        connection.exec_driver_sql("INSERT INTO pgi_arrow_nulls (id) VALUES (1), (2), (3)")
        connection.exec_driver_sql(
            "CREATE TABLE pgi_arrow_inelig (id bigint PRIMARY KEY, c_interval interval, "
            "c_bytea bytea, c_time time, c_arr int[], c_char1 \"char\")"
        )
        connection.exec_driver_sql(
            "INSERT INTO pgi_arrow_inelig VALUES (1, '1 day', '\\x00ff', '12:00', '{1,2}', 'a'), "
            "(2, NULL, NULL, NULL, NULL, NULL)"
        )
        connection.exec_driver_sql("CREATE TABLE pgi_arrow_bad_ts (id bigint PRIMARY KEY, ts timestamp)")
        connection.exec_driver_sql(
            "INSERT INTO pgi_arrow_bad_ts VALUES (1, '2024-01-01'), (2, 'infinity'), (3, '2024-01-02')"
        )
        connection.exec_driver_sql("CREATE TABLE pgi_arrow_bad_date (id bigint PRIMARY KEY, d date)")
        connection.exec_driver_sql(
            "INSERT INTO pgi_arrow_bad_date VALUES (1, '2024-01-01'), (2, '0044-03-15 BC')"
        )
        connection.exec_driver_sql("CREATE TABLE pgi_arrow_bigint (id bigint PRIMARY KEY, v bigint)")
        connection.exec_driver_sql(
            "INSERT INTO pgi_arrow_bigint VALUES (1, 9007199254740993), (2, NULL)"
        )
        connection.exec_driver_sql(
            "ANALYZE pgi_arrow_types, pgi_arrow_small, pgi_arrow_nulls, pgi_arrow_empty, "
            "pgi_arrow_inelig, pgi_arrow_bad_ts, pgi_arrow_bad_date, pgi_arrow_bigint"
        )
    yield
    with engine.begin() as connection:
        connection.exec_driver_sql(drop)
    engine.dispose()


@pytest.fixture
def arrow_calls(monkeypatch) -> list[int]:
    calls: list[int] = []
    original = pg_executor._arrow_table_to_frame

    def _counting(table, arrow_plan):
        calls.append(table.num_rows)
        return original(table, arrow_plan)

    monkeypatch.setattr(pg_executor, "_arrow_table_to_frame", _counting)
    return calls


@pytest.fixture(autouse=True)
def arrow_for_small_reads(monkeypatch) -> None:
    """The test tables are small: read them through Arrow regardless of their row count."""
    monkeypatch.setattr(pg_executor, "_MIN_ARROW_ROWS", 0)


def _partitions(engine: sa.Engine, *, arrow: bool, mode: str, **plan_kwargs):
    planner = resolve_planner(mode)
    plan = planner.build_plan(engine=engine, **plan_kwargs, **STRICT_PARTITIONING_KWARGS)
    executor = resolve_executor(engine, max_concurrent_queries=2, pg_arrow_read=arrow)
    assert isinstance(executor, PostgresReadExecutor if arrow else SQLReadExecutor)
    ddf = frame_from_executor(executor, plan)
    parts = dask.compute(*ddf.to_delayed(), scheduler="threads", num_workers=4)
    return plan, executor, list(parts)


def _outcome(engine: sa.Engine, *, arrow: bool, mode: str, **plan_kwargs):
    try:
        return "ok", _partitions(engine, arrow=arrow, mode=mode, **plan_kwargs)[2]
    except Exception as exc:
        return "error", (type(exc), str(exc))


def _assert_same_outcome(engine: sa.Engine, *, mode: str, **plan_kwargs) -> str:
    fast = _outcome(engine, arrow=True, mode=mode, **plan_kwargs)
    current = _outcome(engine, arrow=False, mode=mode, **plan_kwargs)
    assert fast[0] == current[0], (fast, current)
    if fast[0] == "error":
        assert fast[1] == current[1]
    else:
        assert len(fast[1]) == len(current[1])
        for index, (actual, expected) in enumerate(zip(fast[1], current[1], strict=True)):
            _assert_same_partition(actual, expected, f"partition {index}")
    return fast[0]


def _assert_same_read(engine: sa.Engine, *, mode: str, **plan_kwargs):
    plan, executor, fast = _partitions(engine, arrow=True, mode=mode, **plan_kwargs)
    _, _, current = _partitions(engine, arrow=False, mode=mode, **plan_kwargs)
    assert len(fast) == len(current) == len(plan.segments)
    for index, (actual, expected) in enumerate(zip(fast, current, strict=True)):
        _assert_same_partition(actual, expected, f"partition {index}")
    return plan, executor, fast


@pytest.mark.parametrize("mode", ["table", "query"])
@pytest.mark.parametrize("select_key", [True, False])
def test_type_matrix_range_read_is_identical(pg_url, pg_tables, arrow_calls, mode, select_key):
    engine = _engine(pg_url, "pgi_arrow_matrix", connect_timeout="10")
    columns = _TYPE_COLUMNS if select_key else _TYPE_COLUMNS[1:]
    source = (
        {"table_name": "pgi_arrow_types", "columns": columns}
        if mode == "table"
        else {"query": f"SELECT {', '.join(_TYPE_COLUMNS)} FROM pgi_arrow_types", "columns": columns}
    )
    plan, _, fast = _assert_same_read(
        engine, mode=mode, partition_col="id", npartitions=4, **source
    )
    assert plan.strategy.value == "range"
    assert ("id" in plan.output_columns) is select_key
    assert sum(arrow_calls) == sum(len(part) for part in fast) == 2008
    engine.dispose()


@pytest.mark.parametrize("mode", ["table", "query"])
def test_hash_read_with_empty_buckets_is_identical(pg_url, pg_tables, arrow_calls, mode):
    engine = _engine(pg_url, "pgi_arrow_hash")
    source = (
        {"table_name": "pgi_arrow_small"}
        if mode == "table"
        else {"query": f"SELECT {', '.join(_TYPE_COLUMNS)} FROM pgi_arrow_small"}
    )
    plan, _, fast = _assert_same_read(
        engine, mode=mode, partition_col="c_text", npartitions=8, **source
    )
    assert plan.strategy.value == "hash"
    assert plan.index_column_name == plan.hash_bucket_alias
    assert any(len(part) == 0 for part in fast)
    assert sum(arrow_calls) == 4
    engine.dispose()


def test_custom_grouping_index_literal_read_is_identical(pg_url, pg_tables, arrow_calls):
    engine = _engine(pg_url, "pgi_arrow_grouping")
    plan, _, _ = _assert_same_read(
        engine,
        mode="table",
        table_name="pgi_arrow_types",
        partition_col="c_text",
        partition_grouping={"mode": "prefix", "length": 1},
    )
    assert all(segment.index_literal is not None for segment in plan.segments)
    assert sum(arrow_calls) == 2008
    engine.dispose()


@pytest.mark.parametrize("precision", ["Seconds", "Nanoseconds"])
def test_datetime_precision_read_is_identical(pg_url, pg_tables, arrow_calls, precision):
    engine = _engine(pg_url, "pgi_arrow_precision")
    # Rows 4, 5 and 7 hold dates outside datetime64[ns]; both paths fail on them.
    source = (
        {"mode": "query", "query": "SELECT * FROM pgi_arrow_types WHERE id NOT IN (4, 5, 7)"}
        if precision == "Nanoseconds"
        else {"mode": "table", "table_name": "pgi_arrow_types"}
    )
    _assert_same_read(
        engine, partition_col="id", npartitions=3, datetime_precision=precision, **source
    )
    assert sum(arrow_calls) == (2005 if precision == "Nanoseconds" else 2008)
    assert _assert_same_outcome(
        engine, mode="table", table_name="pgi_arrow_types", partition_col="id", npartitions=3,
        datetime_precision="Nanoseconds",
    ) == "error"
    engine.dispose()


@pytest.mark.parametrize("mode", ["table", "query"])
def test_all_null_and_empty_tables_are_identical(pg_url, pg_tables, arrow_calls, mode):
    engine = _engine(pg_url, "pgi_arrow_nulls")
    # Query mode infers the kind of name and enum columns from sample values, which fails
    # planning for all-NULL columns on both paths.
    columns = _TYPE_COLUMNS if mode == "table" else [
        column for column in _TYPE_COLUMNS if column not in {"c_name", "c_enum"}
    ]
    for table in ("pgi_arrow_nulls", "pgi_arrow_empty"):
        source = (
            {"table_name": table, "columns": columns}
            if mode == "table"
            else {"query": f"SELECT {', '.join(columns)} FROM {table}"}
        )
        _assert_same_read(engine, mode=mode, partition_col="id", npartitions=2, **source)
    assert sum(arrow_calls) == 3
    engine.dispose()


def test_non_utc_session_time_zone_is_identical(pg_url, pg_tables, arrow_calls):
    engine = _engine(pg_url, "pgi_arrow_tz", options="-c TimeZone=America/St_Johns")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SHOW TimeZone").scalar() == "America/St_Johns"
    for mode, source in [
        ("table", {"table_name": "pgi_arrow_types"}),
        ("query", {"query": "SELECT id, c_tstz, c_tstz AT TIME ZONE 'UTC' AS utc_wall, c_ts, c_date "
                            "FROM pgi_arrow_types"}),
    ]:
        _assert_same_read(engine, mode=mode, partition_col="id", npartitions=3, **source)
    assert sum(arrow_calls) == 2 * 2008
    engine.dispose()


@pytest.mark.parametrize("mode", ["table", "query"])
def test_ineligible_types_use_query_df_and_are_identical(pg_url, pg_tables, arrow_calls, mode):
    engine = _engine(pg_url, "pgi_arrow_inelig")
    outcomes = []
    for column in ("c_interval", "c_bytea", "c_time", "c_arr", "c_char1"):
        source = (
            {"table_name": "pgi_arrow_inelig", "columns": ["id", column]}
            if mode == "table"
            else {"query": f"SELECT id, {column} FROM pgi_arrow_inelig"}
        )
        outcomes.append(
            _assert_same_outcome(engine, mode=mode, partition_col="id", npartitions=1, **source)
        )
    assert "ok" in outcomes
    assert arrow_calls == []
    engine.dispose()


@pytest.mark.parametrize(("table", "column"), [("pgi_arrow_bad_ts", "ts"), ("pgi_arrow_bad_date", "d")])
def test_value_failing_only_at_conversion_ends_in_the_current_error(
    pg_url, pg_tables, arrow_calls, table, column
):
    engine = _engine(pg_url, "pgi_arrow_bad")
    outcome = _assert_same_outcome(
        engine, mode="table", table_name=table, columns=["id", column], partition_col="id",
        npartitions=1,
    )
    assert outcome == "error"
    assert len(arrow_calls) == 1  # converted once, failed, re-read through query_df
    engine.dispose()


def test_bigint_with_nulls_is_exact_on_both_paths(pg_url, pg_tables, arrow_calls):
    engine = _engine(pg_url, "pgi_arrow_bigint")
    _, _, parts = _assert_same_read(
        engine, mode="table", table_name="pgi_arrow_bigint", partition_col="id", npartitions=1
    )
    assert arrow_calls == [2]
    assert parts[0]["v"].tolist() == [9007199254740993, pd.NA]
    _, _, current = _partitions(
        engine, arrow=False, mode="table", table_name="pgi_arrow_bigint", partition_col="id",
        npartitions=1,
    )
    assert current[0]["v"].tolist() == [9007199254740993, pd.NA]
    engine.dispose()


def test_small_read_keeps_query_df_by_default(pg_url, pg_tables, arrow_calls, monkeypatch):
    monkeypatch.setattr(pg_executor, "_MIN_ARROW_ROWS", _DEFAULT_MIN_ARROW_ROWS)
    engine = _engine(pg_url, "pgi_arrow_small_read")
    _, executor, _ = _assert_same_read(
        engine, mode="table", table_name="pgi_arrow_types", partition_col="id", npartitions=4
    )
    assert arrow_calls == []
    assert executor._session is None and executor._pool.idle_count() == 0
    engine.dispose()


def test_connect_args_outside_the_url_keep_query_df(pg_url, pg_tables, arrow_calls):
    engine = sa.create_engine(
        pg_url.update_query_dict({"application_name": "pgi_arrow_cargs"}),
        connect_args={"options": "-c TimeZone=Asia/Tokyo"},
    )
    _assert_same_read(
        engine, mode="table", table_name="pgi_arrow_small", partition_col="id", npartitions=2
    )
    assert arrow_calls == []
    engine.dispose()


def test_no_reader_session_outlives_the_read(pg_url, pg_tables, arrow_calls):
    application_name = "pgi_arrow_sessions"
    engine = _engine(pg_url, application_name)
    observer = _engine(pg_url, "pgi_arrow_observer")
    count_sql = (
        "SELECT count(*) FROM pg_stat_activity WHERE application_name = "
        f"'{application_name}' AND pid <> pg_backend_pid()"
    )
    _, executor, _ = _partitions(
        engine, arrow=True, mode="table", table_name="pgi_arrow_types", partition_col="id",
        npartitions=6,
    )
    assert sum(arrow_calls) == 2008
    engine.dispose()  # the SQLAlchemy pool of the current path
    with observer.connect() as connection:
        open_sessions = connection.exec_driver_sql(count_sql).scalar()
    assert executor._pool.idle_count() >= 1
    assert open_sessions == executor._pool.idle_count()
    time.sleep(pg_executor._IDLE_CLOSE_DELAY_SEC + 1.5)
    assert executor._pool.idle_count() == 0
    with observer.connect() as connection:
        assert connection.exec_driver_sql(count_sql).scalar() == 0
    observer.dispose()


def test_float4_values_match_postgres_text(pg_url, pg_tables):
    engine = _engine(pg_url, "pgi_arrow_float4")
    values = np.frombuffer(np.random.default_rng(5).bytes(4 * 50_000), dtype=np.uint32)
    floats = values.view(np.float32)
    floats = floats[np.isfinite(floats)]
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS pgi_arrow_f4")
        connection.exec_driver_sql("CREATE TABLE pgi_arrow_f4 (id bigint PRIMARY KEY, v real)")
        raw = connection.connection.driver_connection
        with raw.cursor() as cursor, cursor.copy("COPY pgi_arrow_f4 (id, v) FROM STDIN") as copy:
            for position, value in enumerate(floats.tolist()):
                copy.write_row((position, value))
    try:
        _assert_same_read(
            engine, mode="table", table_name="pgi_arrow_f4", partition_col="id", npartitions=2
        )
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE pgi_arrow_f4")
        engine.dispose()
