from __future__ import annotations

import dask.dataframe as dd
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from core.db.write_v3 import ExtraColumnsMode, MissingColumnsMode, UpsertConfig
from src.node_dsl import IO
from src.node_dsl.variables import VariableOutput
from src.nodes.write.write_df_to_db_v3 import WriteDataFrameToDBV3
from src.schemas.internal import ProjectSettings


class _FakeEngine:
    def __init__(self) -> None:
        self.dispose_calls = 0

    def dispose(self) -> None:
        self.dispose_calls += 1


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v3_process_supports_upsert(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'node_write_v3.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    seed_df = dd.from_pandas(
        pd.DataFrame(
            {
                "business_key": ["a", None],
                "payload": ["seed-a", "seed-null"],
            }
        ),
        npartitions=1,
    )
    seed_node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-seed",
        connection=engine,
        df=seed_df,
        table_name="events",
        write_mode="append",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )
    await seed_node.process()

    upsert_df = dd.from_pandas(
        pd.DataFrame(
            {
                "business_key": [None, "b", "b"],
                "payload": ["new-null", "b-1", "b-2"],
            }
        ),
        npartitions=2,
    )
    node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-upsert",
        connection=engine,
        df=upsert_df,
        table_name="events",
        write_mode="upsert",
        upsert_config=UpsertConfig(key_column="business_key"),
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    await node.process()

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT business_key, payload FROM events")).fetchall()

    assert sorted(rows, key=lambda row: (row[0] is not None, str(row[0]), str(row[1]))) == [
        (None, "new-null"),
        ("a", "seed-a"),
        ("b", "b-1"),
        ("b", "b-2"),
    ]
    assert node.output_variables["target_table"] == VariableOutput(
        name="target_table",
        type=IO.STRING,
        value="events",
        var_type="system",
    )
    assert node.output_variables["rows_written"] == VariableOutput(
        name="rows_written",
        type=IO.INT,
        value=3,
        var_type="system",
    )


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v3_process_supports_upstream_callbacks(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'node_write_v3_callbacks.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    callback_events = {"start": 0, "end": 0}
    upstream_df = dd.from_pandas(
        pd.DataFrame(
            {
                "business_key": ["a", "b", "c"],
                "payload": ["x", "y", "z"],
            }
        ),
        npartitions=2,
    ).add_callbacks(
        on_start=lambda _meta, operation_id: callback_events.__setitem__(
            "start",
            callback_events["start"] + (1 if operation_id == "task:node:output" else 0),
        ),
        on_end=lambda _meta, operation_id: callback_events.__setitem__(
            "end",
            callback_events["end"] + (1 if operation_id == "task:node:output" else 0),
        ),
        on_partition=lambda *_args, **_kwargs: None,
        operation_id="task:node:output",
    )

    node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-callbacks",
        connection=engine,
        df=upstream_df,
        table_name="events",
        write_mode="append",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    await node.process()

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT business_key, payload FROM events")).fetchall()

    assert sorted(rows) == [("a", "x"), ("b", "y"), ("c", "z")]
    assert callback_events["start"] == 1
    assert callback_events["end"] == 1
    assert node.output_variables["target_table"] == VariableOutput(
        name="target_table",
        type=IO.STRING,
        value="events",
        var_type="system",
    )
    assert node.output_variables["rows_written"] == VariableOutput(
        name="rows_written",
        type=IO.INT,
        value=3,
        var_type="system",
    )


def test_write_dataframe_to_db_v3_build_request_includes_column_mismatch_modes() -> None:
    engine = create_engine("sqlite://")
    node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-request",
        connection=engine,
        df=dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1),
        table_name="events",
        on_extra_df_columns="ignore",
        on_missing_df_columns="ignore",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    request = node._build_request()

    assert request.on_extra_df_columns == ExtraColumnsMode.IGNORE
    assert request.on_missing_df_columns == MissingColumnsMode.IGNORE


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v3_process_ignores_extra_columns_when_configured(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'node_write_v3_ignore_extra.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE events (business_key TEXT, payload TEXT)"))

    node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-ignore-extra",
        connection=engine,
        df=dd.from_pandas(
            pd.DataFrame(
                {
                    "business_key": ["a", "b"],
                    "payload": ["x", "y"],
                    "extra_payload": ["drop-1", "drop-2"],
                }
            ),
            npartitions=1,
        ),
        table_name="events",
        on_extra_df_columns="ignore",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    await node.process()

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT business_key, payload FROM events ORDER BY business_key")).fetchall()

    assert rows == [("a", "x"), ("b", "y")]
    assert node.output_variables["rows_written"] == VariableOutput(
        name="rows_written",
        type=IO.INT,
        value=2,
        var_type="system",
    )


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v3_process_does_not_dispose_passed_engine(monkeypatch) -> None:
    engine = create_engine("sqlite://")
    dispose_calls = 0
    original_dispose = engine.dispose

    def tracked_dispose() -> None:
        nonlocal dispose_calls
        dispose_calls += 1
        original_dispose()

    monkeypatch.setattr(engine, "dispose", tracked_dispose)
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v3.write_dataframe",
        lambda df, used_engine, request: type(
            "Result",
            (),
            {"mode": "append", "target_name": "events", "rows_written": 1},
        )(),
    )

    node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-shared-engine",
        connection=engine,
        df=dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1),
        table_name="events",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    try:
        await node.process()
    finally:
        original_dispose()

    assert dispose_calls == 0


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v3_process_disposes_node_owned_engine_on_failure(monkeypatch) -> None:
    owned_engine = _FakeEngine()
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v3.resolve_sql_engine",
        lambda connection: owned_engine,
    )
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v3.write_dataframe",
        lambda df, used_engine, request: (_ for _ in ()).throw(RuntimeError("write failed")),
    )

    node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-owned-engine-failure",
        connection=object(),
        df=dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1),
        table_name="events",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )

    with pytest.raises(RuntimeError, match="write failed"):
        await node.process()

    assert owned_engine.dispose_calls == 1


@pytest.mark.asyncio
async def test_write_dataframe_to_db_v3_process_reuses_execution_engine_for_meta_cache(monkeypatch) -> None:
    owned_engine = _FakeEngine()
    resolve_calls = 0
    fingerprint_engines = []
    removed_keys = []

    def fake_resolve_sql_engine(connection):
        nonlocal resolve_calls
        resolve_calls += 1
        return owned_engine

    async def fake_remove(key: str) -> None:
        removed_keys.append(key)

    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v3.resolve_sql_engine",
        fake_resolve_sql_engine,
    )
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v3.write_dataframe",
        lambda df, used_engine, request: type(
            "Result",
            (),
            {"mode": "append", "target_name": "events", "rows_written": 1},
        )(),
    )
    monkeypatch.setattr(
        "src.nodes.write.write_df_to_db_v3.create_sa_engine_fingerprint",
        lambda used_engine: fingerprint_engines.append(used_engine) or "fingerprint-key",
    )

    node = WriteDataFrameToDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-write-v3-meta-cache",
        connection=object(),
        df=dd.from_pandas(pd.DataFrame({"payload": ["a"]}), npartitions=1),
        table_name="events",
        project_settings=ProjectSettings(store_enabled=False, ttl_time=600, workers_count=2),
    )
    node._meta_cache = True
    node.metadata_store = type("MetadataStore", (), {"remove": staticmethod(fake_remove)})()

    await node.process()

    assert resolve_calls == 1
    assert fingerprint_engines == [owned_engine]
    assert removed_keys == ["fingerprint-key"]
    assert owned_engine.dispose_calls == 1
