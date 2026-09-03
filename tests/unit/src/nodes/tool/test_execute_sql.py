import dask.dataframe as dd
import pandas as pd
import pytest
import sqlalchemy as sa

from core.types import Column, DataFrameMetadata, DataType
from src.node_dsl import IO
from src.modules.sql_code_metadata import SQLCodeMetadata, SQLStatementMetadata
from src.nodes.tool.execute_sql import ExecuteSQL


def _build_node(*, connection, sql_code: str) -> ExecuteSQL:
    return ExecuteSQL(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-sql-1",
        connection=connection,
        sql_code=sql_code,
    )


def test_execute_sql_runs_statement_and_emits_signal(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'execute_sql.sqlite'}")

    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE test_events (id INTEGER PRIMARY KEY, value TEXT)")

    node = _build_node(connection=engine, sql_code="INSERT INTO test_events(value) VALUES ('ok')")
    node.process()

    with engine.begin() as conn:
        inserted_rows = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM test_events WHERE value = 'ok'"
        ).scalar_one()

    assert inserted_rows == 1
    assert node.signal_out is True
    assert not isinstance(node.output, dd.DataFrame)


def test_execute_sql_reads_select_result_into_output(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'execute_sql_select.sqlite'}")

    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE test_events (id INTEGER PRIMARY KEY, value TEXT)")
        conn.exec_driver_sql("INSERT INTO test_events(value) VALUES ('first'), ('second')")

    node = _build_node(
        connection=engine,
        sql_code="SELECT id, value FROM test_events ORDER BY id",
    )
    node.process()

    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [
        {"id": 1, "value": "first"},
        {"id": 2, "value": "second"},
    ]
    assert "id" not in node.output_variables
    assert "value" not in node.output_variables


def test_execute_sql_reads_single_select_result_into_output_variables(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'execute_sql_single_select.sqlite'}")

    node = _build_node(
        connection=engine,
        sql_code="SELECT 42 AS answer, 'ok' AS status",
    )
    node.process()

    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [{"answer": 42, "status": "ok"}]
    assert node.output_variables["answer"].value == 42
    assert node.output_variables["answer"].type == IO.INT
    assert node.output_variables["status"].value == "ok"
    assert node.output_variables["status"].type == IO.STRING


def test_execute_sql_commits_returning_statement_and_populates_output(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'execute_sql_returning.sqlite'}")

    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE test_events (id INTEGER PRIMARY KEY, value TEXT)")

    node = _build_node(
        connection=engine,
        sql_code="INSERT INTO test_events(value) VALUES ('ok') RETURNING id, value",
    )
    node.process()

    with engine.begin() as conn:
        inserted_rows = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM test_events WHERE value = 'ok'"
        ).scalar_one()

    assert inserted_rows == 1
    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [{"id": 1, "value": "ok"}]
    assert node.output_variables["id"].value == 1
    assert node.output_variables["id"].type == IO.INT
    assert node.output_variables["value"].value == "ok"
    assert node.output_variables["value"].type == IO.STRING


def test_execute_sql_single_row_null_result_populates_nullable_variable(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'execute_sql_null.sqlite'}")

    node = _build_node(
        connection=engine,
        sql_code="SELECT NULL AS maybe_value",
    )
    node.process()

    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [{"maybe_value": None}]
    assert node.output_variables["maybe_value"].value is None
    assert node.output_variables["maybe_value"].type == IO.JSON


def test_execute_sql_mssql_output_statement_populates_dataframe_and_variables(monkeypatch):
    engine = sa.create_engine("sqlite:///:memory:")
    node = _build_node(
        connection=engine,
        sql_code="INSERT INTO test_events(value) OUTPUT INSERTED.id, INSERTED.value VALUES ('ok')",
    )
    statement_metadata = SQLStatementMetadata(
        statement_type="INSERT",
        category="data_mutating",
        returns_data=True,
        is_query_expression=False,
    )
    sql_metadata = SQLCodeMetadata(
        statements=(statement_metadata,),
        statement_count=1,
        result_statement_count=1,
        dialect_name="mssql",
    )
    captured_returns_query_rows = []

    def fake_read_resulting_dataframe(*, sql_code: str, returns_query_rows: bool) -> pd.DataFrame:
        captured_returns_query_rows.append(returns_query_rows)
        return pd.DataFrame([{"id": 7, "value": "ok"}])

    monkeypatch.setattr(node, "ensure_sql_code_metadata", lambda: sql_metadata)
    monkeypatch.setattr(node, "_read_resulting_dataframe", fake_read_resulting_dataframe)

    node.process()

    assert captured_returns_query_rows == [False]
    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [{"id": 7, "value": "ok"}]
    assert node.output_variables["id"].value == 7
    assert node.output_variables["id"].type == IO.INT
    assert node.output_variables["value"].value == "ok"
    assert node.output_variables["value"].type == IO.STRING


@pytest.mark.asyncio
async def test_execute_sql_process_metadata_builds_empty_output_from_dataframe_metadata(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'execute_sql_metadata.sqlite'}")
    node = _build_node(connection=engine, sql_code="SELECT id, value FROM test_events")

    statement_metadata = SQLStatementMetadata(
        statement_type="SELECT",
        category="read_only",
        returns_data=True,
        is_query_expression=True,
    )
    sql_metadata = SQLCodeMetadata(
        statements=(statement_metadata,),
        statement_count=1,
        result_statement_count=1,
        dialect_name="sqlite",
    )
    dataframe_metadata = DataFrameMetadata(
        columns=[
            Column(name="id", dtype=DataType.INT, nullable=True, index=False),
            Column(name="value", dtype=DataType.STRING, nullable=True, index=False),
        ]
    )

    class _FakeExtractor:
        def execute(self, **_kwargs) -> SQLCodeMetadata:
            return SQLCodeMetadata(
                statements=(statement_metadata,),
                statement_count=1,
                result_statement_count=1,
                dialect_name="sqlite",
                dataframe_metadata=dataframe_metadata,
                dataframe_metadata_statement_index=0,
            )

    monkeypatch.setattr(node, "ensure_sql_code_metadata", lambda: sql_metadata)
    monkeypatch.setattr(node, "_sql_metadata_extractor", _FakeExtractor())

    await node.process_metadata()

    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert list(node.output.columns) == ["id", "value"]
    assert node.output.compute().empty is True


def test_execute_sql_raises_on_empty_sql(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'execute_sql_empty.sqlite'}")
    node = _build_node(connection=engine, sql_code="   ")

    with pytest.raises(ValueError, match="SQL code is empty"):
        node.process()


def test_execute_sql_keeps_sql_field_definition():
    sql_field = ExecuteSQL._input_field_instances["sql_code"]

    assert sql_field.multiline is True
    assert sql_field.expression_policy == "default"


def test_execute_sql_exposes_output_variables_handle():
    variables_field = ExecuteSQL._output_field_instances["output_variables"]

    assert variables_field.force_handle_visible is True
