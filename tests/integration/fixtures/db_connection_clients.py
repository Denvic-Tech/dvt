from collections.abc import Generator
from typing import Any

import pytest
import sqlalchemy as sa

from src.node_dsl.runtime import resolve_file_fs_context, resolve_sql_engine

from .db_connections import (
    clickhouse_db_connection,  # noqa: F401
    mongodb_db_connection,  # noqa: F401
    mssql_db_connection,  # noqa: F401
    mysql_db_connection,  # noqa: F401
    oracle_db_connection,  # noqa: F401
    postgres_db_connection,  # noqa: F401
    s3_db_connection,  # noqa: F401
)


@pytest.fixture(scope="function")
def postgres_test_engine(
    postgres_db_connection
) -> Generator[sa.Engine]:
    yield resolve_sql_engine(postgres_db_connection)


@pytest.fixture(scope="function")
def clickhouse_http_test_engine(
    clickhouse_db_connection
) -> Generator[sa.Engine]:
    yield resolve_sql_engine(clickhouse_db_connection)


@pytest.fixture(scope="function")
def mysql_test_engine(
    mysql_db_connection, connection_service
) -> Generator[sa.Engine]:
    yield resolve_sql_engine(mysql_db_connection)


@pytest.fixture(scope="function")
def mongodb_test_engine(
    mongodb_db_connection
) -> Generator[sa.Engine]:
    yield resolve_sql_engine(mongodb_db_connection)


@pytest.fixture(scope="function")
def mssql_test_engine(
    mssql_db_connection
) -> Generator[sa.Engine]:
    yield resolve_sql_engine(mssql_db_connection)


@pytest.fixture(scope="function")
def s3_test_client(s3_db_connection) -> Generator[Any]:
    fs_ctx = resolve_file_fs_context(s3_db_connection, create_fs=True)
    try:
        yield fs_ctx.fs
    finally:
        close = getattr(fs_ctx.fs, "close", None)
        if callable(close):
            close()


@pytest.fixture(scope="function")
def oracle_test_engine(
    oracle_db_connection
) -> Generator[sa.Engine]:
    yield resolve_sql_engine(oracle_db_connection)
