from __future__ import annotations

from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from services.gateway.routes.utils.DDL import database as database_routes, schema as schema_routes

from src.exceptions import DDLError
from src.schemas.http.create_table import (
    CreateDatabaseRequest,
    CreateSchemaRequest,
    GenerateSchemaDDLRequest,
)


def _connection_id(
    connection_string: str = "postgresql://localhost/postgres",
) -> str:
    return connection_string


@pytest.mark.asyncio
async def test_create_database_returns_existing_message(monkeypatch) -> None:
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        dispose=lambda: None,
    )

    monkeypatch.setattr(
        database_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )
    monkeypatch.setattr(database_routes, "_database_exists", lambda *_: True)

    response = await database_routes.create_database(
        request=CreateDatabaseRequest(
            connection_id=_connection_id(),
            database_name="analytics",
        ),
        user=None,
        redis=object(),
    )

    assert response.success is True
    assert response.message == 'Database "analytics" already exists.'


@pytest.mark.asyncio
async def test_create_database_executes_ddl(monkeypatch) -> None:
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        dispose=lambda: None,
    )
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        database_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )
    monkeypatch.setattr(database_routes, "_database_exists", lambda *_: False)
    monkeypatch.setattr(database_routes, "_build_create_database_sql", lambda *_: 'CREATE DATABASE "analytics"')
    monkeypatch.setattr(
        database_routes,
        "execute_create_database",
        lambda _engine, sql: captured.setdefault("sql", sql),
    )

    response = await database_routes.create_database(
        request=CreateDatabaseRequest(
            connection_id=_connection_id(),
            database_name="analytics",
        ),
        user=None,
        redis=object(),
    )

    assert response.success is True
    assert captured["sql"] == 'CREATE DATABASE "analytics"'


@pytest.mark.asyncio
async def test_generate_schema_ddl_returns_sql(monkeypatch) -> None:
    fake_engine = sa.create_mock_engine("postgresql://", executor=lambda *args, **kwargs: None)
    fake_engine.dispose = lambda: None

    monkeypatch.setattr(
        schema_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )

    response = await schema_routes.generate_schema_ddl(
        request=GenerateSchemaDDLRequest(
            connection_id=_connection_id(),
            schema_name="analytics",
        ),
        user=None,
    )

    assert response.sql == "CREATE SCHEMA analytics;"


@pytest.mark.asyncio
async def test_create_schema_returns_existing_message(monkeypatch) -> None:
    fake_engine = sa.create_mock_engine("postgresql://", executor=lambda *args, **kwargs: None)
    fake_engine.dispose = lambda: None

    monkeypatch.setattr(
        schema_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )
    monkeypatch.setattr(
        schema_routes.sa,
        "inspect",
        lambda _engine: SimpleNamespace(has_schema=lambda schema_name: schema_name == "analytics"),
    )

    response = await schema_routes.create_schema(
        request=CreateSchemaRequest(
            connection_id=_connection_id(),
            schema_name="analytics",
        ),
        user=None,
        redis=object(),
    )

    assert response.success is True
    assert response.message == 'Schema "analytics" already exists.'


@pytest.mark.asyncio
async def test_generate_schema_ddl_rejects_clickhouse(monkeypatch) -> None:
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="clickhouse"),
        dispose=lambda: None,
    )

    monkeypatch.setattr(
        schema_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )

    with pytest.raises(DDLError, match="does not support CREATE SCHEMA"):
        await schema_routes.generate_schema_ddl(
            request=GenerateSchemaDDLRequest(
                connection_id=_connection_id("clickhouse://localhost/default"),
                schema_name="analytics",
            ),
            user=None,
        )
