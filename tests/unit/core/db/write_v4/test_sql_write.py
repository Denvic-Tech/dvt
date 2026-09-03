from __future__ import annotations

from types import SimpleNamespace

import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.write_v4 import (
    UpsertConfig,
    WriteColumnMapping,
    WriteMode,
    WritePlan,
    WriteRequest,
    WriteTarget,
    write_dataframe,
)
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors.ch import ClickHouseWriteExecutor, _ClickHouseClientPool
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


def test_write_v4_clickhouse_client_pool_uses_factory_and_reuses_client(monkeypatch) -> None:
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
        "core.db.write_v4.executors.ch.create_clickhouse_client",
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


def test_write_v4_sqlite_append_applies_column_mapping(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v4_mapping.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (client_id INTEGER NOT NULL, payload TEXT)"))

    ddf = dd.from_pandas(
        pd.DataFrame({"id": [1, 2], "payload": ["a", "b"]}),
        npartitions=1,
    )
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        column_mapping=[
            WriteColumnMapping(source_name="id", target_name="client_id", dtype=DataType.INT)
        ],
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT client_id, payload FROM events ORDER BY client_id")).fetchall()
    assert rows == [(1, "a"), (2, "b")]


def test_write_v4_sqlite_append_supports_partial_column_mapping(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v4_partial_mapping.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (client_id INTEGER NOT NULL, payload TEXT)"))

    ddf = dd.from_pandas(
        pd.DataFrame({"id": [1], "payload": ["kept-by-name"]}),
        npartitions=1,
    )
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="events"),
        column_mapping=[{"source_name": "id", "target_name": "client_id"}],
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 1
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT client_id, payload FROM events")).fetchall()
    assert rows == [(1, "kept-by-name")]


def test_write_v4_sqlite_append_preserves_transliteration_fallback_without_mapping(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v4_translit.sqlite'}")
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
        pd.DataFrame({"Код": [101, 202], "Наименование": ["alpha", "beta"]}),
        npartitions=1,
    )
    request = WriteRequest(mode=WriteMode.APPEND, target=WriteTarget(table_name="products"))

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 2
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT kod, naimenovanie FROM products ORDER BY kod")).fetchall()
    assert rows == [(101, "alpha"), (202, "beta")]


def test_write_v4_explicit_mapping_takes_priority_over_transliteration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v4_mapping_priority.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (kod INTEGER NOT NULL, custom_code INTEGER NOT NULL)"))

    ddf = dd.from_pandas(
        pd.DataFrame({"Код": [101], "custom_code": [202]}),
        npartitions=1,
    )
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="products"),
        column_mapping=[{"source_name": "Код", "target_name": "kod"}],
    )

    result = write_dataframe(ddf, engine, request)

    assert result.rows_written == 1
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT kod, custom_code FROM products")).fetchall()
    assert rows == [(101, 202)]


def test_write_v4_fails_when_explicit_mapping_and_transliteration_collide(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'write_v4_mapping_collision.sqlite'}")
    metadata = sa.MetaData()
    table = build_table_from_db_columns(
        table_name="products",
        columns=[DBColumn(name="Код", dtype=DataType.INT, nullable=False)],
        dialect=engine.dialect,
        metadata=metadata,
    )
    metadata.create_all(engine, tables=[table], checkfirst=False)

    ddf = dd.from_pandas(
        pd.DataFrame({"Код": [101], "manual": [202]}),
        npartitions=1,
    )
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name="products"),
        column_mapping=[{"source_name": "manual", "target_name": "kod"}],
    )

    with pytest.raises(WriteV4ExecutionError, match="duplicate target names"):
        write_dataframe(ddf, engine, request)


def test_write_v4_rejects_duplicate_mapping_targets_case_insensitive() -> None:
    with pytest.raises(ValueError, match="duplicate target_name"):
        WriteRequest(
            mode=WriteMode.APPEND,
            target=WriteTarget(table_name="events"),
            column_mapping=[
                {"source_name": "a", "target_name": "ID"},
                {"source_name": "b", "target_name": "id"},
            ],
        )


@pytest.mark.parametrize(
    ("mode", "expected_table", "expected_async_insert"),
    [
        (WriteMode.APPEND, "events", True),
        (WriteMode.TRUNCATE, "events_stg", False),
        (WriteMode.UPSERT, "events_stg", False),
    ],
)
def test_write_v4_clickhouse_execute_enables_async_insert_only_for_append(
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
        "core.db.write_v4.executors.ch.build_clickhouse_client_kwargs",
        lambda engine: {},
    )
    monkeypatch.setattr(
        "core.db.write_v4.executors.ch.process_partitions_bounded",
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
    plan = WritePlan(
        dialect="clickhouse",
        mode=mode,
        table_exists=True,
        target=request.target,
        use_staging=mode in {WriteMode.TRUNCATE, WriteMode.UPSERT},
        upsert_key="id" if mode == WriteMode.UPSERT else None,
    )

    result = executor.execute(
        dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        request,
        plan,
    )

    assert result.rows_written == 1
    assert captured_calls == [(expected_table, expected_async_insert)]
