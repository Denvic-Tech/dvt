import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.types import Column, DataFrameMetadata, DataType

from src.nodes.extract.read_query_from_db_v3 import node as read_query_module
from src.node_dsl import (
    ExecutionDateTimePrecision,
    ExecutionSettings,
    NodeValidationError,
    get_definition,
)
from src.node_dsl.variables import make_unresolved_value
from src.nodes.extract.read_query_from_db_v3 import ReadQueryFromDBV3


class _Dialect:
    name = "sqlite"


class _Connection:
    dialect = _Dialect()


def test_read_query_from_db_v3_documents_required_partition_column() -> None:
    definition = get_definition("ReadQueryFromDBV3", lang="en")

    assert "required" in definition.input_definitions["partition_col"].description.lower()
    assert "prefer readtablefromdbv3" in definition.description.lower()


def test_read_query_from_db_v3_forwards_partitioning_params_to_planner(monkeypatch):
    captured: dict[str, object] = {}

    class _Planner:
        def build_plan(self, **kwargs):
            captured.update(kwargs)
            return "plan"

    monkeypatch.setattr(read_query_module, "resolve_planner", lambda mode="query": _Planner())
    monkeypatch.setattr(read_query_module, "resolve_executor", lambda engine: "executor")
    monkeypatch.setattr(read_query_module, "frame_from_executor", lambda executor, plan: "output")

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=_Connection(),
        sql_code="SELECT id FROM events",
        partition_col="id",
        partition_grouping={"mode": "prefix", "length": 2},
        npartitions=3,
        limit=11,
        execution_settings=ExecutionSettings(
            datetime_precision=ExecutionDateTimePrecision.SECONDS,
        ),
    )

    node.process()

    assert captured["limit"] == 11
    assert captured["partition_grouping"] == {"mode": "prefix", "length": 2}
    assert captured["datetime_precision"] == ExecutionDateTimePrecision.SECONDS
    assert node.output == "output"


def test_read_query_from_db_v3_passes_none_npartitions_to_planner(monkeypatch):
    captured: dict[str, object] = {}

    class _Planner:
        def build_plan(self, **kwargs):
            captured.update(kwargs)
            return "plan"

    monkeypatch.setattr(read_query_module, "resolve_planner", lambda mode="query": _Planner())
    monkeypatch.setattr(read_query_module, "resolve_executor", lambda engine: "executor")
    monkeypatch.setattr(read_query_module, "frame_from_executor", lambda executor, plan: "output")

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=_Connection(),
        sql_code="SELECT id FROM events",
        partition_col="id",
        npartitions=None,
    )

    node.process()

    assert captured["npartitions"] is None


def test_read_query_from_db_v3_no_longer_has_local_auto_npartitions() -> None:
    assert not hasattr(ReadQueryFromDBV3, "_auto_npartitions")


def test_read_query_from_db_v3_process_preserves_non_string_meta_types(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_query_v3.sqlite'}")

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS users"))
        conn.execute(
            text(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL,
                    balance REAL NOT NULL,
                    is_deleted BOOLEAN NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO users (id, email, balance, is_deleted)
                VALUES (1, 'user@example.com', 12.5, 0)
                """
            )
        )

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=engine,
        sql_code="SELECT id, email, balance, is_deleted FROM users",
        partition_col="id",
        npartitions=1,
    )

    node.process()
    meta = node.output._meta

    assert not pd.api.types.is_string_dtype(meta["id"].dtype)
    assert not pd.api.types.is_string_dtype(meta["balance"].dtype)
    assert not pd.api.types.is_string_dtype(meta["is_deleted"].dtype)


@pytest.mark.asyncio
async def test_read_query_from_db_v3_process_metadata_builds_typed_empty_output(tmp_path):
    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine(f"sqlite:///{tmp_path / 'read_query_v3_metadata.sqlite'}"),
        sql_code="SELECT id, email, balance, is_deleted FROM users",
        partition_col="id",
        npartitions=1,
    )
    expected_metadata = {
        "output": DataFrameMetadata(
            columns=[
                Column(name="id", dtype=DataType.INT, nullable=False, index=False),
                Column(name="email", dtype=DataType.STRING, nullable=False, index=False),
                Column(name="balance", dtype=DataType.FLOAT, nullable=False, index=False),
                Column(name="is_deleted", dtype=DataType.BOOLEAN, nullable=False, index=False),
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


def test_read_query_from_db_v3_infer_metadata_returns_empty_schema_for_unresolved_query() -> None:
    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        sql_code=make_unresolved_value(reason="missing target_table", declared_type="STRING"),
    )

    metadata = node.infer_metadata()

    assert metadata == {"output": DataFrameMetadata(columns=[])}


def test_read_query_from_db_v3_infer_metadata_preserves_exact_query_column_case(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        read_query_module,
        "describe_query_columns",
        lambda *_args, **_kwargs: [
            ("PERIOD", "NUMBER"),
            ("Source", "VARCHAR2"),
            ("Kontragent", "VARCHAR2"),
        ],
    )

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        sql_code='SELECT 1 AS PERIOD, 2 AS "Source", 3 AS "Kontragent"',
    )

    metadata = node.infer_metadata()

    output = metadata["output"]
    assert isinstance(output, DataFrameMetadata)
    assert [column.name for column in output.columns] == ["PERIOD", "Source", "Kontragent"]


def test_read_query_from_db_v3_infer_metadata_maps_oracle_types_without_unknowns(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        read_query_module,
        "describe_query_columns",
        lambda *_args, **_kwargs: [
            ("PERIOD", "DATE"),
            ("SUMREAL", "NUMBER(18,4)"),
            ("BITRIXID", "VARCHAR2"),
            ("COMPANYREVENUE", "BINARY_DOUBLE"),
        ],
    )

    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        sql_code="SELECT 1 FROM dual",
    )

    metadata = node.infer_metadata()

    output = metadata["output"]
    assert isinstance(output, DataFrameMetadata)
    assert [(column.name, column.dtype) for column in output.columns] == [
        ("PERIOD", DataType.DATETIME),
        ("SUMREAL", DataType.FLOAT),
        ("BITRIXID", DataType.STRING),
        ("COMPANYREVENUE", DataType.FLOAT),
    ]


@pytest.mark.asyncio
async def test_read_query_from_db_v3_validate_rejects_empty_query() -> None:
    node = ReadQueryFromDBV3(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node",
        connection=sa.create_engine("sqlite:///:memory:"),
        partition_col="my_col",
        sql_code="   ",
    )

    with pytest.raises(NodeValidationError, match=ReadQueryFromDBV3.SQL_EMPTY_VALIDATION_MESSAGE):
        await node.validate()


def test_read_query_from_db_v3_keeps_query_field_definition() -> None:
    query_field = ReadQueryFromDBV3._input_field_instances["sql_code"]

    assert query_field.multiline is True
