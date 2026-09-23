"""Isolated SQL sources for comment reflection tests; no DVT database setup."""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from clickhouse_sqlalchemy import Table as ClickHouseTable, engines
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

TABLE_COMMENT = "  Клиенты O'Brien\nОписание таблицы  "
COLUMN_COMMENT = "  Идентификатор\nклиента  "
COMMENT_DIALECTS = ("postgresql", "mysql", "mariadb", "mssql", "oracle", "clickhouse")


@pytest.fixture(scope="session")
def mariadb_comments_container():
    with (
        DockerContainer("mariadb:11.4")
        .with_env("MARIADB_ROOT_PASSWORD", "test")
        .with_env("MARIADB_DATABASE", "test")
        .with_env("MARIADB_USER", "test")
        .with_env("MARIADB_PASSWORD", "test")
        .with_exposed_ports(3306)
        .waiting_for(LogMessageWaitStrategy("port: 3306"))
    ) as container:
        yield container


@pytest.fixture
def comments_engine(request):
    dialect = request.param
    fixture = {
        "postgresql": "postgres_container",
        "mysql": "mysql_container",
        "mariadb": "mariadb_comments_container",
        "mssql": "mssql_container",
        "oracle": "oracle_container",
        "clickhouse": "clickhouse_container",
    }[dialect]
    container = request.getfixturevalue(fixture)
    if dialect == "mariadb":
        url = sa.URL.create(
            "mariadb+pymysql",
            username="test",
            password="test",
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(3306)),
            database="test",
        )
    elif dialect == "clickhouse":
        url = sa.URL.create(
            "clickhouse+http",
            username=container.username,
            password=container.password,
            host=container.get_container_host_ip(),
            port=int(container.get_exposed_port(8123)),
            database=container.dbname,
        )
    else:
        url = sa.make_url(container.get_connection_url())
        if dialect == "mssql":
            import pyodbc

            drivers = [driver for driver in pyodbc.drivers() if "ODBC Driver" in driver]
            if not drivers:
                pytest.skip("Microsoft ODBC driver is required for MSSQL integration tests")
            url = url.update_query_dict({"driver": drivers[-1], "TrustServerCertificate": "yes"})
    engine = sa.create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def commented_table(comments_engine):
    metadata = sa.MetaData()
    columns = [
        sa.Column("id", sa.Integer(), nullable=False, comment=COLUMN_COMMENT),
        sa.Column("value", sa.String(64), nullable=True),
    ]
    name = f"DvtComments_{uuid4().hex[:10]}"
    if comments_engine.dialect.name == "oracle":
        name = name.upper()
    if comments_engine.dialect.name == "clickhouse":
        table = ClickHouseTable(name, metadata, *columns, engines.Memory(), comment=TABLE_COMMENT)
    else:
        table = sa.Table(name, metadata, *columns, comment=TABLE_COMMENT)
    metadata.create_all(comments_engine)
    try:
        with comments_engine.begin() as conn:
            conn.execute(table.insert(), [{"id": 1, "value": "one"}, {"id": 2, "value": "two"}])
        yield table
    finally:
        metadata.drop_all(comments_engine)
