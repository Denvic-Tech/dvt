import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.types import (
    Column,
    DataFrameMetadata,
    DataType,
    DBColumn,
    DBTable,
    DBTableType,
)

import src.nodes.extract.read_table_from_db_v3 as read_table_module
from src.node_dsl import ExecutionDateTimePrecision, ExecutionSettings, get_definition
from src.node_dsl.variables import make_unresolved_value
from src.nodes.extract.read_table_from_db_v3 import ReadTableFromDBV3


def test_read_table_from_db_v3_documents_mcp_safe_column_configuration() -> None:
    definition = get_definition("ReadTableFromDBV3")
    english_definition = get_definition("ReadTableFromDBV3", lang="en")
    russian_definition = get_definition("ReadTableFromDBV3", lang="ru")

    assert "explicit non-empty" in definition.input_definitions["columns"].description.lower()
    assert "without sql quotes or backticks" in (
        definition.input_definitions["partition_col"].description.lower()
    )
    assert "explicit non-empty" in (
        english_definition.input_definitions["columns"].description.lower()
    )
    assert "обязательный непустой" in (
        russian_definition.input_definitions["columns"].description.lower()
    )


def test_read_table_from_db_v3_forwards_partitioning_params_to_planner(monkeypatch):
    captured: dict[str, object] = {}

    class _Planner:
        def build_plan(self, **kwargs):
            captured.update(kwargs)
            return "plan"

    monkeypatch.setattr(read_table_module, "resolve_planner", lambda mode="table": _Planner())
    monkeypatch.setattr(read_table_module, "resolve_executor", lambda engine: "executor")
    monkeypatch.setattr(read_table_module, "frame_from_executor", lambda executor, plan: "output")

    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        table_name="events",
        schema_name=None,
        partition_col="id",
        partition_grouping={"mode": "ranges", "ranges": [[1, 10, True]]},
        npartitions=4,
        limit=10,
        execution_settings=ExecutionSettings(
            datetime_precision=ExecutionDateTimePrecision.SECONDS,
        ),
    )

    node.process()

    assert captured["limit"] == 10
    assert captured["partition_col"] == "id"
    assert captured["partition_grouping"] == {"mode": "ranges", "ranges": [[1, 10, True]]}
    assert captured["datetime_precision"] == ExecutionDateTimePrecision.SECONDS
    assert node.output == "output"


def test_read_table_from_db_v3_passes_none_npartitions_to_planner(monkeypatch):
    captured: dict[str, object] = {}

    class _Planner:
        def build_plan(self, **kwargs):
            captured.update(kwargs)
            return "plan"

    monkeypatch.setattr(read_table_module, "resolve_planner", lambda mode="table": _Planner())
    monkeypatch.setattr(read_table_module, "resolve_executor", lambda engine: "executor")
    monkeypatch.setattr(read_table_module, "frame_from_executor", lambda executor, plan: "output")

    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        table_name="events",
        schema_name=None,
        partition_col="id",
        npartitions=None,
    )

    node.process()

    assert captured["npartitions"] is None


def test_read_table_from_db_v3_process_preserves_non_string_meta_types(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_table_v3.sqlite'}")

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS users"))
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL,
                    balance REAL NOT NULL,
                    is_deleted BOOLEAN NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO users (id, email, balance, is_deleted, created_at, updated_at)
                VALUES (1, 'user@example.com', 12.5, 0, '2026-01-01 10:00:00', '2026-01-01 10:05:00')
                """
            )
        )

    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        table_name="users",
        schema_name=None,
        partition_col="id",
        columns=["id", "email", "balance", "is_deleted", "created_at", "updated_at"],
        npartitions=1,
    )

    node.process()
    meta = node.output._meta

    assert not pd.api.types.is_string_dtype(meta["id"].dtype)
    assert not pd.api.types.is_string_dtype(meta["balance"].dtype)
    assert not pd.api.types.is_string_dtype(meta["is_deleted"].dtype)


@pytest.mark.asyncio
async def test_read_table_from_db_v3_process_metadata_builds_typed_empty_output(tmp_path):
    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine(f"sqlite:///{tmp_path / 'read_table_v3_metadata.sqlite'}"),
        table_name="users",
        schema_name=None,
        partition_col="id",
        columns=["id", "email", "balance", "is_deleted", "created_at"],
        npartitions=1,
    )
    expected_metadata = {
        "output": DataFrameMetadata(
            columns=[
                Column(name="id", dtype=DataType.INT, nullable=False, index=False),
                Column(name="email", dtype=DataType.STRING, nullable=False, index=False),
                Column(name="balance", dtype=DataType.FLOAT, nullable=False, index=False),
                Column(name="is_deleted", dtype=DataType.BOOLEAN, nullable=False, index=False),
                Column(name="created_at", dtype=DataType.DATETIME, nullable=False, index=False),
            ]
        )
    }

    async def _resolve_metadata():
        return expected_metadata

    node.resolve_metadata = _resolve_metadata

    await node.process_metadata()
    meta = node.output._meta

    assert node.output.npartitions == 1
    assert meta.empty
    assert str(meta["id"].dtype) == "Int64"
    assert str(meta["email"].dtype) == "string"
    assert str(meta["balance"].dtype) == "float64"
    assert str(meta["is_deleted"].dtype) == "boolean"
    assert str(meta["created_at"].dtype) == "datetime64[ns]"
    assert "source_table_name" in node.output_variables


def test_read_table_from_db_v3_infer_metadata_returns_empty_schema_for_unresolved_target() -> None:
    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        table_name=make_unresolved_value(reason="missing source_table", declared_type="STRING"),
        database_name=make_unresolved_value(reason="missing database", declared_type="STRING"),
        schema_name=make_unresolved_value(reason="missing schema", declared_type="STRING"),
    )

    metadata = node.infer_metadata()

    assert metadata == {"output": DataFrameMetadata(columns=[])}


def test_read_table_from_db_v3_infer_metadata_loads_only_target_table(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        read_table_module,
        "load_db_table_metadata",
        lambda engine, **kwargs: calls.append((engine, kwargs)) or DBTable(
            database_name="analytics",
            schema_name="public",
            name="users",
            columns=[
                DBColumn(name="id", dtype=DataType.INT, nullable=False, index=True),
                DBColumn(name="email", dtype=DataType.STRING, nullable=False, index=False),
            ],
            type=DBTableType.BASE_TABLE,
        ),
    )

    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        table_name="users",
        database_name="analytics",
        schema_name="public",
        columns=["id"],
    )
    metadata_engine = sa.create_engine("sqlite:///:memory:")
    disposed = []
    original_dispose = metadata_engine.dispose
    metadata_engine.dispose = lambda: (disposed.append(True), original_dispose())[1]
    monkeypatch.setattr(node, "create_new_connection", lambda: metadata_engine)

    metadata = node.infer_metadata()

    assert isinstance(metadata["output"], DataFrameMetadata)
    assert metadata["output"].columns == [
        DBColumn(name="id", dtype=DataType.INT, nullable=False, index=True)
    ]
    assert calls[0][1] == {
        "table_name": "users",
        "schema_name": "public",
        "database_name": "analytics",
    }
    assert disposed == [True]


@pytest.mark.asyncio
async def test_read_table_from_db_v3_process_metadata_skips_system_variables_for_unresolved_target() -> None:
    node = ReadTableFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        table_name=make_unresolved_value(reason="missing source_table", declared_type="STRING"),
        database_name=None,
        schema_name=None,
    )

    await node.process_metadata()

    assert node.output._meta.empty
    assert "source_table_name" not in node.output_variables
