import pytest
from db_connection.errors import ValidationFailedError

from services.task_benchmarking.nodes.benchmark_sql_connection import BenchmarkSqlConnection
from services.task_benchmarking.nodes.benchmark_sql_connection.node import expand_env

from src.logger import logger
from src.node_dsl import SqlConnectionRecord
from src.node_dsl.runtime.connections import resolve_sql_connection_url


def _make_node(**inputs) -> BenchmarkSqlConnection:
    return BenchmarkSqlConnection(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="connection",
        **inputs,
    )


def test_expand_env_resolves_defaults_and_values(monkeypatch) -> None:
    monkeypatch.setenv("BENCH_HOST", "db.internal")
    monkeypatch.setenv("BENCH_EMPTY", "")
    monkeypatch.delenv("BENCH_UNSET", raising=False)

    assert expand_env("${BENCH_HOST:-localhost}") == "db.internal"
    assert expand_env("${BENCH_EMPTY:-localhost}") == "localhost"
    assert expand_env("${BENCH_UNSET:-54321}") == "54321"
    assert expand_env("tcp://${BENCH_HOST}:${BENCH_UNSET:-1}") == "tcp://db.internal:1"
    assert expand_env("plain") == "plain"
    with pytest.raises(ValueError, match="BENCH_UNSET"):
        expand_env("${BENCH_UNSET}")


def test_build_record_expands_env_and_applies_driver_defaults(monkeypatch) -> None:
    monkeypatch.setenv("BENCH_PG_PORT", "6543")
    node = _make_node(
        connection_type="postgres",
        host="${BENCH_PG_HOST_UNSET:-localhost}",
        port="${BENCH_PG_PORT:-54321}",
        database="testdb",
        user="testuser",
        password="testpassword",
    )

    node.process()

    connection = node.connection
    assert isinstance(connection, SqlConnectionRecord)
    assert (connection.kind, connection.type, connection.driver) == ("sql", "postgres", "psycopg")
    assert connection.properties["host"] == "localhost"
    assert connection.properties["port"] == 6543
    assert connection.properties["username"] == "testuser"
    assert connection.secrets["password"] == "testpassword"
    url = resolve_sql_connection_url(connection)
    assert url.render_as_string(hide_password=False) == (
        "postgresql+psycopg://testuser:testpassword@localhost:6543/testdb?connect_timeout=30"
    )


def test_build_record_uses_mssql_odbc_default_and_password_env(monkeypatch) -> None:
    monkeypatch.setenv("BENCH_MSSQL_PASSWORD", "from-env")
    node = _make_node(
        connection_type="mssql",
        host="localhost",
        port=11433,
        database="benchdb",
        user="sa",
        password="ignored",
        password_env="BENCH_MSSQL_PASSWORD",
    )

    connection = node.build_record()

    assert connection.driver == "pyodbc"
    assert connection.driver_options == {"driver_name": "ODBC Driver 18 for SQL Server"}
    assert connection.secrets["password"] == "from-env"
    assert "driver=ODBC+Driver+18+for+SQL+Server" in str(resolve_sql_connection_url(connection))


def test_build_record_falls_back_to_password_when_password_env_is_missing(monkeypatch) -> None:
    monkeypatch.delenv("BENCH_MISSING_PASSWORD", raising=False)
    node = _make_node(
        connection_type="clickhouse",
        host="localhost",
        port="8124",
        database="testdb",
        user="testuser",
        password="testpassword",
        password_env="BENCH_MISSING_PASSWORD",
    )

    assert node.build_record().secrets["password"] == "testpassword"


def test_invalid_record_fails_at_node_without_logging_password() -> None:
    messages: list[str] = []
    handler_id = logger.add(messages.append, level="DEBUG")
    try:
        node = _make_node(
            connection_type="mssql",
            host="localhost",
            port=11433,
            database="benchdb",
            user="sa",
            password="super-secret",
            driver_options={},
        )
        with pytest.raises(ValidationFailedError):
            node.build_record()
        _make_node(
            connection_type="postgres",
            host="localhost",
            port=54321,
            database="testdb",
            user="testuser",
            password="super-secret",
        ).build_record()
    finally:
        logger.remove(handler_id)

    assert messages
    assert not any("super-secret" in message for message in messages)


def test_invalid_port_is_rejected() -> None:
    node = _make_node(
        connection_type="postgres",
        host="localhost",
        port="not-a-port",
        database="testdb",
        user="testuser",
    )

    with pytest.raises(ValueError, match="Invalid port"):
        node.build_record()
