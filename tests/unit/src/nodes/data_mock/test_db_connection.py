import pytest
import sqlalchemy as sa

from core.types import DBMetadata, DataType, MetadataType

from src.nodes.data_mock.db_connection import GetMockDBConnection


@pytest.mark.parametrize(
    ("connection_type", "expected_dialect", "expected_drivername"),
    [
        ("postgres", "postgresql", "postgresql+psycopg"),
        ("mysql", "mysql", "mysql+pymysql"),
        ("clickhouse", "clickhouse", "clickhouse+http"),
        ("mssql", "mssql", "mssql+pyodbc"),
        ("oracle", "oracle", "oracle+oracledb"),
        ("mongodb", "mongodb", "mongodb"),
    ],
)
@pytest.mark.asyncio
async def test_get_mock_db_connection_builds_engine_with_expected_dialect(
    connection_type: str,
    expected_dialect: str,
    expected_drivername: str,
):
    node = GetMockDBConnection(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id=f"node-{connection_type}",
        connection_type=connection_type,
    )

    await node.process()

    assert isinstance(node.connection, sa.Engine)
    assert node.connection.dialect.name == expected_dialect
    assert node.connection.url.drivername == expected_drivername
    assert node.connection.url.host == "mock-host"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "connection_type",
        "expected_database_name",
        "top_level_kind",
        "expected_top_level_names",
        "lookup_kwargs",
        "expected_column_types",
    ),
    [
        (
            "postgres",
            "mock_database",
            "databases",
            {"mock_database", "warehouse"},
            {"database_name": "mock_database", "schema_name": "public", "table_name": "users"},
            {"id": DataType.INT, "email": DataType.STRING, "profile": DataType.DICTIONARY},
        ),
        (
            "mysql",
            "mock_database",
            "schemas",
            {"mock_database", "analytics_archive"},
            {"database_name": "mock_database", "schema_name": "mock_database", "table_name": "orders"},
            {"order_id": DataType.INT, "status": DataType.STRING},
        ),
        (
            "mssql",
            "mock_database",
            "databases",
            {"mock_database", "sandbox"},
            {"database_name": "mock_database", "schema_name": "dbo", "table_name": "accounts"},
            {"account_id": DataType.INT, "external_id": DataType.STRING, "is_active": DataType.BOOLEAN},
        ),
        (
            "oracle",
            "FREEPDB1",
            "schemas",
            {"MOCK_USER"},
            {"database_name": "MOCK_USER", "schema_name": "MOCK_USER", "table_name": "CUSTOMER_ACCOUNTS"},
            {"ACCOUNT_ID": DataType.INT, "EMAIL": DataType.STRING, "CREATED_AT": DataType.DATETIME},
        ),
        (
            "clickhouse",
            "mock_database",
            "databases",
            {"mock_database", "analytics_archive"},
            {"database_name": "mock_database", "schema_name": None, "table_name": "events_local"},
            {"event_id": DataType.INT, "event_time": DataType.DATETIME, "payload_json": DataType.STRING},
        ),
        (
            "mongodb",
            "mock_database",
            "databases",
            {"mock_database", "analytics_archive"},
            {"database_name": "mock_database", "schema_name": None, "table_name": "users"},
            {"_id": DataType.STRING, "profile": DataType.DICTIONARY, "created_at": DataType.DATETIME},
        ),
    ],
)
async def test_get_mock_db_connection_returns_realistic_metadata_for_connection_type(
    connection_type: str,
    expected_database_name: str,
    top_level_kind: str,
    expected_top_level_names: set[str],
    lookup_kwargs: dict[str, str | None],
    expected_column_types: dict[str, DataType],
):
    node = GetMockDBConnection(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id=f"node-{connection_type}-metadata",
        connection_type=connection_type,
    )

    metadata = await node.resolve_metadata()
    connection_metadata = metadata["connection"]

    assert isinstance(connection_metadata, DBMetadata)
    assert connection_metadata.type == MetadataType.DATABASE
    assert connection_metadata.database_name == expected_database_name
    assert connection_metadata.connection_string
    assert "***@" in connection_metadata.connection_string

    if top_level_kind == "databases":
        assert {database.name for database in connection_metadata.databases} == expected_top_level_names
        assert not connection_metadata.schemas
    else:
        assert {schema.name for schema in connection_metadata.schemas} == expected_top_level_names
        assert not connection_metadata.databases

    table = connection_metadata.find_table(**lookup_kwargs)
    assert table is not None

    column_types = {column.name: column.dtype for column in table.columns}
    for column_name, expected_dtype in expected_column_types.items():
        assert column_types[column_name] == expected_dtype
