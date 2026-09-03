from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.types import DataFrameMetadata, DataType, DBColumn

from services.gateway.routes.utils.DDL import table as create_table_routes

from src.schemas.http.create_table import GenerateTableDDL


@pytest.mark.parametrize(
    ("dialect_name", "schema_name", "database_name", "expected_schema"),
    [
        ("clickhouse", "public", "analytics", "analytics"),
        ("clickhouse", "public", None, None),
        ("sqlite", "public", "analytics", None),
        ("mysql", "public", "analytics", None),
        ("mariadb", "public", "analytics", None),
        ("postgresql", "public", "analytics", "public"),
    ],
)
def test_resolve_metadata_schema_for_ddl(
    dialect_name: str,
    schema_name: str | None,
    database_name: str | None,
    expected_schema: str | None,
) -> None:
    schema = create_table_routes._resolve_metadata_schema_for_ddl(
        dialect_name=dialect_name,
        schema_name=schema_name,
        database_name=database_name,
    )

    assert schema == expected_schema


@pytest.mark.parametrize(
    ("dialect_name", "primary_key_cols", "preserve_input_nullable", "expected_nullable_by_name"),
    [
        ("clickhouse", None, False, {"id": False, "Period": False}),
        ("postgresql", None, False, {"id": True, "Period": True}),
        ("postgresql", None, True, {"id": False, "Period": False}),
        ("oracle", "id", False, {"id": False, "Period": True}),
    ],
)
def test_normalize_db_columns_nullable_for_ddl(
    dialect_name: str,
    primary_key_cols: str | list[str] | None,
    preserve_input_nullable: bool,
    expected_nullable_by_name: dict[str, bool],
) -> None:
    columns = [
        DBColumn(name="id", dtype=DataType.INT, nullable=False, index=True),
        DBColumn(name="Period", dtype=DataType.STRING, nullable=False, index=False),
    ]

    normalized = create_table_routes._normalize_db_columns_nullable_for_ddl(
        dialect_name=dialect_name,
        columns=columns,
        primary_key_cols=primary_key_cols,
        preserve_input_nullable=preserve_input_nullable,
    )

    assert {column.name: column.nullable for column in normalized} == expected_nullable_by_name
    assert {column.name: column.nullable for column in columns} == {"id": False, "Period": False}


@pytest.mark.asyncio
async def test_generate_table_ddl_applies_nullable_policy_and_passes_primary_key_cols(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        url=SimpleNamespace(database="engine_db"),
        dispose=lambda: None,
    )

    monkeypatch.setattr(
        create_table_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )
    def _fake_generate_create_table_ddl_from_metadata(**kwargs):
        captured.update(kwargs)
        return "CREATE TABLE events (id bigint);"

    monkeypatch.setattr(
        create_table_routes,
        "generate_create_table_ddl_from_metadata",
        _fake_generate_create_table_ddl_from_metadata,
    )

    request = GenerateTableDDL(
        dataframe_metadata=DataFrameMetadata(columns=[]),
        connection_id="postgresql://localhost/db",
        table_name="events",
        database_name="metadata_db",
        schema_name="public",
        table_create_spec={"primary_key_cols": "id"},
    )

    response = await create_table_routes.generate_table_ddl(
        request=request,
        user=None,
    )

    assert captured["schema_name"] == "public"
    assert captured["database_name"] == "metadata_db"
    assert captured["index_col"] is None
    assert captured["table_create_spec"].primary_key_cols == "id"
    assert response.sql == "CREATE TABLE events (id bigint);"


@pytest.mark.asyncio
async def test_generate_table_ddl_prefers_explicit_columns_when_provided(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        url=SimpleNamespace(database="engine_db"),
        dispose=lambda: None,
    )

    monkeypatch.setattr(
        create_table_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )
    monkeypatch.setattr(
        create_table_routes,
        "generate_create_table_ddl_from_metadata",
        lambda **_: pytest.fail("dataframe_metadata path must not be used when columns are provided"),
    )

    def _fake_generate_create_table_ddl_from_columns(**kwargs):
        captured.update(kwargs)
        return 'CREATE TABLE events ("id" bigint NOT NULL);'

    monkeypatch.setattr(
        create_table_routes,
        "generate_create_table_ddl_from_columns",
        _fake_generate_create_table_ddl_from_columns,
    )

    request = GenerateTableDDL(
        dataframe_metadata=DataFrameMetadata(columns=[]),
        connection_id="postgresql://localhost/db",
        table_name="events",
        database_name="metadata_db",
        schema_name="public",
        columns=[
            DBColumn(name="id", dtype=DataType.INT, nullable=False, index=False),
        ],
    )

    response = await create_table_routes.generate_table_ddl(
        request=request,
        user=None,
    )

    assert captured["columns"][0].nullable is False
    assert captured["database_name"] == "metadata_db"
    assert captured["preserve_input_nullable"] is True
    assert response.sql == 'CREATE TABLE events ("id" bigint NOT NULL);'


@pytest.mark.asyncio
async def test_generate_table_ddl_clickhouse_uses_request_database_name(monkeypatch) -> None:
    captured: dict[str, str | None] = {}
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="clickhouse"),
        url=SimpleNamespace(database="engine_db"),
        dispose=lambda: None,
    )

    monkeypatch.setattr(
        create_table_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )
    def _fake_generate_create_table_ddl_from_metadata(**kwargs):
        captured["database_name"] = kwargs["database_name"]
        return "CREATE TABLE events (id Int32);"

    monkeypatch.setattr(
        create_table_routes,
        "generate_create_table_ddl_from_metadata",
        _fake_generate_create_table_ddl_from_metadata,
    )

    request = GenerateTableDDL(
        dataframe_metadata=DataFrameMetadata(columns=[]),
        connection_id="clickhouse://localhost/default",
        table_name="events",
        schema_name="ignored_schema",
        database_name="metadata_db",
    )

    response = await create_table_routes.generate_table_ddl(
        request=request,
        user=None,
    )

    assert captured["database_name"] == "metadata_db"
    assert response.sql == "CREATE TABLE events (id Int32);"


@pytest.mark.asyncio
async def test_generate_table_ddl_clickhouse_prefers_request_database_name(monkeypatch) -> None:
    captured: dict[str, str | None] = {}
    fake_engine = SimpleNamespace(
        dialect=SimpleNamespace(name="clickhouse"),
        url=SimpleNamespace(database="engine_db"),
        dispose=lambda: None,
    )

    monkeypatch.setattr(
        create_table_routes,
        "build_engine_from_connection_string",
        lambda **_: fake_engine,
    )
    def _fake_generate_create_table_ddl_from_metadata(**kwargs):
        captured["database_name"] = kwargs["database_name"]
        return "CREATE TABLE events (id Int32);"

    monkeypatch.setattr(
        create_table_routes,
        "generate_create_table_ddl_from_metadata",
        _fake_generate_create_table_ddl_from_metadata,
    )

    request = GenerateTableDDL(
        dataframe_metadata=DataFrameMetadata(columns=[]),
        connection_id="clickhouse://localhost/default",
        table_name="events",
        schema_name="ignored_schema",
        database_name="request_db",
    )

    response = await create_table_routes.generate_table_ddl(
        request=request,
        user=None,
    )

    assert captured["database_name"] == "request_db"
    assert response.sql == "CREATE TABLE events (id Int32);"
