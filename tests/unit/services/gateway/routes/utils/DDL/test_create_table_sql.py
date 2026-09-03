from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from core.db.write_v4 import WriteColumnResolutionResult
from core.types import DataFrameMetadata, DataType, DBColumn

from services.gateway.routes.utils.DDL import table as ddl_table_route

from src.exceptions import ApplyTableColumnActionsError, ResolveWriteColumnsError


def _build_df_metadata_payload() -> dict:
    dataframe_metadata: DataFrameMetadata = DataFrameMetadata(
        columns=[
            DBColumn(
                name="id",
                dtype=DataType.INT,
                nullable=False,
                index=True,
            ),
            DBColumn(
                name="name",
                dtype=DataType.STRING,
                nullable=True,
                index=False,
            )
        ],
        rows_num=None,
        size=None,
    )
    return dataframe_metadata.model_dump()


def _build_sqlite_connection_string(prefix: str) -> str:
    db_name = f"{prefix}_{uuid4().hex}"
    return f"sqlite:///file:{db_name}?mode=memory&cache=shared&uri=true"


def _build_resolve_write_columns_request():
    return ddl_table_route.ResolveWriteColumnsRequest.model_validate(
        {
            "mode": "typed_create",
            "connection_id": "postgresql://user@db/test",
            "table_name": "products",
            "dataframe_metadata": _build_df_metadata_payload(),
        }
    )


@pytest.mark.asyncio
async def test_resolve_write_columns_offloads_sync_resolution(monkeypatch):
    request = _build_resolve_write_columns_request()
    expected = ddl_table_route.ResolveWriteColumnsResponse()
    captured = {}

    async def fake_to_thread(fn, *args, **kwargs):
        captured["fn"] = fn
        captured["args"] = args
        captured["kwargs"] = kwargs
        return expected

    monkeypatch.setattr(ddl_table_route.asyncio, "to_thread", fake_to_thread)

    response = await ddl_table_route.resolve_write_columns(request, object())

    assert response is expected
    assert captured == {
        "fn": ddl_table_route._resolve_write_columns_request,
        "args": (request, "postgresql://user@db/test"),
        "kwargs": {},
    }


@pytest.mark.asyncio
async def test_resolve_write_columns_timeout_returns_resolve_error(monkeypatch):
    request = _build_resolve_write_columns_request()

    async def fake_to_thread(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(ddl_table_route.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(ddl_table_route, "_RESOLVE_WRITE_COLUMNS_REQUEST_TIMEOUT_SEC", 0.01)

    with pytest.raises(ResolveWriteColumnsError) as exc_info:
        await ddl_table_route.resolve_write_columns(request, object())

    assert exc_info.value.name == "RESOLVE_WRITE_COLUMNS_ERROR"
    assert exc_info.value.detail["code"] == "RESOLVE_WRITE_COLUMNS_ERROR"
    assert "Timed out while resolving write columns" in exc_info.value.detail["detail"]


def _build_apply_table_column_actions_request(connection_string: str):
    return ddl_table_route.ApplyTableColumnActionsRequest.model_validate(
        {
            "connection_id": connection_string,
            "table_name": "items",
            "actions": [
                {
                    "type": "drop_column",
                    "column_name": "id",
                }
            ],
        }
    )


def test_apply_table_column_actions_rejects_nested_connection_metadata():
    with pytest.raises(ValidationError):
        ddl_table_route.ApplyTableColumnActionsRequest.model_validate(
            {
                "connection_metadata": {"connection_id": "connection-1"},
                "table_name": "items",
                "actions": [{"type": "drop_column", "column_name": "id"}],
            }
        )


def test_apply_table_column_actions_connection_error_returns_specific_error(monkeypatch):
    request = _build_apply_table_column_actions_request("sqlite://")

    def fail_to_build_engine(**kwargs):
        raise RuntimeError("connection failed")

    monkeypatch.setattr(
        ddl_table_route,
        "build_engine_from_connection_string",
        fail_to_build_engine,
    )

    with pytest.raises(ApplyTableColumnActionsError) as exc_info:
        ddl_table_route._apply_table_column_actions_request(request, "sqlite://")

    assert exc_info.value.detail["code"] == "APPLY_TABLE_COLUMN_ACTIONS_ERROR"
    assert "connection failed" in exc_info.value.detail["detail"]


def test_apply_table_column_actions_execution_error_returns_specific_error_and_disposes_engine(
    monkeypatch,
):
    request = _build_apply_table_column_actions_request("sqlite://")

    class FakeEngine:
        url = sa.engine.make_url("sqlite:///test.db")
        disposed = False

        def dispose(self):
            self.disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(
        ddl_table_route,
        "build_engine_from_connection_string",
        lambda **kwargs: engine,
    )

    def fail_to_apply_actions(**kwargs):
        raise RuntimeError("Cannot DROP or CLEAR all columns")

    monkeypatch.setattr(
        ddl_table_route,
        "apply_table_column_actions",
        fail_to_apply_actions,
    )

    with pytest.raises(ApplyTableColumnActionsError) as exc_info:
        ddl_table_route._apply_table_column_actions_request(request, "sqlite://")

    assert exc_info.value.detail["code"] == "APPLY_TABLE_COLUMN_ACTIONS_ERROR"
    assert "Failed to apply table column actions" in exc_info.value.detail["detail"]
    assert "Cannot DROP or CLEAR all columns" in exc_info.value.detail["detail"]
    assert engine.disposed is True


def test_load_table_columns_for_resolution_uses_inspector_get_columns(monkeypatch):
    captured = {}

    class FakeInspector:
        def get_columns(self, table_name, schema=None):
            captured["table_name"] = table_name
            captured["schema"] = schema
            return [
                {"name": "id", "type": sa.Integer(), "nullable": False},
                {"name": "name", "type": sa.String(), "nullable": True},
            ]

    engine = object()
    monkeypatch.setattr(ddl_table_route.sa, "inspect", lambda inspected: FakeInspector())

    table = ddl_table_route._load_table_columns_for_resolution(
        engine=engine,
        table_name="users",
        schema_name="public",
    )

    assert captured == {"table_name": "users", "schema": "public"}
    assert table.name == "users"
    assert table.schema == "public"
    assert list(table.columns.keys()) == ["id", "name"]
    assert isinstance(table.c.id.type, sa.Integer)
    assert table.c.id.nullable is False
    assert isinstance(table.c.name.type, sa.String)
    assert table.c.name.nullable is True


def test_resolve_write_columns_request_rejects_nested_connection_metadata():
    with pytest.raises(ValidationError):
        ddl_table_route.ResolveWriteColumnsRequest.model_validate(
            {
                "mode": "existing_table",
                "connection_metadata": {"connection_id": "connection-1"},
                "table_name": "products",
                "dataframe_metadata": _build_df_metadata_payload(),
            }
        )


def test_resolve_write_columns_existing_table_uses_light_column_loader(monkeypatch):
    request = ddl_table_route.ResolveWriteColumnsRequest.model_validate(
        {
            "mode": "existing_table",
            "connection_id": "postgresql://user@db/test",
            "table_name": "products",
            "schema_name": "public",
            "dataframe_metadata": _build_df_metadata_payload(),
        }
    )
    captured = {}

    class FakeEngine:
        def dispose(self):
            captured["disposed"] = True

    engine = FakeEngine()
    loaded_table = sa.Table(
        "products",
        sa.MetaData(),
        sa.Column("id", sa.Integer(), nullable=False),
        schema="public",
    )

    def fake_build_engine_from_connection_string(**kwargs):
        return engine

    def fake_load_table_columns_for_resolution(**kwargs):
        captured["loader_kwargs"] = kwargs
        return loaded_table

    def fake_resolve_existing_table_write_columns(**kwargs):
        captured["resolver_kwargs"] = kwargs
        return WriteColumnResolutionResult()

    monkeypatch.setattr(
        ddl_table_route,
        "build_engine_from_connection_string",
        fake_build_engine_from_connection_string,
    )
    monkeypatch.setattr(
        ddl_table_route,
        "_load_table_columns_for_resolution",
        fake_load_table_columns_for_resolution,
    )
    monkeypatch.setattr(
        ddl_table_route,
        "resolve_existing_table_write_columns",
        fake_resolve_existing_table_write_columns,
    )

    response = ddl_table_route._resolve_write_columns_request(
        request,
        "postgresql://user@db/test",
    )

    assert response == ddl_table_route.ResolveWriteColumnsResponse()
    assert captured["loader_kwargs"] == {
        "engine": engine,
        "table_name": "products",
        "schema_name": "public",
    }
    assert captured["resolver_kwargs"]["table"] is loaded_table
    assert captured["resolver_kwargs"]["dataframe_metadata"] == request.dataframe_metadata
    assert captured["disposed"] is True


def test_resolve_write_columns_disposes_engine(monkeypatch):
    request = _build_resolve_write_columns_request()

    class FakeURL:
        database = "test"

    class FakeDialect:
        name = "postgresql"

    class FakeEngine:
        url = FakeURL()
        dialect = FakeDialect()

        def __init__(self):
            self.disposed = False

        def dispose(self):
            self.disposed = True

    engine = FakeEngine()

    def fake_build_engine_from_connection_string(**kwargs):
        assert kwargs["connect_timeout_sec"] == 25
        return engine

    def fake_resolve_typed_create_write_columns(**kwargs):
        return WriteColumnResolutionResult()

    monkeypatch.setattr(
        ddl_table_route,
        "build_engine_from_connection_string",
        fake_build_engine_from_connection_string,
    )
    monkeypatch.setattr(
        ddl_table_route,
        "resolve_typed_create_write_columns",
        fake_resolve_typed_create_write_columns,
    )

    response = ddl_table_route._resolve_write_columns_request(
        request,
        "postgresql://user@db/test",
    )

    assert response == ddl_table_route.ResolveWriteColumnsResponse()
    assert engine.disposed is True


@pytest.mark.asyncio
async def test_create_table_sql_returns_create_statement(gateway_client, router_prefix):
    connection_string = _build_sqlite_connection_string("create_table_sql")

    payload = {
        "dataframe_metadata": _build_df_metadata_payload(),
        "connection_id": connection_string,
        "table_name": "users",
        "index_col": "id",
    }

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/generate-table-ddl",
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert "sql" in body
    assert "CREATE TABLE" in body["sql"].upper()
    assert "users" in body["sql"]


@pytest.mark.asyncio
async def test_generate_table_ddl_from_explicit_columns_preserves_nullable(gateway_client, router_prefix):
    connection_string = _build_sqlite_connection_string("generate_table_ddl_explicit_columns")

    payload = {
        "connection_id": connection_string,
        "table_name": "users",
        "columns": [
            {
                "name": "id",
                "dtype": "INT",
                "nullable": False,
                "index": False,
            },
            {
                "name": "name",
                "dtype": "STRING",
                "nullable": True,
                "index": False,
            },
        ],
    }

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/generate-table-ddl",
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert '"id" BIGINT NOT NULL' in body["sql"]
    assert body["sql"].upper().count("NOT NULL") == 1


@pytest.mark.asyncio
async def test_generate_table_ddl_from_explicit_columns_applies_primary_key_spec(
    gateway_client, router_prefix
):
    connection_string = _build_sqlite_connection_string("generate_table_ddl_explicit_columns_pk")

    payload = {
        "connection_id": connection_string,
        "table_name": "users",
        "columns": [
            {
                "name": "id",
                "dtype": "INT",
                "nullable": True,
                "index": False,
            },
        ],
        "table_create_spec": {
            "primary_key_cols": "id",
        },
    }

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/generate-table-ddl",
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert '"id" BIGINT NOT NULL' in body["sql"]
    assert "PRIMARY KEY" in body["sql"].upper()


@pytest.mark.asyncio
async def test_resolve_write_columns_typed_create_does_not_create_table(gateway_client, router_prefix):
    connection_string = _build_sqlite_connection_string("resolve_write_columns_typed_create")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        payload = {
            "mode": "typed_create",
            "connection_id": connection_string,
            "table_name": "products",
            "dataframe_metadata": {
                "type": "DATAFRAME",
                "columns": [
                    {
                        "name": "Код",
                        "dtype": "INT",
                        "nullable": False,
                        "index": False,
                    },
                ],
            },
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/resolve-write-columns",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["effective_column_mapping"] == [
            {
                "source_name": "Код",
                "target_name": "kod",
                "dtype": "INT",
                "nullable": False,
            }
        ]
        assert body["columns"][0]["requested_target_name"] == "Код"
        assert body["columns"][0]["effective_target_name"] == "kod"
        assert sa.inspect(keeper_engine).has_table("products") is False
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_resolve_write_columns_accepts_sql_dtype_strings_in_mapping(
    gateway_client, router_prefix
):
    connection_string = _build_sqlite_connection_string("resolve_write_columns_sql_dtype_mapping")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        with keeper_engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE metrics (score REAL)"))

        payload = {
            "mode": "existing_table",
            "connection_id": connection_string,
            "table_name": "metrics",
            "dataframe_metadata": {
                "type": "DATAFRAME",
                "columns": [
                    {
                        "name": "score",
                        "dtype": "FLOAT",
                        "nullable": False,
                        "index": False,
                    },
                ],
            },
            "column_mapping": [
                {
                    "source_name": "score",
                    "target_name": "score",
                    "dtype": "Float64",
                    "nullable": False,
                },
            ],
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/resolve-write-columns",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["columns"][0]["source_dtype"] == "FLOAT"
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_resolve_write_columns_existing_table_returns_suggested_actions(
    gateway_client, router_prefix
):
    connection_string = _build_sqlite_connection_string("resolve_write_columns_suggested_actions")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        with keeper_engine.begin() as conn:
            conn.execute(
                sa.text("CREATE TABLE metrics (id INTEGER NOT NULL, score TEXT, obsolete TEXT)")
            )

        payload = {
            "mode": "existing_table",
            "connection_id": connection_string,
            "table_name": "metrics",
            "dataframe_metadata": {
                "type": "DATAFRAME",
                "columns": [
                    {
                        "name": "id",
                        "dtype": "INT",
                        "nullable": False,
                        "index": False,
                    },
                    {
                        "name": "score",
                        "dtype": "FLOAT",
                        "nullable": True,
                        "index": False,
                    },
                    {
                        "name": "name",
                        "dtype": "STRING",
                        "nullable": True,
                        "index": False,
                    },
                ],
            },
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/resolve-write-columns",
            json=payload,
        )

        assert response.status_code == 200
        rows = response.json()["columns"]
        actions_by_column = {
            row["suggested_action"]["column_name"]: row["suggested_action"]["type"]
            for row in rows
            if row.get("suggested_action")
        }

        assert actions_by_column == {
            "score": "recreate_column",
            "name": "add_column",
            "obsolete": "drop_column",
        }
        score_row = next(row for row in rows if row.get("source_name") == "score")
        assert score_row["status"] == "type_mismatch"
        assert score_row["source_dtype"] == "FLOAT"
        assert score_row["db_dtype"] == "TEXT"
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_create_table_from_schema_creates_table(gateway_client, router_prefix):
    connection_string = _build_sqlite_connection_string("create_table_from_schema")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        payload = {
            "mode": "from_schema",
            "table_name": "users",
            "connection_id": connection_string,
            "columns": [
                {
                    "name": "id",
                    "dtype": "INT",
                    "nullable": False,
                    "index": True,
                },
                {
                    "name": "name",
                    "dtype": "STRING",
                    "nullable": True,
                    "index": False,
                },
            ],
            "on_exists": "error",
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/create-table",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True

        inspector = sa.inspect(keeper_engine)
        assert inspector.has_table("users") is True
        nullable_by_name = {
            column["name"]: column["nullable"]
            for column in inspector.get_columns("users")
        }
        assert nullable_by_name == {
            "id": False,
            "name": True,
        }
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_create_table_from_schema_applies_table_create_spec(gateway_client, router_prefix):
    connection_string = _build_sqlite_connection_string("create_table_from_schema_with_spec")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        payload = {
            "mode": "from_schema",
            "table_name": "users",
            "connection_id": connection_string,
            "columns": [
                {
                    "name": "id",
                    "dtype": "INT",
                    "nullable": False,
                    "index": True,
                },
                {
                    "name": "name",
                    "dtype": "STRING",
                    "nullable": True,
                    "index": False,
                },
            ],
            "table_create_spec": {
                "primary_key_cols": "id",
                "indexes": [
                    {
                        "name": "users_name_idx",
                        "columns": ["name"],
                        "unique": True,
                    }
                ],
            },
            "on_exists": "error",
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/create-table",
            json=payload,
        )

        assert response.status_code == 200

        inspector = sa.inspect(keeper_engine)
        assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
        index_names = {index["name"] for index in inspector.get_indexes("users")}
        assert "users_name_idx" in index_names
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_create_table_from_sql_creates_table(gateway_client, router_prefix):
    connection_string = _build_sqlite_connection_string("create_table_from_sql")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        payload = {
            "mode": "from_sql",
            "connection_id": connection_string,
            "table_ddl": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
            "on_exists": "error",
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/create-table",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True

        inspector = sa.inspect(keeper_engine)
        assert inspector.has_table("users") is True
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_create_table_from_sql_on_exists_ignore(gateway_client, router_prefix):
    connection_string = _build_sqlite_connection_string("create_table_from_sql_ignore")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        with keeper_engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"))

        payload = {
            "mode": "from_sql",
            "connection_id": connection_string,
            "table_ddl": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);",
            "on_exists": "ignore",
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/create-table",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert "already exists" in body["message"].lower()
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_generate_table_ddl_includes_indexes_from_table_create_spec(
    gateway_client, router_prefix
):
    connection_string = _build_sqlite_connection_string("generate_table_ddl_with_spec")

    payload = {
        "dataframe_metadata": _build_df_metadata_payload(),
        "connection_id": connection_string,
        "table_name": "users",
        "index_col": "id",
        "table_create_spec": {
            "primary_key_cols": "id",
            "indexes": [
                {
                    "name": "users_name_idx",
                    "columns": ["name"],
                    "unique": True,
                }
            ],
        },
    }

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/generate-table-ddl",
        json=payload,
    )

    assert response.status_code == 200
    body = response.json()
    assert "CREATE TABLE" in body["sql"].upper()
    assert "CREATE UNIQUE INDEX" in body["sql"].upper()
    assert "users_name_idx" in body["sql"]


@pytest.mark.asyncio
async def test_apply_table_column_actions_dry_run_does_not_change_table(
    gateway_client, router_prefix
):
    connection_string = _build_sqlite_connection_string("apply_column_actions_dry_run")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        with keeper_engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE items (id INTEGER, old_value TEXT)"))

        payload = {
            "connection_id": connection_string,
            "table_name": "items",
            "dry_run": True,
            "actions": [
                {
                    "type": "add_column",
                    "column_name": "new_value",
                    "column": {
                        "name": "new_value",
                        "dtype": "STRING",
                        "nullable": True,
                        "index": False,
                    },
                },
            ],
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/apply-table-column-actions",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["sql"]
        assert body["applied_actions"][0]["type"] == "add_column"

        column_names = {
            column["name"]
            for column in sa.inspect(keeper_engine).get_columns("items")
        }
        assert "new_value" not in column_names
    finally:
        keeper_conn.close()


@pytest.mark.asyncio
async def test_apply_table_column_actions_applies_bulk_changes(
    gateway_client, router_prefix
):
    connection_string = _build_sqlite_connection_string("apply_column_actions_bulk")
    keeper_engine = sa.create_engine(connection_string)
    keeper_conn = keeper_engine.connect()

    try:
        with keeper_engine.begin() as conn:
            conn.execute(
                sa.text("CREATE TABLE items (id INTEGER, old_value TEXT, score TEXT)")
            )

        payload = {
            "connection_id": connection_string,
            "table_name": "items",
            "actions": [
                {
                    "type": "add_column",
                    "column_name": "new_value",
                    "column": {
                        "name": "new_value",
                        "dtype": "STRING",
                        "nullable": True,
                        "index": False,
                    },
                },
                {
                    "type": "drop_column",
                    "column_name": "old_value",
                },
                {
                    "type": "recreate_column",
                    "column_name": "score",
                    "column": {
                        "name": "score",
                        "dtype": "FLOAT",
                        "nullable": True,
                        "index": False,
                    },
                },
            ],
        }

        response = await gateway_client.post(
            f"{router_prefix}/utils/ddl/apply-table-column-actions",
            json=payload,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert len(body["applied_actions"]) == 3
        assert len(body["sql"]) == 4

        columns = {
            column["name"]: str(column["type"])
            for column in sa.inspect(keeper_engine).get_columns("items")
        }
        assert "old_value" not in columns
        assert "new_value" in columns
        assert "score" in columns
        assert "FLOAT" in columns["score"].upper()
    finally:
        keeper_conn.close()
