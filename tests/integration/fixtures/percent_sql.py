"""Tables whose values contain ``%`` on the PostgreSQL and MySQL testcontainers.

For user SQL with ``%`` on drivers with the format/pyformat paramstyle (psycopg, pymysql).
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text

PERCENT_ROWS = 400


def percent_name(row_id: int) -> str:
    """``A4``, ``A%5``, ``B6``, ``%%7``: the name of row ``row_id`` by ``row_id % 4``."""
    return ("A{}", "A%{}", "B{}", "%%{}")[row_id % 4].format(row_id)


@pytest.fixture(params=["postgres", "mysql"])
def percent_table(request) -> Generator[tuple[sa.Engine, str]]:
    """``(engine, table)``: ``id`` 1..PERCENT_ROWS and ``name`` = ``percent_name(id)``."""
    engine: sa.Engine = request.getfixturevalue(f"{request.param}_test_engine")
    table_name = f"pct_{uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table_name} (id BIGINT PRIMARY KEY, name VARCHAR(32))"))
        conn.execute(
            text(f"INSERT INTO {table_name} (id, name) VALUES (:id, :name)"),
            [{"id": row_id, "name": percent_name(row_id)} for row_id in range(1, PERCENT_ROWS + 1)],
        )
    yield engine, table_name
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
