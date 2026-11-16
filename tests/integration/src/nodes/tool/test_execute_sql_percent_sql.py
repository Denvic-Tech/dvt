"""ExecuteSQL statements with ``%`` on PostgreSQL (psycopg) and MySQL (pymysql)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from src.nodes.tool.execute_sql import ExecuteSQL

pytestmark = pytest.mark.docker_required


def _run(engine, sql_code: str) -> ExecuteSQL:
    node = ExecuteSQL(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-sql-percent",
        connection=engine,
        sql_code=sql_code,
    )
    node.process()
    return node


def test_execute_sql_keeps_percent_signs_of_user_sql(percent_table) -> None:
    engine, table = percent_table

    # Statements without a result set: LIKE wildcard, modulo and literals with percent signs.
    _run(engine, f"UPDATE {table} SET name = 'Z%' WHERE id % 100 = 0 AND name LIKE 'A%'")
    _run(engine, f"INSERT INTO {table} (id, name) VALUES (1001, '%%'), (1002, '%s')")
    # A query: '%%' is two percent signs, as in psql or the mysql client.
    query = _run(
        engine,
        f"SELECT id, name FROM {table} "
        "WHERE name LIKE 'Z%' OR name = '%%' OR name = '%s' ORDER BY id",
    )

    expected = [(100, "Z%"), (200, "Z%"), (300, "Z%"), (400, "Z%"), (1001, "%%"), (1002, "%s")]
    assert [tuple(row) for row in query.output.compute().itertuples(index=False)] == expected
    with engine.connect() as conn:
        stored = conn.execute(
            text(f"SELECT id, name FROM {table} WHERE id IN (100, 1001, 1002) ORDER BY id")
        ).all()
    assert [tuple(row) for row in stored] == [(100, "Z%"), (1001, "%%"), (1002, "%s")]


def test_execute_sql_returning_statement_keeps_percent_signs(postgres_test_engine) -> None:
    # A data-returning DML statement (MySQL has no RETURNING): the non-query result path.
    table = f"pct_returning_{uuid4().hex[:8]}"
    with postgres_test_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id BIGINT PRIMARY KEY, name VARCHAR(32))"))
    try:
        node = _run(
            postgres_test_engine,
            f"INSERT INTO {table} (id, name) VALUES (1, 'A%'), (2, '%%'), (3, 'B') "
            "RETURNING id, name, id % 2 AS odd",
        )
    finally:
        with postgres_test_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table}"))

    assert node.output.compute().to_dict(orient="records") == [
        {"id": 1, "name": "A%", "odd": 1},
        {"id": 2, "name": "%%", "odd": 0},
        {"id": 3, "name": "B", "odd": 1},
    ]
