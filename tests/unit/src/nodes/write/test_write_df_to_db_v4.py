from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import dask.dataframe as dd
import pandas as pd
import pytest
from db_connection.domain import ConnectionRecord
from sqlalchemy import create_engine

from core.db.write_v4 import WriteColumnMapping
from core.types import DataType

from src.node_dsl import SqlConnectionRecord, get_definition
from src.nodes.write.write_df_to_db_v4 import WriteDataFrameToDBV4
from src.schemas.internal import ProjectSettings


class _FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


@pytest.fixture(autouse=True)
def _no_catalog(monkeypatch):
    # Описания каталога требуют БД: по умолчанию тесты работают без них.
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v4.node.load_catalog_descriptions", AsyncMock(return_value={})
    )


def _result(mode: str = "append"):
    return type("Result", (), {"mode": mode, "target_name": "events", "rows_written": 1})()


def _node(**overrides) -> WriteDataFrameToDBV4:
    kwargs = {
        "user_id": "user",
        "project_id": "project",
        "task_id": "task",
        "node_id": "node-write-v4-sync",
        "connection": _make_sqlite_connection_record(),
        "df": dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        "table_name": "events",
        "schema_name": "public",
        "project_settings": ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    }
    kwargs.update(overrides)
    return WriteDataFrameToDBV4(**kwargs)


@pytest.mark.asyncio
async def test_process_syncs_catalog_descriptions_into_target_column_comments(monkeypatch) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr("src.nodes.write.write_df_to_db_v4.node.resolve_sql_engine", lambda connection: engine)
    monkeypatch.setattr("src.nodes.write.write_df_to_db_v4.node.write_dataframe", lambda df, e, r: _result())
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v4.node.load_catalog_descriptions",
        AsyncMock(return_value={"id": "Идентификатор клиента", "skipped": "Нет в маппинге, но имя совпадает"}),
    )
    captured = {}

    def fake_sync(used_engine, **kwargs):
        captured["engine"] = used_engine
        captured.update(kwargs)
        return 1

    monkeypatch.setattr("src.nodes.write.write_df_to_db_v4.node.sync_table_column_comments", fake_sync)
    node = _node(
        column_mapping=[WriteColumnMapping(source_name="id", target_name="client_id", dtype=DataType.INT, nullable=False)]
    )

    await node.process()

    assert captured["engine"] is engine
    assert (captured["table_name"], captured["schema_name"], captured["database_name"]) == ("events", "public", None)
    assert captured["descriptions"] == {"client_id": "Идентификатор клиента", "skipped": "Нет в маппинге, но имя совпадает"}


@pytest.mark.asyncio
async def test_process_skips_comment_sync_when_disabled_or_empty_and_survives_sync_errors(monkeypatch) -> None:
    monkeypatch.setattr("src.nodes.write.write_df_to_db_v4.node.resolve_sql_engine", lambda connection: _FakeEngine())
    monkeypatch.setattr("src.nodes.write.write_df_to_db_v4.node.write_dataframe", lambda df, e, r: _result())
    loader = AsyncMock(return_value={"id": "Текст"})
    monkeypatch.setattr("src.nodes.write.write_df_to_db_v4.node.load_catalog_descriptions", loader)
    calls = []
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v4.node.sync_table_column_comments",
        lambda engine, **kwargs: calls.append(kwargs) or 1,
    )

    await _node(sync_column_descriptions=False).process()
    assert calls == [] and loader.await_count == 0, "disabled: the catalog is not even asked"

    loader.return_value = {}
    await _node().process()
    assert calls == [], "nothing to sync without descriptions"

    loader.return_value = {"id": "Текст"}

    def failing(engine, **kwargs):
        raise RuntimeError("permission denied")

    monkeypatch.setattr("src.nodes.write.write_df_to_db_v4.node.sync_table_column_comments", failing)
    await _node().process()


def test_write_dataframe_to_db_v4_documents_existing_target_requirement() -> None:
    definition = get_definition("WriteDataFrameToDBV4", lang="en")

    assert "does not create missing databases, schemas, or tables" in definition.description


def test_write_dataframe_to_db_v4_build_request_includes_column_mapping() -> None:
    engine = create_engine("sqlite://")
    node = WriteDataFrameToDBV4(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v4-request",
        connection=engine,
        df=dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        table_name="events",
        column_mapping=[
            WriteColumnMapping(
                source_name="id",
                target_name="client_id",
                dtype=DataType.INT,
                nullable=False,
            )
        ],
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    request = node._build_request()

    assert request.column_mapping == [
        WriteColumnMapping(
            source_name="id",
            target_name="client_id",
            dtype=DataType.INT,
            nullable=False,
        )
    ]


def _make_sqlite_connection_record() -> SqlConnectionRecord:
    return SqlConnectionRecord(
        ConnectionRecord(
            id="conn-1",
            name="Test connection",
            kind="sql",
            type="sqlite",
            driver="pysqlite",
            driver_options=None,
            properties={"database": ":memory:"},
            secrets={},
            labels={},
            metadata={},
            extra={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )


def test_write_dataframe_to_db_v4_resolves_sql_connection_record(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    captured = {}

    def fake_write_dataframe(df, used_engine, request):
        captured["df"] = df
        captured["engine"] = used_engine
        captured["request"] = request

        class Result:
            mode = "append"
            target_name = "events"
            rows_written = 1

        return Result()

    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v4.node.resolve_sql_engine",
        lambda connection: engine,
    )
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v4.node.write_dataframe",
        fake_write_dataframe,
    )

    node = WriteDataFrameToDBV4(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v4-record",
        connection=_make_sqlite_connection_record(),
        df=dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        table_name="events",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    try:
        result, used_engine, owned_by_node = node._run_blocking_write_sync()
    finally:
        engine.dispose()

    assert captured["engine"] is engine
    assert captured["request"].target.table_name == "events"
    assert used_engine is engine
    assert owned_by_node is True
    assert result.rows_written == 1


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v4_process_disposes_node_owned_engine(monkeypatch) -> None:
    owned_engine = _FakeEngine()
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v4.node.resolve_sql_engine",
        lambda connection: owned_engine,
    )
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v4.node.write_dataframe",
        lambda df, used_engine, request: type(
            "Result",
            (),
            {"mode": "append", "target_name": "events", "rows_written": 1},
        )(),
    )

    node = WriteDataFrameToDBV4(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v4-owned-engine",
        connection=_make_sqlite_connection_record(),
        df=dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        table_name="events",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    await node.process()

    assert owned_engine.dispose_calls == 1
