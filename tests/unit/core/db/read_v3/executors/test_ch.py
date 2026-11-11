from __future__ import annotations

import threading
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pytest
import sqlalchemy as sa

from core.db.read_v3.errors import ReadV3ExecutionError
from core.db.read_v3.executors import ch as ch_executor
from core.db.read_v3.executors.ch import (
    ClickHouseReadExecutor,
    _arrow_table_to_pandas,
    _ArrowColumnSpec,
    _parse_arrow_column_spec,
    _segment_arrow_specs,
)
from core.db.read_v3.models import (
    PartitionStrategy,
    ReadMode,
    ReadSegment,
    ReadV3Plan,
    SegmentDivision,
    ValueKind,
)
from core.db.read_v3.resolver import resolve_executor

_UTC_CLIENT = SimpleNamespace(
    server_tz=SimpleNamespace(zone="UTC"), apply_server_timezone=True, utc_tz_aware=False
)
_MOSCOW_CLIENT = SimpleNamespace(
    server_tz=SimpleNamespace(zone="Europe/Moscow"), apply_server_timezone=True, utc_tz_aware=False
)


class _FakeClient:
    def __init__(self, arrow_table: pa.Table | None = None, df: pd.DataFrame | None = None):
        self.arrow_table = arrow_table
        self.df = df
        self.server_tz = SimpleNamespace(zone="UTC")
        self.apply_server_timezone = True
        self.utc_tz_aware = False
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    def raw_query(self, sql: str, fmt: str | None = None) -> bytes:
        assert fmt == "Arrow"
        self.calls.append(("arrow", sql))
        if isinstance(self.arrow_table, Exception):
            raise self.arrow_table
        sink = pa.BufferOutputStream()
        with pa.ipc.new_file(sink, self.arrow_table.schema) as writer:
            writer.write_table(self.arrow_table)
        return sink.getvalue().to_pybytes()

    def query_df(self, sql: str) -> pd.DataFrame:
        self.calls.append(("query_df", sql))
        return self.df

    def close(self) -> None:
        self.closed = True


def _plan(types: dict[str, str], **kwargs) -> ReadV3Plan:
    columns = list(types)
    defaults = {
        "mode": ReadMode.TABLE,
        "dialect": "clickhouse",
        "cte_prefix_sql": None,
        "relation_sql": "FROM `events`",
        "select_exprs": [f"`{column}`" for column in columns],
        "output_columns": columns,
        "partition_key_name": columns[0],
        "partition_key_kind": ValueKind.NUMERIC,
        "strategy": PartitionStrategy.RANGE,
        "segments": [
            ReadSegment(
                label="p0",
                predicate_sql=f"`{columns[0]}` >= 0",
                order_by_sql=f"ORDER BY `{columns[0]}` ASC",
                division=SegmentDivision(start=0, end=100, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        "divisions": (0, 100),
        "max_rows_per_partition": 100,
        "partition_key_type_repr": types[columns[0]],
        "index_column_name": columns[0],
        "output_column_kinds": dict.fromkeys(columns, ValueKind.NUMERIC),
        "output_column_type_repr": dict(types),
        "output_column_sql_names": {column: column for column in columns},
    }
    defaults.update(kwargs)
    return ReadV3Plan(**defaults)


def _executor(monkeypatch, clients: list[_FakeClient], **kwargs) -> ClickHouseReadExecutor:
    created: list[_FakeClient] = []

    def _create(_client_kwargs):
        client = clients[len(created)]
        created.append(client)
        return client

    monkeypatch.setattr(ch_executor, "create_clickhouse_client", _create)
    engine = sa.create_engine("clickhouse+http://user:secret@localhost:8123/db")
    executor = resolve_executor(engine, **kwargs)
    assert isinstance(executor, ClickHouseReadExecutor)
    executor.created_clients = created
    return executor


@pytest.mark.parametrize(
    ("type_repr", "expected"),
    [
        ("Int8", _ArrowColumnSpec("int", arrow_type=pa.int8())),
        ("Int64", _ArrowColumnSpec("int", arrow_type=pa.int64())),
        ("UInt8", _ArrowColumnSpec("int", arrow_type=pa.uint8())),
        ("UInt64", _ArrowColumnSpec("int", arrow_type=pa.uint64())),
        ("Float32", _ArrowColumnSpec("float", arrow_type=pa.float32())),
        ("Float64", _ArrowColumnSpec("float", arrow_type=pa.float64())),
        ("Bool", _ArrowColumnSpec("bool")),
        ("String", _ArrowColumnSpec("string")),
        ("Date", _ArrowColumnSpec("date")),
        ("Date32", _ArrowColumnSpec("date")),
        ("DateTime", _ArrowColumnSpec("datetime")),
        ("DateTime('Asia/Tokyo')", _ArrowColumnSpec("datetime", timezone="Asia/Tokyo")),
        # Reflected table types quote the timezone twice.
        ("DateTime(''Asia/Tokyo'')", _ArrowColumnSpec("datetime", timezone="Asia/Tokyo")),
        ("DateTime64(3)", _ArrowColumnSpec("datetime")),
        (
            "DateTime64(3, 'Europe/Moscow')",
            _ArrowColumnSpec("datetime", timezone="Europe/Moscow"),
        ),
        ("DateTime64(9, ''UTC'')", _ArrowColumnSpec("datetime", timezone="UTC")),
        ("Decimal(38, 4)", _ArrowColumnSpec("decimal")),
        ("Decimal32(2)", _ArrowColumnSpec("decimal")),
        ("Decimal256(10)", _ArrowColumnSpec("decimal")),
        ("Nullable(Int32)", _ArrowColumnSpec("int", nullable=True, arrow_type=pa.int32())),
        ("LowCardinality(String)", _ArrowColumnSpec("string")),
        ("LowCardinality(Nullable(String))", _ArrowColumnSpec("string", nullable=True)),
        (
            "Nullable(DateTime64(6, 'Asia/Tokyo'))",
            _ArrowColumnSpec("datetime", nullable=True, timezone="Asia/Tokyo"),
        ),
        ("Nullable(Decimal(18, 2))", _ArrowColumnSpec("decimal", nullable=True)),
    ],
)
def test_parse_arrow_column_spec_accepts_allow_listed_types(type_repr, expected) -> None:
    assert _parse_arrow_column_spec(type_repr) == expected


@pytest.mark.parametrize(
    "type_repr",
    [
        "",
        "FixedString(16)",
        "UUID",
        "Nullable(UUID)",
        "Enum8('a' = 1, 'b' = 2)",
        "IPv4",
        "IPv6",
        "Int128",
        "UInt256",
        "Array(Int64)",
        "Map(String, Int64)",
        "Tuple(Int64, String)",
        "Nested(a Int64)",
        "JSON",
        "Object('json')",
        "Point",
        "Ring",
        "AggregateFunction(sum, Int64)",
        "LowCardinality(FixedString(2))",
        "Nullable(Nothing)",
        "DateTime64(10)",
        "Decimal(38)",
    ],
)
def test_parse_arrow_column_spec_rejects_other_types(type_repr) -> None:
    assert _parse_arrow_column_spec(type_repr) is None


def test_segment_arrow_specs_require_every_output_and_selected_key_type() -> None:
    assert set(_segment_arrow_specs(_plan({"id": "Int64", "label": "String"}))) == {"id", "label"}
    assert _segment_arrow_specs(_plan({"id": "Int64", "uid": "UUID"})) is None
    assert _segment_arrow_specs(_plan({"id": "Int64", "label": ""})) is None

    key_plan = _plan(
        {"label": "String"},
        partition_key_name="uid",
        partition_key_type_repr="UUID",
        index_column_name="__dvt_partition_key",
    )
    assert _segment_arrow_specs(key_plan) is None
    key_plan.partition_key_type_repr = "DateTime"
    assert _segment_arrow_specs(key_plan)["__dvt_partition_key"] == _ArrowColumnSpec("datetime")


def _typed_arrow_table() -> pa.Table:
    invalid_free_strings = pa.array(["a", None, "привет"], pa.string())
    columns = {
        "i64": (pa.array([1, 2, 3], pa.int64()), False),
        "n_i32": (pa.array([None, -7, 5], pa.int32()), True),
        "n_u64": (pa.array([18446744073709551615, None, 9007199254740993], pa.uint64()), True),
        "n_i64_no_nulls": (pa.array([1, 2, 3], pa.int64()), True),
        "n_f32": (pa.array([1.5, None, 2.5], pa.float32()), True),
        "f32": (pa.array([1.5, -0.0, 2.5], pa.float32()), False),
        "n_b": (pa.array([True, None, False], pa.bool_()), True),
        "s": (invalid_free_strings, True),
        "lc_s": (pa.array(["x", "y", "x"]).dictionary_encode(), False),
        "d": (pa.array([0, 11016, None], pa.uint16()), True),
        "d32": (pa.array([-25567, 0, 11016], pa.int32()).cast(pa.date32()), False),
        "dt": (pa.array([0, 946728000, 4294967295], pa.uint32()), False),
        "dt_tokyo": (pa.array([1709256030, None, 0], pa.uint32()), True),
        "dt64_msk": (
            pa.array([1709277630123, -1999, 0], pa.timestamp("ms", tz="Europe/Moscow")),
            False,
        ),
        "dec": (
            pa.array([Decimal("1.5000"), None, Decimal("-0.0001")], pa.decimal128(38, 4)),
            True,
        ),
        "__dvt_partition_bucket": (pa.array([0, 0, 1], pa.uint8()), False),
    }
    fields = [
        pa.field(name, array.type, nullable=nullable) for name, (array, nullable) in columns.items()
    ]
    return pa.Table.from_arrays([array for array, _ in columns.values()], schema=pa.schema(fields))


_TYPED_SPECS = {
    "i64": _ArrowColumnSpec("int", arrow_type=pa.int64()),
    "n_i32": _ArrowColumnSpec("int", nullable=True, arrow_type=pa.int32()),
    "n_u64": _ArrowColumnSpec("int", nullable=True, arrow_type=pa.uint64()),
    "n_i64_no_nulls": _ArrowColumnSpec("int", nullable=True, arrow_type=pa.int64()),
    "n_f32": _ArrowColumnSpec("float", nullable=True, arrow_type=pa.float32()),
    "f32": _ArrowColumnSpec("float", arrow_type=pa.float32()),
    "n_b": _ArrowColumnSpec("bool", nullable=True),
    "s": _ArrowColumnSpec("string", nullable=True),
    "LC_S": _ArrowColumnSpec("string"),
    "d": _ArrowColumnSpec("date", nullable=True),
    "d32": _ArrowColumnSpec("date"),
    "dt": _ArrowColumnSpec("datetime"),
    "dt_tokyo": _ArrowColumnSpec("datetime", nullable=True, timezone="Asia/Tokyo"),
    "dt64_msk": _ArrowColumnSpec("datetime", timezone="Europe/Moscow"),
    "dec": _ArrowColumnSpec("decimal", nullable=True),
}


def test_arrow_table_converts_to_query_df_dtypes_and_values() -> None:
    df = _arrow_table_to_pandas(_typed_arrow_table(), _TYPED_SPECS, _UTC_CLIENT)

    assert df.dtypes.astype(str).to_dict() == {
        "i64": "int64",
        "n_i32": "Int32",
        "n_u64": "UInt64",
        "n_i64_no_nulls": "Int64",
        "n_f32": "float64",
        "f32": "float32",
        "n_b": "object",
        "s": "string",
        "lc_s": "string",
        "d": "datetime64[ns]",
        "d32": "datetime64[ns]",
        "dt": "datetime64[ns]",
        "dt_tokyo": "datetime64[ns, Asia/Tokyo]",
        "dt64_msk": "datetime64[ns, Europe/Moscow]",
        "dec": "object",
        "__dvt_partition_bucket": "uint8",
    }
    assert df["s"].dtype == pd.StringDtype()
    assert df["n_i32"].tolist() == [pd.NA, -7, 5]
    assert df["n_u64"].tolist() == [18446744073709551615, pd.NA, 9007199254740993]
    assert df["n_f32"].isna().tolist() == [False, True, False]
    assert df["n_b"].tolist() == [True, None, False]
    assert df["s"].tolist() == ["a", pd.NA, "привет"]
    assert df["lc_s"].tolist() == ["x", "y", "x"]
    assert df["d"].tolist() == [pd.Timestamp("1970-01-01"), pd.Timestamp("2000-02-29"), pd.NaT]
    assert df["d32"].tolist()[0] == pd.Timestamp("1900-01-01")
    assert df["dt"].tolist() == [
        pd.Timestamp("1970-01-01 00:00:00"),
        pd.Timestamp("2000-01-01 12:00:00"),
        pd.Timestamp("2106-02-07 06:28:15"),
    ]
    assert df["dt_tokyo"].tolist()[0] == pd.Timestamp("2024-03-01 10:20:30", tz="Asia/Tokyo")
    assert df["dt_tokyo"].isna().tolist() == [False, True, False]
    assert df["dt64_msk"].tolist()[0] == pd.Timestamp("2024-03-01 10:20:30.123", tz="Europe/Moscow")
    assert df["dt64_msk"].tolist()[1] == pd.Timestamp("1969-12-31 23:59:58.001", tz="UTC")
    assert [None if value is None else str(value) for value in df["dec"]] == [
        "1.5000",
        None,
        "-0.0001",
    ]


def test_datetime_without_column_timezone_uses_client_server_timezone() -> None:
    table = pa.table({"dt": pa.array([0], pa.uint32())})
    spec = {"dt": _ArrowColumnSpec("datetime")}

    moscow = _arrow_table_to_pandas(table, spec, _MOSCOW_CLIENT)["dt"]

    assert str(moscow.dtype) == "datetime64[ns, Europe/Moscow]"
    assert moscow.tolist() == [pd.Timestamp("1970-01-01 03:00:00", tz="Europe/Moscow")]


def test_arrow_values_after_type_hints_match_naive_utc_instants() -> None:
    table = pa.table(
        {
            "dt_tokyo": pa.array([1709256030], pa.uint32()),
            "dt64_msk": pa.array([1709277630123], pa.timestamp("ms", tz="Europe/Moscow")),
        }
    )
    specs = {
        "dt_tokyo": _ArrowColumnSpec("datetime", timezone="Asia/Tokyo"),
        "dt64_msk": _ArrowColumnSpec("datetime", timezone="Europe/Moscow"),
    }
    plan = _plan(
        {"dt_tokyo": "DateTime('Asia/Tokyo')", "dt64_msk": "DateTime64(3, 'Europe/Moscow')"},
        output_column_kinds={"dt_tokyo": ValueKind.DATETIME, "dt64_msk": ValueKind.DATETIME},
    )

    df = _arrow_table_to_pandas(table, specs, _UTC_CLIENT)
    hinted = ClickHouseReadExecutor._apply_output_type_hints(df, plan, stage="test")

    assert hinted["dt_tokyo"].tolist() == [pd.Timestamp("2024-03-01 01:20:30")]
    assert hinted["dt64_msk"].tolist() == [pd.Timestamp("2024-03-01 07:20:30.123")]


def test_fetch_segment_uses_arrow_for_supported_types(monkeypatch) -> None:
    client = _FakeClient(arrow_table=pa.table({"id": pa.array([1, 2], pa.int64())}))
    executor = _executor(monkeypatch, [client])

    df = executor._fetch_segment_df("SELECT 1", _plan({"id": "Int64"}))

    assert client.calls == [("arrow", "SELECT 1")]
    assert df["id"].tolist() == [1, 2]


def test_fetch_segment_falls_back_to_query_df_for_unsupported_type(monkeypatch) -> None:
    expected = pd.DataFrame({"id": [1], "uid": ["00000000-0000-0000-0000-000000000001"]})
    client = _FakeClient(df=expected)
    executor = _executor(monkeypatch, [client])

    df = executor._fetch_segment_df("SELECT 1", _plan({"id": "Int64", "uid": "UUID"}))

    assert client.calls == [("query_df", "SELECT 1")]
    assert df is expected


def test_fetch_segment_rereads_invalid_utf8_through_query_df(monkeypatch) -> None:
    invalid = pa.array([b"\xc3\x28"], pa.binary()).view(pa.string())
    expected = pd.DataFrame({"payload": pd.array(["c328"], dtype=pd.StringDtype())})
    client = _FakeClient(arrow_table=pa.table({"payload": invalid}), df=expected)
    executor = _executor(monkeypatch, [client])

    df = executor._fetch_segment_df("SELECT 1", _plan({"payload": "String"}))

    assert [call for call, _sql in client.calls] == ["arrow", "query_df"]
    assert df is expected


def test_max_rows_per_partition_guard_applies_to_arrow_segments(monkeypatch) -> None:
    client = _FakeClient(arrow_table=pa.table({"id": pa.array(range(4), pa.int64())}))
    executor = _executor(monkeypatch, [client])
    plan = _plan({"id": "Int64"}, max_rows_per_partition=3)

    with pytest.raises(
        ReadV3ExecutionError,
        match=r"Segment 'p0' exceeded max_rows_per_partition=3 \(rows_read=4\)",
    ):
        executor.load_partition(plan, plan.segments[0])

    assert client.calls[0][0] == "arrow"
    assert client.calls[0][1].endswith("LIMIT 4 OFFSET 0")


def test_client_pool_reuses_clients_and_discards_failed_ones(monkeypatch) -> None:
    table = pa.table({"id": pa.array([1], pa.int64())})
    first, second = _FakeClient(arrow_table=table), _FakeClient(arrow_table=table)
    executor = _executor(monkeypatch, [first, second], max_concurrent_queries=2)
    plan = _plan({"id": "Int64"})

    executor._fetch_segment_df("SELECT 1", plan)
    executor._fetch_segment_df("SELECT 2", plan)
    assert executor.created_clients == [first]

    first.arrow_table = RuntimeError("connection reset")
    with pytest.raises(RuntimeError, match="connection reset"):
        executor._fetch_segment_df("SELECT 3", plan)
    assert first.closed is True

    executor._fetch_segment_df("SELECT 4", plan)
    assert executor.created_clients == [first, second]


def test_client_pool_lends_each_client_to_one_thread_and_keeps_its_size(monkeypatch) -> None:
    clients = [_FakeClient() for _ in range(3)]
    executor = _executor(monkeypatch, clients, max_concurrent_queries=2)
    pool = executor._client_pool
    barrier = threading.Barrier(3)
    held: list[_FakeClient] = []
    lock = threading.Lock()

    def _hold() -> None:
        with pool.acquire() as client:
            with lock:
                held.append(client)
            barrier.wait(timeout=5)

    threads = [threading.Thread(target=_hold) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sorted(map(id, held)) == sorted(map(id, clients))
    assert sum(client.closed for client in clients) == 1
    assert len(pool._idle) == 2
