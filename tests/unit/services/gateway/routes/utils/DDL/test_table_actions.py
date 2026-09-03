import pytest
import sqlalchemy as sa

from services.gateway.routes.utils.DDL import table as table_routes

from src.schemas.http.create_table import RecreateTableRequest, TruncateTableRequest


def _column(name: str, dtype: str) -> dict:
    return {
        "name": name,
        "dtype": dtype,
        "nullable": True,
        "index": False,
    }


@pytest.mark.asyncio
async def test_recreate_table_replaces_schema_and_data(
    gateway_client,
    router_prefix,
    tmp_path,
) -> None:
    database_path = tmp_path / "recreate_existing.sqlite"
    connection_string = f"sqlite:///{database_path.as_posix()}"
    engine = sa.create_engine(connection_string)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE items (old_value TEXT)"))
        connection.execute(sa.text("INSERT INTO items VALUES ('old')"))

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/recreate-table",
        json={
            "connection_id": connection_string,
            "table_name": "items",
            "columns": [_column("id", "INT"), _column("new_value", "STRING")],
        },
    )

    assert response.status_code == 200
    assert [column["name"] for column in response.json()["table_metadata"]["columns"]] == [
        "id",
        "new_value",
    ]
    assert engine.connect().execute(sa.text("SELECT COUNT(*) FROM items")).scalar_one() == 0
    inspector = sa.inspect(engine)
    assert not any("__dvt_recreate_" in name for name in inspector.get_table_names())


@pytest.mark.asyncio
async def test_recreate_table_creates_missing_target(
    gateway_client,
    router_prefix,
    tmp_path,
) -> None:
    database_path = tmp_path / "recreate_missing.sqlite"
    connection_string = f"sqlite:///{database_path.as_posix()}"

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/recreate-table",
        json={
            "connection_id": connection_string,
            "table_name": "items",
            "columns": [_column("id", "INT")],
        },
    )

    assert response.status_code == 200
    engine = sa.create_engine(connection_string)
    inspector = sa.inspect(engine)
    assert inspector.has_table("items")
    assert not any("__dvt_recreate_" in name for name in inspector.get_table_names())


@pytest.mark.asyncio
async def test_recreate_named_index_conflict_preserves_source(
    gateway_client,
    router_prefix,
    tmp_path,
) -> None:
    database_path = tmp_path / "recreate_index_conflict.sqlite"
    connection_string = f"sqlite:///{database_path.as_posix()}"
    engine = sa.create_engine(connection_string)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE items (old_value TEXT)"))
        connection.execute(sa.text("CREATE INDEX shared_idx ON items(old_value)"))
        connection.execute(sa.text("INSERT INTO items VALUES ('preserved')"))

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/recreate-table",
        json={
            "connection_id": connection_string,
            "table_name": "items",
            "columns": [_column("new_value", "STRING")],
            "table_create_spec": {
                "indexes": [
                    {
                        "name": "shared_idx",
                        "columns": ["new_value"],
                        "unique": False,
                    }
                ]
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "RECREATE_TABLE_ERROR"
    inspector = sa.inspect(engine)
    assert [column["name"] for column in inspector.get_columns("items")] == ["old_value"]
    assert (
        engine.connect().execute(sa.text("SELECT old_value FROM items")).scalar_one() == "preserved"
    )
    assert not any("__dvt_recreate_" in name for name in inspector.get_table_names())


@pytest.mark.asyncio
async def test_truncate_table_clears_rows_and_returns_metadata(
    gateway_client,
    router_prefix,
    tmp_path,
) -> None:
    database_path = tmp_path / "truncate.sqlite"
    connection_string = f"sqlite:///{database_path.as_posix()}"
    engine = sa.create_engine(connection_string)
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE items (id INTEGER)"))
        connection.execute(sa.text("INSERT INTO items VALUES (1), (2)"))

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/truncate-table",
        json={
            "connection_id": connection_string,
            "table_name": "items",
        },
    )

    assert response.status_code == 200
    assert [column["name"] for column in response.json()["table_metadata"]["columns"]] == ["id"]
    assert engine.connect().execute(sa.text("SELECT COUNT(*) FROM items")).scalar_one() == 0


@pytest.mark.asyncio
async def test_truncate_missing_table_returns_specific_error(
    gateway_client,
    router_prefix,
    tmp_path,
) -> None:
    database_path = tmp_path / "truncate_missing.sqlite"
    connection_string = f"sqlite:///{database_path.as_posix()}"

    response = await gateway_client.post(
        f"{router_prefix}/utils/ddl/truncate-table",
        json={
            "connection_id": connection_string,
            "table_name": "missing",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "TRUNCATE_TABLE_ERROR"


@pytest.mark.parametrize(
    ("action_request", "handler", "operation_name"),
    [
        (
            RecreateTableRequest.model_validate(
                {
                    "connection_id": "connection-1",
                    "database_name": "requested_database",
                    "table_name": "items",
                    "columns": [_column("id", "INT")],
                }
            ),
            table_routes._recreate_table_request,
            "recreate",
        ),
        (
            TruncateTableRequest.model_validate(
                {
                    "connection_id": "connection-1",
                    "database_name": "requested_database",
                    "table_name": "items",
                }
            ),
            table_routes._truncate_table_request,
            "truncate",
        ),
    ],
)
def test_table_action_engine_uses_request_database(
    monkeypatch,
    action_request,
    handler,
    operation_name,
) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE items (id INTEGER)"))

    builder_kwargs = {}

    def fake_build_engine(**kwargs):
        builder_kwargs.update(kwargs)
        return engine

    monkeypatch.setattr(
        table_routes,
        "build_engine_from_connection_string",
        fake_build_engine,
    )
    if operation_name == "recreate":
        monkeypatch.setattr(table_routes, "recreate_table_safely", lambda **kwargs: None)

    handler(action_request, "sqlite://")

    assert builder_kwargs["database_name"] == "requested_database"
