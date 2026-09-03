from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import mssql
from sqlalchemy.exc import IntegrityError

from core.db.write_v3 import (
    ExtraColumnsMode,
    MissingColumnsMode,
    UpsertConfig,
    WriteMode,
    WriteRequest,
    WriteTarget,
    write_dataframe,
)
from core.db.write_v3.errors import WriteV3ExecutionError, WriteV3PlanningError
from core.db.write_v3.executors.ch import ClickHouseWriteExecutor, _ClickHouseClientPool
from core.db.write_v3.normalize import align_partition_to_table
from core.mapper.factory._db_columns import build_table_from_db_columns
from core.types import DataType, DBColumn


class _FakeBeginContext:
    def __init__(self, executed_sql: list[str]) -> None:
        self._executed_sql = executed_sql

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False

    def execute(self, statement) -> None:
        self._executed_sql.append(str(statement))


class _FakeClickHouseEngine:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []

    def begin(self) -> _FakeBeginContext:
        return _FakeBeginContext(self.executed_sql)


class _FakeClickHouseDialect:
    name = "clickhouse"

    @staticmethod
    def full_table_name(table_name: str, schema_name: str | None) -> str:
        return f"{schema_name}.{table_name}" if schema_name else table_name


def test_write_v3_clickhouse_client_pool_uses_factory_and_reuses_client(monkeypatch) -> None:
    factory_calls: list[dict[str, object]] = []

    class _FakeClient:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    client = _FakeClient()

    def _create_client(client_kwargs):
        factory_calls.append(dict(client_kwargs))
        return client

    monkeypatch.setattr(
        "core.db.write_v3.executors.ch.create_clickhouse_client",
        _create_client,
    )
    pool = _ClickHouseClientPool({"host": "clickhouse.local"}, max_clients=2)

    with pytest.raises(RuntimeError, match="partition failed"), pool.acquire() as first:
        assert first is client
        raise RuntimeError("partition failed")

    with pool.acquire() as reused:
        assert reused is client

    assert factory_calls == [{"host": "clickhouse.local", "compress": True}]
    assert client.closed is False

    pool.close_all()

    assert client.closed is True


def _sorted_rows(rows: list[tuple[object, object]]) -> list[tuple[object, object]]:
    return sorted(rows, key=lambda row: (row[0] is not None, "" if row[0] is None else str(row[0]), str(row[1])))


class _RenderedType(sa.types.TypeEngine):
    cache_ok = True

    def __init__(self, rendered: str) -> None:
        super().__init__()
        self._rendered = rendered

    def __str__(self) -> str:
        return self._rendered


def test_write_v3_sqlite_append_then_upsert_preserves_duplicates_and_nulls(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    first_pdf = pd.DataFrame(
        {
            "business_key": ["one", None, "two"],
            "payload": ["row-1", "null-1", "row-2"],
        }
    )
    first_ddf = dd.from_pandas(first_pdf, npartitions=2)

    append_request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        chunksize=2,
        write_workers=2,
    )
    append_result = write_dataframe(first_ddf, engine, append_request)
    assert append_result.rows_written == 3

    upsert_pdf = pd.DataFrame(
        {
            "business_key": ["two", None, None, "three", "three"],
            "payload": ["row-2-new", "null-2", "null-3", "row-3-a", "row-3-b"],
        }
    )
    upsert_ddf = dd.from_pandas(upsert_pdf, npartitions=2)
    upsert_request = WriteRequest(
        mode=WriteMode.UPSERT,
        target=WriteTarget(table_name="events"),
        upsert=UpsertConfig(key_column="business_key"),
        chunksize=2,
        write_workers=2,
    )
    upsert_result = write_dataframe(upsert_ddf, engine, upsert_request)
    assert upsert_result.rows_written == 5

    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT business_key, payload FROM events")
        ).fetchall()

    assert _sorted_rows(rows) == _sorted_rows(
        [
            ("one", "row-1"),
            ("two", "row-2-new"),
            (None, "null-2"),
            (None, "null-3"),
            ("three", "row-3-a"),
            ("three", "row-3-b"),
        ]
    )


def test_write_v3_missing_table_fails_without_attempting_ddl(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'missing_table.sqlite'}")
    ddf = dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1)

    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="expected_table"),
        chunksize=1,
    )

    with pytest.raises(WriteV3PlanningError, match="writes only to existing tables"):
        write_dataframe(ddf, engine, request)


def test_write_v3_sqlite_append_drops_internal_dvt_columns(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_internal_cols.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    ddf = dd.from_pandas(
        pd.DataFrame(
            {
                "business_key": ["one", "two"],
                "payload": ["a", "b"],
                "__dvt_partition_bucket": [0, 1],
            }
        ),
        npartitions=2,
    )

    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        chunksize=2,
        write_workers=2,
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT business_key, payload FROM events")).fetchall()
    assert sorted(rows) == [("one", "a"), ("two", "b")]


def test_write_v3_sqlite_truncate_replaces_existing_rows(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_truncate.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))
        conn.execute(
            text(
                "INSERT INTO events (business_key, payload) VALUES "
                "('old-1', 'seed-1'), ('old-2', 'seed-2')"
            )
        )

    ddf = dd.from_pandas(
        pd.DataFrame(
            {
                "business_key": ["new-1", "new-2"],
                "payload": ["value-1", "value-2"],
            }
        ),
        npartitions=2,
    )

    request = WriteRequest(
        mode=WriteMode.TRUNCATE,
        target=WriteTarget(table_name="events"),
        chunksize=2,
        write_workers=2,
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT business_key, payload FROM events")).fetchall()
    assert sorted(rows) == [("new-1", "value-1"), ("new-2", "value-2")]


def test_write_v3_sqlite_append_supports_upstream_operation_callbacks(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_callbacks.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    source = dd.from_pandas(
        pd.DataFrame(
            {
                "business_key": ["one", "two", "three"],
                "payload": ["a", "b", "c"],
            }
        ),
        npartitions=2,
    )
    callback_events = {"start": 0, "end": 0}

    def on_start(_meta, operation_id: str) -> None:
        assert operation_id == "write_v3_append_source"
        callback_events["start"] += 1

    def on_end(_meta, operation_id: str) -> None:
        assert operation_id == "write_v3_append_source"
        callback_events["end"] += 1

    ddf = source.add_callbacks(
        on_start=on_start,
        on_end=on_end,
        on_partition=lambda *_args, **_kwargs: None,
        operation_id="write_v3_append_source",
    )

    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        chunksize=2,
        write_workers=2,
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 3
    assert callback_events["start"] == 1
    assert callback_events["end"] == 1


def test_write_v3_sqlite_append_fails_early_on_nulls_in_non_nullable_numeric_columns(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_non_nullable_numeric_nulls.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (id INTEGER NOT NULL, amount REAL NOT NULL, payload TEXT)"))

    ddf = dd.from_pandas(
        pd.DataFrame(
            {
                "id": [1, None],
                "amount": [10.5, None],
                "payload": ["ok", "bad"],
            }
        ),
        npartitions=1,
    )
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        chunksize=2,
        write_workers=1,
    )

    with pytest.raises(WriteV3ExecutionError) as exc_info:
        write_dataframe(ddf, engine, request)

    message = str(exc_info.value)
    assert "contain NULL values" in message
    assert "'id'" in message
    assert "'amount'" in message
    assert "non-nullable numeric columns" in message


def test_write_v3_clickhouse_normalize_partition_drops_internal_dvt_columns() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("business_key", sa.String()),
        sa.Column("payload", sa.String()),
    )
    pdf = pd.DataFrame(
        {
            "business_key": ["one", "two"],
            "payload": ["a", "b"],
            "__dvt_partition_bucket": [0, 1],
        }
    )

    executor = object.__new__(ClickHouseWriteExecutor)
    normalized = executor._normalize_partition(
        pdf,
        table,
        WriteRequest(mode=WriteMode.APPEND, target=WriteTarget(table_name="events")),
    ).normalized

    assert list(normalized.columns) == ["business_key", "payload"]
    assert normalized.to_dict(orient="records") == [
        {"business_key": "one", "payload": "a"},
        {"business_key": "two", "payload": "b"},
    ]


def test_write_v3_clickhouse_normalize_partition_ignores_extra_columns_when_configured() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("business_key", sa.String()),
        sa.Column("payload", sa.String()),
    )
    pdf = pd.DataFrame(
        {
            "business_key": ["one"],
            "payload": ["a"],
            "extra_payload": ["drop-me"],
        }
    )

    executor = object.__new__(ClickHouseWriteExecutor)
    alignment = executor._normalize_partition(
        pdf,
        table,
        WriteRequest(
            mode=WriteMode.APPEND,
            target=WriteTarget(table_name="events"),
            on_extra_df_columns=ExtraColumnsMode.IGNORE,
        ),
    )

    assert alignment.insert_column_names == ["business_key", "payload"]
    assert alignment.normalized.to_dict(orient="records") == [{"business_key": "one", "payload": "a"}]


def test_write_v3_clickhouse_normalize_partition_allows_missing_optional_columns() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("business_key", sa.String()),
        sa.Column("payload", sa.String()),
        sa.Column("optional_value", sa.String(), nullable=True),
    )
    pdf = pd.DataFrame({"business_key": ["one"], "payload": ["a"]})

    executor = object.__new__(ClickHouseWriteExecutor)
    alignment = executor._normalize_partition(
        pdf,
        table,
        WriteRequest(
            mode=WriteMode.APPEND,
            target=WriteTarget(table_name="events"),
            on_missing_df_columns=MissingColumnsMode.IGNORE_IF_DEFAULT,
        ),
    )

    assert alignment.insert_column_names == ["business_key", "payload"]
    assert alignment.normalized.to_dict(orient="records") == [{"business_key": "one", "payload": "a"}]


def test_write_v3_clickhouse_build_column_meta_preserves_nullable_type_names() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("amount", _RenderedType("Nullable(Float64)"), nullable=False),
        sa.Column("tag", _RenderedType("LowCardinality(String)"), nullable=True),
    )

    executor = object.__new__(ClickHouseWriteExecutor)
    meta = executor._build_column_meta(table)

    assert meta["amount"]["type_name"] == "Nullable(Float64)"
    assert meta["amount"]["base_type"] == "Float64"
    assert meta["tag"]["type_name"] == "LowCardinality(Nullable(String))"
    assert meta["tag"]["base_type"] == "String"


@pytest.mark.parametrize(
    ("mode", "expected_table", "expected_async_insert"),
    [
        (WriteMode.APPEND, "events", True),
        (WriteMode.TRUNCATE, "events_stg", False),
        (WriteMode.UPSERT, "events_stg", False),
    ],
)
def test_write_v3_clickhouse_execute_enables_async_insert_only_for_append(
    monkeypatch,
    mode: WriteMode,
    expected_table: str,
    expected_async_insert: bool,
) -> None:
    executor = object.__new__(ClickHouseWriteExecutor)
    executor.engine = _FakeClickHouseEngine()
    executor.dialect = _FakeClickHouseDialect()

    table = sa.Table("events", sa.MetaData(), sa.Column("id", sa.Integer()))
    staging_table = sa.Table("events_stg", sa.MetaData(), sa.Column("id", sa.Integer()))
    captured_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        "core.db.write_v3.executors.ch.build_clickhouse_client_kwargs",
        lambda engine: {},
    )
    monkeypatch.setattr(
        "core.db.write_v3.executors.ch.process_partitions_bounded",
        lambda ddf, handler, max_workers: handler(pd.DataFrame({"id": [1]})),
    )

    executor._reflect_table = lambda table_name, schema_name: table
    executor._create_staging_table = lambda target_table: staging_table
    executor._normalize_partition = lambda pdf, target_table, request, include_default_only_diagnostic=False: SimpleNamespace(
        diagnostics=[],
        insert_column_names=["id"],
    )
    executor._delete_using_staging_sql = lambda *args: "DELETE FROM events"
    executor._copy_table = lambda *args: None
    executor._drop_table = lambda *args: None
    executor._insert_partition = (
        lambda pool, target_table, pdf, request, *, use_async_insert: captured_calls.append(
            (target_table.name, use_async_insert)
        ) or len(pdf)
    )

    request_kwargs = {
        "mode": mode,
        "target": WriteTarget(table_name="events"),
        "write_workers": 1,
    }
    if mode == WriteMode.UPSERT:
        request_kwargs["upsert"] = UpsertConfig(key_column="id")
    request = WriteRequest(**request_kwargs)
    plan = SimpleNamespace(
        mode=mode,
        upsert_key="id" if mode == WriteMode.UPSERT else None,
    )

    result = executor.execute(
        dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        request,
        plan,
    )

    assert result.rows_written == 1
    assert captured_calls == [(expected_table, expected_async_insert)]


def test_write_v3_sqlite_append_ignores_extra_df_columns_when_configured(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_ignore_extra.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    ddf = dd.from_pandas(
        pd.DataFrame(
            {
                "business_key": ["one", "two"],
                "payload": ["a", "b"],
                "extra_payload": ["drop-1", "drop-2"],
            }
        ),
        npartitions=2,
    )

    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_extra_df_columns=ExtraColumnsMode.IGNORE,
        chunksize=2,
        write_workers=2,
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "extra_columns_ignored"
    assert result.diagnostics[0].details == {"columns": ["extra_payload"]}
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT business_key, payload FROM events")).fetchall()
    assert sorted(rows) == [("one", "a"), ("two", "b")]


def test_write_v3_sqlite_append_transliterates_non_ascii_dataframe_columns_for_reflected_table(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_translit.sqlite'}")
    metadata = sa.MetaData()
    table = build_table_from_db_columns(
        table_name="products",
        columns=[
            DBColumn(name="Код", dtype=DataType.INT, nullable=False),
            DBColumn(name="Наименование", dtype=DataType.STRING, nullable=True),
        ],
        dialect=engine.dialect,
        metadata=metadata,
    )
    metadata.create_all(engine, tables=[table], checkfirst=False)

    ddf = dd.from_pandas(
        pd.DataFrame(
            {
                "Код": [101, 202],
                "Наименование": ["alpha", "beta"],
            }
        ),
        npartitions=1,
    )
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="products"),
        chunksize=2,
        write_workers=1,
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT kod, naimenovanie FROM products ORDER BY kod")).fetchall()
    assert rows == [(101, "alpha"), (202, "beta")]


def test_write_v3_sqlite_append_allows_missing_optional_columns_by_default(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_missing_optional.sqlite'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "payload TEXT NOT NULL, "
                "note TEXT DEFAULT 'seed', "
                "optional_value TEXT)"
            )
        )

    ddf = dd.from_pandas(pd.DataFrame({"payload": ["a", "b"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        chunksize=2,
        write_workers=1,
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == "missing_columns_ignored"
    assert result.diagnostics[0].details == {
        "columns": ["id", "note", "optional_value"],
        "policy": "ignore_if_default",
    }
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT payload, note, optional_value FROM events ORDER BY id")).fetchall()
    assert rows == [("a", "seed", None), ("b", "seed", None)]


def test_write_v3_sqlite_append_missing_required_column_fails_for_ignore_if_default(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_missing_required.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (payload TEXT NOT NULL, required_code TEXT NOT NULL)"))

    ddf = dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_missing_df_columns=MissingColumnsMode.IGNORE_IF_DEFAULT,
    )

    with pytest.raises(WriteV3ExecutionError, match="missing required columns"):
        write_dataframe(ddf, engine, request)


def test_write_v3_sqlite_append_case_mismatch_reports_exact_column_names(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_case_mismatch.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (kontragent TEXT NOT NULL, source TEXT NOT NULL)"))

    ddf = dd.from_pandas(pd.DataFrame({"Kontragent": ["a"], "Source": ["b"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_extra_df_columns=ExtraColumnsMode.IGNORE,
        on_missing_df_columns=MissingColumnsMode.IGNORE_IF_DEFAULT,
    )

    with pytest.raises(WriteV3ExecutionError) as exc_info:
        write_dataframe(ddf, engine, request)

    message = str(exc_info.value)
    assert "'kontragent' <- 'Kontragent'" in message
    assert "'source' <- 'Source'" in message
    assert "Exact-case column names are required" in message


def test_write_v3_sqlite_append_missing_optional_column_fails_for_error_policy(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_missing_error.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (payload TEXT NOT NULL, optional_value TEXT)"))

    ddf = dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_missing_df_columns=MissingColumnsMode.ERROR,
    )

    with pytest.raises(WriteV3ExecutionError, match="mismatch policy"):
        write_dataframe(ddf, engine, request)


def test_write_v3_sqlite_append_ignore_missing_defers_required_validation_to_db(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_missing_db_error.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (payload TEXT NOT NULL, required_code TEXT NOT NULL)"))

    ddf = dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_missing_df_columns=MissingColumnsMode.IGNORE,
    )

    with pytest.raises(IntegrityError):
        write_dataframe(ddf, engine, request)


def test_write_v3_sqlite_append_default_only_insert_uses_table_defaults(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_default_only.sqlite'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "note TEXT DEFAULT 'seed', "
                "optional_value TEXT)"
            )
        )

    ddf = dd.from_pandas(pd.DataFrame({"__dvt_partition_bucket": [0, 1]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_extra_df_columns=ExtraColumnsMode.IGNORE,
        on_missing_df_columns=MissingColumnsMode.IGNORE_IF_DEFAULT,
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT note, optional_value FROM events ORDER BY id")).fetchall()
    assert rows == [("seed", None), ("seed", None)]


def test_write_v3_sqlite_append_no_matching_user_columns_fails_instead_of_default_only_insert(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_no_match.sqlite'}")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "note TEXT DEFAULT 'seed', "
                "optional_value TEXT)"
            )
        )

    ddf = dd.from_pandas(pd.DataFrame({"extra_payload": ["x", "y"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_extra_df_columns=ExtraColumnsMode.IGNORE,
        on_missing_df_columns=MissingColumnsMode.IGNORE_IF_DEFAULT,
    )

    with pytest.raises(WriteV3ExecutionError, match="No DataFrame columns match target table"):
        write_dataframe(ddf, engine, request)


def test_write_v3_sqlite_append_default_only_insert_fails_for_required_table_column(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_default_only_fail.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (required_payload TEXT NOT NULL)"))

    ddf = dd.from_pandas(pd.DataFrame({"extra_payload": ["x"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        on_extra_df_columns=ExtraColumnsMode.IGNORE,
        on_missing_df_columns=MissingColumnsMode.IGNORE_IF_DEFAULT,
    )

    with pytest.raises(WriteV3ExecutionError, match="missing required columns"):
        write_dataframe(ddf, engine, request)


def test_write_v3_upsert_requires_key_column_in_dataframe_even_with_relaxed_missing_policy(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_upsert_missing_key.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    ddf = dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1)
    request = WriteRequest(
        mode=WriteMode.UPSERT,
        target=WriteTarget(table_name="events"),
        upsert=UpsertConfig(key_column="business_key"),
        on_missing_df_columns=MissingColumnsMode.IGNORE,
    )

    with pytest.raises(WriteV3ExecutionError, match="Upsert key column 'business_key' must be present"):
        write_dataframe(ddf, engine, request)


def test_write_v3_upsert_case_mismatch_reports_exact_key_column_name(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v3_upsert_case_key.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    ddf = dd.from_pandas(
        pd.DataFrame({"Business_Key": ["one"], "payload": ["row-1"]}),
        npartitions=1,
    )
    request = WriteRequest(
        mode=WriteMode.UPSERT,
        target=WriteTarget(table_name="events"),
        upsert=UpsertConfig(key_column="business_key"),
        on_missing_df_columns=MissingColumnsMode.IGNORE,
    )

    with pytest.raises(WriteV3ExecutionError) as exc_info:
        write_dataframe(ddf, engine, request)

    message = str(exc_info.value)
    assert "'business_key' <- 'Business_Key'" in message
    assert "Exact-case column names are required" in message


def test_write_v3_normalize_partition_coerces_mssql_uuid_and_binary_strings() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("guid_col", mssql.UNIQUEIDENTIFIER()),
        sa.Column("bin_col", mssql.VARBINARY(4)),
    )
    pdf = pd.DataFrame(
        {
            "guid_col": ["12345678-1234-5678-1234-567812345678"],
            "bin_col": ["00FF6162"],
        }
    )

    alignment = align_partition_to_table(
        pdf,
        table,
        WriteRequest(mode=WriteMode.APPEND, target=WriteTarget(table_name="events")),
    )

    assert alignment.normalized.iloc[0]["guid_col"] == UUID("12345678-1234-5678-1234-567812345678")
    assert alignment.normalized.iloc[0]["bin_col"] == b"\x00\xffab"


def test_write_v3_normalize_partition_rejects_invalid_mssql_uuid_string() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("guid_col", mssql.UNIQUEIDENTIFIER()),
    )

    with pytest.raises(WriteV3ExecutionError, match="uniqueidentifier column 'guid_col'"):
        align_partition_to_table(
            pd.DataFrame({"guid_col": ["not-a-uuid"]}),
            table,
            WriteRequest(mode=WriteMode.APPEND, target=WriteTarget(table_name="events")),
        )


def test_write_v3_normalize_partition_rejects_invalid_mssql_binary_hex_string() -> None:
    metadata = sa.MetaData()
    table = sa.Table(
        "events",
        metadata,
        sa.Column("bin_col", mssql.BINARY(2)),
    )

    with pytest.raises(WriteV3ExecutionError, match="Expected hex string"):
        align_partition_to_table(
            pd.DataFrame({"bin_col": ["zz"]}),
            table,
            WriteRequest(mode=WriteMode.APPEND, target=WriteTarget(table_name="events")),
        )
