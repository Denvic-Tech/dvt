from __future__ import annotations

from uuid import uuid4

import dask.dataframe as dd
import pytest

from src.node_dsl import IO
from src.nodes.tool.execute_sql import ExecuteSQL

pytest.importorskip("pyodbc", reason="pyodbc is not installed; MSSQL integration tests are skipped")

pytestmark = pytest.mark.docker_required


def _build_node(*, connection, sql_code: str) -> ExecuteSQL:
    return ExecuteSQL(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-sql-mssql-1",
        connection=connection,
        sql_code=sql_code,
    )


def test_execute_sql_mssql_insert_output_populates_dataframe_and_variables(mssql_test_engine):
    table_name = f"execute_sql_output_{uuid4().hex[:8]}"
    with mssql_test_engine.begin() as conn:
        conn.exec_driver_sql(
            f"""
            IF OBJECT_ID(N'{table_name}', N'U') IS NOT NULL
                DROP TABLE {table_name}
            """
        )
        conn.exec_driver_sql(
            f"""
            CREATE TABLE {table_name} (
                id INT IDENTITY(1,1) PRIMARY KEY,
                value NVARCHAR(100) NOT NULL
            )
            """
        )

    try:
        node = _build_node(
            connection=mssql_test_engine,
            sql_code=(
                f"INSERT INTO {table_name} (value) "
                "OUTPUT INSERTED.id, INSERTED.value "
                "VALUES ('mssql-ok')"
            ),
        )

        node.process()

        with mssql_test_engine.connect() as conn:
            inserted_rows = conn.exec_driver_sql(
                f"SELECT COUNT(*) FROM {table_name} WHERE value = 'mssql-ok'"
            ).scalar_one()

        assert inserted_rows == 1
        assert node.signal_out is True
        assert isinstance(node.output, dd.DataFrame)
        assert node.output.compute().to_dict(orient="records") == [
            {"id": 1, "value": "mssql-ok"}
        ]
        assert node.output_variables["id"].value == 1
        assert node.output_variables["id"].type == IO.INT
        assert node.output_variables["value"].value == "mssql-ok"
        assert node.output_variables["value"].type == IO.STRING
    finally:
        with mssql_test_engine.begin() as conn:
            conn.exec_driver_sql(
                f"""
                IF OBJECT_ID(N'{table_name}', N'U') IS NOT NULL
                    DROP TABLE {table_name}
                """
            )
