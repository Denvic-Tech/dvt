from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.types import DataType

from services.gateway.routes.utils import sql_query_to_metadata as route_module
from services.gateway.routes.utils.sql_query_to_metadata import _get_metadata

from src.modules.sql_code_metadata.infra import sqlalchemy_result_metadata as result_metadata_module


class _FakeCursor:
    def __init__(self) -> None:
        self.description = [
            ("table_code", str, None, 128, 128, 0, False),
            ("source_schema", str, None, 128, 128, 0, False),
            ("row_cap", int, None, 10, 10, 0, False),
        ]

    def execute(self, sql: str) -> None:
        self._last_sql = sql

    def fetchall(self) -> list[tuple[int, str]]:
        return [
            (56, "int"),
            (167, "varchar"),
            (231, "nvarchar"),
        ]

    def close(self) -> None:
        return None


class _FakeRawConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self) -> None:
        self._cursor = _FakeCursor()

    def raw_connection(self) -> _FakeRawConnection:
        return _FakeRawConnection(self._cursor)


class _FakeDialect:
    name = "mssql"


class _FakeEngine:
    def __init__(self) -> None:
        self.dialect = _FakeDialect()
        self._conn = _FakeConnection()

    def raw_connection(self) -> _FakeRawConnection:
        return self._conn.raw_connection()


@pytest.mark.asyncio
async def test_get_metadata_uses_read_v3_mssql_introspection_for_pyodbc_descriptions() -> None:
    metadata = await _get_metadata(
        connection=_FakeEngine(),
        query=(
            "SELECT table_code, source_schema, row_cap "
            "FROM demo_meta.raw_export_tables "
            "WHERE is_active = 1"
        ),
    )

    assert metadata.statement_count == 1
    assert metadata.result_statement_count == 1
    assert metadata.dataframe_metadata_statement_index == 0
    assert metadata.dataframe_metadata is not None
    assert [column.name for column in metadata.dataframe_metadata.columns] == [
        "table_code",
        "source_schema",
        "row_cap",
    ]
    assert [column.dtype for column in metadata.dataframe_metadata.columns] == [
        DataType.STRING,
        DataType.STRING,
        DataType.INT,
    ]


@pytest.mark.asyncio
async def test_get_metadata_builds_dataframe_metadata_for_mssql_output(monkeypatch) -> None:
    class _FakeInspector:
        def get_columns(self, table_name: str, schema: str | None = None):
            assert table_name == "raw_export_tables"
            assert schema == "demo_meta"
            import sqlalchemy as sa

            return [
                {"name": "id", "type": sa.INTEGER(), "nullable": False},
                {"name": "name", "type": sa.VARCHAR(), "nullable": True},
            ]

    monkeypatch.setattr(result_metadata_module.sa, "inspect", lambda _engine: _FakeInspector())

    metadata = await _get_metadata(
        connection=SimpleNamespace(dialect=SimpleNamespace(name="mssql")),
        query=(
            "UPDATE demo_meta.raw_export_tables "
            "SET id = id "
            "OUTPUT INSERTED.id, DELETED.name"
        ),
    )

    assert metadata.dataframe_metadata is not None
    assert [column.name for column in metadata.dataframe_metadata.columns] == ["id", "name"]
    assert [column.dtype for column in metadata.dataframe_metadata.columns] == [
        DataType.INT,
        DataType.STRING,
    ]


@pytest.mark.asyncio
async def test_sql_query_metadata_route_delegates_to_use_case(monkeypatch) -> None:
    expected = SimpleNamespace(
        statement_count=1,
        result_statement_count=1,
        statements=[],
        dialect_name="postgres",
        dataframe_metadata=None,
        dataframe_metadata_statement_index=0,
    )

    async def _fake_get_metadata(*, connection, query):
        assert connection == "fake-engine"
        assert query == "SELECT 1"
        return expected

    monkeypatch.setattr(route_module, "_get_metadata", _fake_get_metadata)
    monkeypatch.setattr(route_module, "resolve_sql_engine", lambda connection: "fake-engine")

    db_connection = SimpleNamespace(
        id="conn-1",
        kind="sql",
        type="postgres",
        driver="psycopg2",
        properties={"host": "localhost", "port": 5432, "database": "demo", "username": "reader"},
        secrets={"password": "secret"},
    )

    response = await route_module.sql_code_metadata(
        sql_code="SELECT 1",
        db_connection=db_connection,
        session=SimpleNamespace(),
        user=SimpleNamespace(),
    )

    assert response is expected


@pytest.mark.asyncio
async def test_sql_query_metadata_route_disposes_engine(monkeypatch) -> None:
    state = {"disposed": False}

    class _FakeEngine:
        def __init__(self) -> None:
            self.dialect = SimpleNamespace(name="postgres")

        def dispose(self) -> None:
            state["disposed"] = True

    async def _fake_get_metadata(*, connection, query):
        assert isinstance(connection, _FakeEngine)
        assert query == "SELECT 1"
        return "ok"

    monkeypatch.setattr(route_module, "_get_metadata", _fake_get_metadata)
    monkeypatch.setattr(route_module, "resolve_sql_engine", lambda connection: _FakeEngine())

    db_connection = SimpleNamespace(
        id="conn-1",
        kind="sql",
        type="postgres",
        driver="psycopg2",
        properties={"host": "localhost", "port": 5432, "database": "demo", "username": "reader"},
        secrets={"password": "secret"},
    )

    response = await route_module.sql_code_metadata(
        sql_code="SELECT 1",
        db_connection=db_connection,
        session=SimpleNamespace(),
        user=SimpleNamespace(),
    )

    assert response == "ok"
    assert state["disposed"] is True


@pytest.mark.asyncio
async def test_sql_query_metadata_route_resolves_both_project_variable_template_forms(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_get_metadata(*, connection, query):
        captured["connection"] = connection
        captured["query"] = query
        return "ok"

    async def _fake_get_user_project(*, project_id, session, user):
        assert (project_id, session, user) == ("project-1", "session", "user")
        return SimpleNamespace(
            variables={
                "table_name": {"type": "STRING", "value": "warehouse.events"},
                "limit": {"type": "INT", "value": 10},
            }
        )

    monkeypatch.setattr(route_module, "_get_metadata", _fake_get_metadata)
    monkeypatch.setattr(route_module, "_get_user_project", _fake_get_user_project)
    monkeypatch.setattr(route_module, "resolve_sql_engine", lambda connection: "fake-engine")

    db_connection = SimpleNamespace(
        id="conn-1",
        kind="sql",
        type="postgres",
        driver="psycopg2",
        properties={"host": "localhost", "port": 5432, "database": "demo", "username": "reader"},
        secrets={"password": "secret"},
    )

    response = await route_module.sql_code_metadata(
        sql_code=(
            "SELECT * FROM {{ project_variables.table_name }} "
            "LIMIT {{ limit }}"
        ),
        project_id="project-1",
        db_connection=db_connection,
        session="session",
        user="user",
    )

    assert response == "ok"
    assert captured == {
        "connection": "fake-engine",
        "query": 'SELECT * FROM "warehouse"."events" LIMIT 10',
    }


@pytest.mark.asyncio
async def test_sql_query_metadata_route_rejects_project_template_without_project_id(monkeypatch) -> None:
    monkeypatch.setattr(
        route_module,
        "resolve_sql_engine",
        lambda connection: pytest.fail("SQL engine must not be created."),
    )
    db_connection = SimpleNamespace(
        id="conn-1",
        kind="sql",
        type="postgres",
        driver="psycopg2",
        properties={"host": "localhost", "port": 5432, "database": "demo", "username": "reader"},
        secrets={"password": "secret"},
    )

    with pytest.raises(route_module.SQLQueryMetadataExtractionError, match="project_id is required"):
        await route_module.sql_code_metadata(
            sql_code="SELECT * FROM {{ table_name }}",
            db_connection=db_connection,
            session=SimpleNamespace(),
            user=SimpleNamespace(),
        )


@pytest.mark.asyncio
async def test_sql_query_metadata_route_rejects_unknown_project_variable_after_engine_creation(
        monkeypatch,
) -> None:
    engine_created = False

    async def _fake_get_user_project(**kwargs):
        return SimpleNamespace(variables={})

    def _fake_resolve_sql_engine(connection):
        nonlocal engine_created
        engine_created = True
        return SimpleNamespace(dialect=SimpleNamespace(name="postgres"))

    monkeypatch.setattr(route_module, "_get_user_project", _fake_get_user_project)
    monkeypatch.setattr(route_module, "resolve_sql_engine", _fake_resolve_sql_engine)
    db_connection = SimpleNamespace(
        id="conn-1",
        kind="sql",
        type="postgres",
        driver="psycopg2",
        properties={"host": "localhost", "port": 5432, "database": "demo", "username": "reader"},
        secrets={"password": "secret"},
    )

    with pytest.raises(route_module.SQLQueryMetadataExtractionError, match="not found"):
        await route_module.sql_code_metadata(
            sql_code="SELECT * FROM {{ missing_table }}",
            project_id="project-1",
            db_connection=db_connection,
            session=SimpleNamespace(),
            user=SimpleNamespace(),
        )
    assert engine_created is True
