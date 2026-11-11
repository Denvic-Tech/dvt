"""ReadVariablesFromDB SQL mode with ``%`` on PostgreSQL (psycopg) and MySQL (pymysql)."""

from __future__ import annotations

import pytest
from tests.integration.fixtures.percent_sql import (
    PERCENT_ROWS,
)

from src.nodes.extract.read_variables_from_db import ReadVariablesFromDB

pytestmark = pytest.mark.docker_required


def test_read_variables_from_db_keeps_percent_signs_of_user_sql(percent_table) -> None:
    engine, table = percent_table
    node = ReadVariablesFromDB(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-variables-percent",
        connection=engine,
        mode="sql",
        # '%%' is two percent signs, as in psql or the mysql client.
        sql_code=(
            f"SELECT (SELECT COUNT(*) FROM {table} WHERE name LIKE 'A%') AS like_rows, "
            f"(SELECT COUNT(*) FROM {table} WHERE LEFT(name, 2) = '%%') AS double_percent_rows, "
            f"(SELECT COUNT(*) FROM {table} WHERE id % 3 = 0) AS modulo_rows, "
            "'%%' AS double_percent"
        ),
    )

    node.process()

    rows = range(1, PERCENT_ROWS + 1)
    values = {name: variable.value for name, variable in node.output_variables.items()}
    assert values == {
        "like_rows": sum(1 for row_id in rows if row_id % 4 in (0, 1)),
        "double_percent_rows": sum(1 for row_id in rows if row_id % 4 == 3),
        "modulo_rows": sum(1 for row_id in rows if row_id % 3 == 0),
        "double_percent": "%%",
    }
