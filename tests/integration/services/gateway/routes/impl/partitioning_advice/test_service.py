from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from services.gateway.routes.impl.partitioning_advice import (
    PartitioningAdviceError,
    PartitioningAdviceRequest,
    suggest_read_partitioning,
)

from src.node_dsl.runtime.connections import resolve_sql_connection_url

pytestmark = pytest.mark.docker_required

ROWS = 50_000


def _connection_string(connection) -> str:
    url = resolve_sql_connection_url(connection)
    return url if isinstance(url, str) else url.render_as_string(hide_password=False)


async def test_postgres_query_advice_runs_in_a_read_only_session(
    postgres_db_connection, postgres_test_engine: sa.Engine
):
    table_name = f"advice_{uuid4().hex[:8]}"
    with postgres_test_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {table_name} AS SELECT n AS id, n % 100 AS store "
                f"FROM generate_series(1, {ROWS}) AS n"
            )
        )
        conn.execute(text(f"CREATE SEQUENCE {table_name}_seq"))
    connection_string = _connection_string(postgres_db_connection)
    try:
        response = await suggest_read_partitioning(
            connection_string,
            PartitioningAdviceRequest(
                sql_code=f"SELECT id, store FROM {table_name} WHERE id > 0",
                npartitions=10,
            ),
        )
        # A data-modifying CTE passes no SELECT policy and never reaches the source.
        with pytest.raises(PartitioningAdviceError) as raised:
            await suggest_read_partitioning(
                connection_string,
                PartitioningAdviceRequest(
                    sql_code=f"WITH d AS (DELETE FROM {table_name} RETURNING id) SELECT id FROM d"
                ),
            )
        # A volatile write function is stopped by the read-only session.
        with pytest.raises(PartitioningAdviceError) as read_only:
            await suggest_read_partitioning(
                connection_string,
                PartitioningAdviceRequest(
                    sql_code=f"SELECT id FROM (SELECT nextval('{table_name}_seq') AS id) s"
                ),
            )
    finally:
        with postgres_test_engine.begin() as conn:
            sequence_called = conn.execute(text(f"SELECT is_called FROM {table_name}_seq")).scalar()
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
            conn.execute(text(f"DROP SEQUENCE IF EXISTS {table_name}_seq"))

    assert response.relation.mode == "query"
    assert response.relation.total_rows == ROWS
    statistics = {item.name: item for item in response.statistics}
    assert statistics["store"].max_repeat == ROWS // 100
    assert response.recommendations[0].partition_col == "id"
    assert raised.value.code == "UNSAFE_SQL"
    assert read_only.value.code == "STATISTICS_FAILED"
    assert "read-only transaction" in read_only.value.message
    assert sequence_called is False


async def test_postgres_query_advice_keeps_percent_signs_of_user_sql(
    postgres_db_connection, postgres_test_engine: sa.Engine
):
    table_name = f"advice_pct_{uuid4().hex[:8]}"
    names = ("A{}", "A%{}", "B{}", "%%{}")
    with postgres_test_engine.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table_name} (id BIGINT PRIMARY KEY, name TEXT)"))
        conn.execute(
            text(f"INSERT INTO {table_name} (id, name) VALUES (:id, :name)"),
            [{"id": row_id, "name": names[row_id % 4].format(row_id)} for row_id in range(1, 1201)],
        )
    try:
        # LIKE wildcard, a literal of two percent signs (as in psql) and the modulo operator.
        response = await suggest_read_partitioning(
            _connection_string(postgres_db_connection),
            PartitioningAdviceRequest(
                sql_code=(
                    f"SELECT id, name FROM {table_name} "
                    "WHERE (name LIKE 'A%' OR left(name, 2) = '%%') AND id % 3 = 0"
                ),
                npartitions=4,
            ),
        )
    finally:
        with postgres_test_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))

    expected = [row_id for row_id in range(1, 1201) if row_id % 4 != 2 and row_id % 3 == 0]
    assert response.relation.mode == "query"
    assert response.relation.total_rows == len(expected)
    assert {item.name for item in response.statistics} == {"id", "name"}


async def test_clickhouse_table_and_query_advice(
    clickhouse_db_connection, clickhouse_http_test_engine: sa.Engine
):
    table_name = f"advice_{uuid4().hex[:8]}"
    with clickhouse_http_test_engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {table_name} (id UInt64, store Int64) ENGINE = MergeTree ORDER BY id"
            )
        )
        conn.execute(
            text(f"INSERT INTO {table_name} SELECT number, number % 100 FROM numbers({ROWS})")
        )
    connection_string = _connection_string(clickhouse_db_connection)
    try:
        table = await suggest_read_partitioning(
            connection_string, PartitioningAdviceRequest(table_name=table_name, npartitions=10)
        )
        query = await suggest_read_partitioning(
            connection_string,
            PartitioningAdviceRequest(sql_code=f"SELECT store FROM {table_name}", npartitions=10),
        )
    finally:
        with clickhouse_http_test_engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))

    assert table.relation.sort_key == "id"
    best = table.recommendations[0]
    assert (best.partition_col, best.partition_grouping) == ("id", {"mode": "range"})
    assert [item.name for item in query.statistics] == ["store"]
    assert query.statistics[0].max_repeat == ROWS // 100
