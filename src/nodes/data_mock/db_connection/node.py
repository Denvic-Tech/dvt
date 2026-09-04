from typing import Literal

import sqlalchemy as sa
from sqlalchemy.engine import default as sa_default
from sqlalchemy.pool import StaticPool

from core.metadata.db_metadata.helpers import (
    _rows_to_db_tables,
    build_database_db_metadata,
    build_database_schema_db_metadata,
    build_schema_db_metadata,
)
from core.types import DataType, DBColumn, DBMetadata, DBTable, DBTableType

from src.node_dsl import InputField, OutputField, SqlConnectionOutputBaseNode


def _raise_mock_connection_error():
    raise RuntimeError("Mock DB connection cannot be used for real database operations")


_MOCK_SQLALCHEMY_URLS: dict[str, sa.URL] = {
    "postgres": sa.URL.create(
        "postgresql+psycopg",
        username="mock_user",
        password="mock_password",
        host="mock-host",
        port=5432,
        database="mock_database",
    ),
    "mysql": sa.URL.create(
        "mysql+pymysql",
        username="mock_user",
        password="mock_password",
        host="mock-host",
        port=3306,
        database="mock_database",
    ),
    "clickhouse": sa.URL.create(
        "clickhouse+http",
        username="mock_user",
        password="mock_password",
        host="mock-host",
        port=8123,
        database="mock_database",
    ),
    "mssql": sa.URL.create(
        "mssql+pyodbc",
        username="mock_user",
        password="mock_password",
        host="mock-host",
        port=1433,
        database="mock_database",
        query={"driver": "ODBC Driver 18 for SQL Server"},
    ),
    "oracle": sa.URL.create(
        "oracle+oracledb",
        username="mock_user",
        password="mock_password",
        host="mock-host",
        port=1521,
        database="FREEPDB1",
    ),
    "mongodb": sa.URL.create(
        "mongodb",
        username="mock_user",
        password="mock_password",
        host="mock-host",
        port=27017,
        database="mock_database",
    ),
}


def _normalize_connection_type(connection_type: object) -> str:
    return str(getattr(connection_type, "value", connection_type)).lower()


def _build_mock_sql_engine(connection_type: str) -> sa.Engine:
    url = _MOCK_SQLALCHEMY_URLS[connection_type]

    if connection_type == "mongodb":
        dialect = sa_default.DefaultDialect()
        dialect.name = "mongodb"
        dialect.driver = "mock"
        return sa.Engine(StaticPool(creator=_raise_mock_connection_error), dialect, url)

    return sa.create_engine(
        url,
        creator=_raise_mock_connection_error,
        poolclass=StaticPool,
    )


def _build_postgres_mock_metadata(engine: sa.Engine) -> DBMetadata:
    rows = [
        {
            "database_name": "mock_database",
            "table_schema": "public",
            "table_name": "users",
            "column_name": "id",
            "data_type": "bigint",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "users_pkey [btree]",
            "is_primary_key": True,
        },
        {
            "database_name": "mock_database",
            "table_schema": "public",
            "table_name": "users",
            "column_name": "email",
            "data_type": "character varying",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "users_email_key [btree]",
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "public",
            "table_name": "users",
            "column_name": "profile",
            "data_type": "jsonb",
            "is_nullable": "YES",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "marts",
            "table_name": "daily_revenue",
            "column_name": "report_date",
            "data_type": "date",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "marts",
            "table_name": "daily_revenue",
            "column_name": "total_revenue",
            "data_type": "numeric",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "warehouse",
            "table_schema": "staging",
            "table_name": "events_raw",
            "column_name": "event_id",
            "data_type": "uuid",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "events_raw_pkey [btree]",
            "is_primary_key": True,
        },
        {
            "database_name": "warehouse",
            "table_schema": "staging",
            "table_name": "events_raw",
            "column_name": "payload",
            "data_type": "jsonb",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "warehouse",
            "table_schema": "staging",
            "table_name": "events_raw",
            "column_name": "ingested_at",
            "data_type": "timestamp with time zone",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "events_raw_ingested_at_idx [brin]",
            "is_primary_key": False,
        },
    ]
    return build_database_schema_db_metadata(
        dialect="postgresql",
        database_names=["mock_database", "warehouse"],
        schema_names_by_database={
            "mock_database": ["marts", "public"],
            "warehouse": ["staging"],
        },
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )


def _build_mysql_mock_metadata(engine: sa.Engine) -> DBMetadata:
    rows = [
        {
            "database_name": "mock_database",
            "table_schema": "mock_database",
            "table_name": "customers",
            "column_name": "id",
            "data_type": "bigint",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "PRIMARY",
            "is_primary_key": True,
        },
        {
            "database_name": "mock_database",
            "table_schema": "mock_database",
            "table_name": "customers",
            "column_name": "segment",
            "data_type": "enum",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": "retail,enterprise,partner",
            "indexes": "idx_customers_segment",
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "mock_database",
            "table_name": "customers",
            "column_name": "profile_json",
            "data_type": "json",
            "is_nullable": "YES",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "mock_database",
            "table_name": "orders",
            "column_name": "order_id",
            "data_type": "bigint",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "PRIMARY",
            "is_primary_key": True,
        },
        {
            "database_name": "mock_database",
            "table_schema": "mock_database",
            "table_name": "orders",
            "column_name": "status",
            "data_type": "enum",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": "draft,paid,shipped,cancelled",
            "indexes": "idx_orders_status",
            "is_primary_key": False,
        },
        {
            "database_name": "analytics_archive",
            "table_schema": "analytics_archive",
            "table_name": "order_rollup",
            "column_name": "order_day",
            "data_type": "date",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "analytics_archive",
            "table_schema": "analytics_archive",
            "table_name": "order_rollup",
            "column_name": "gross_amount",
            "data_type": "decimal",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
    ]
    return build_schema_db_metadata(
        dialect="mysql",
        schema_names=["analytics_archive", "mock_database"],
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )


def _build_mssql_mock_metadata(engine: sa.Engine) -> DBMetadata:
    rows = [
        {
            "database_name": "mock_database",
            "table_schema": "dbo",
            "table_name": "accounts",
            "column_name": "account_id",
            "data_type": "bigint",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "PK_accounts",
            "is_primary_key": True,
        },
        {
            "database_name": "mock_database",
            "table_schema": "dbo",
            "table_name": "accounts",
            "column_name": "external_id",
            "data_type": "uniqueidentifier",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "UQ_accounts_external_id",
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "dbo",
            "table_name": "accounts",
            "column_name": "is_active",
            "data_type": "bit",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "reporting",
            "table_name": "fact_orders",
            "column_name": "order_date",
            "data_type": "datetime2",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": "reporting",
            "table_name": "fact_orders",
            "column_name": "gross_amount",
            "data_type": "decimal",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "sandbox",
            "table_schema": "stage",
            "table_name": "import_queue",
            "column_name": "payload",
            "data_type": "nvarchar",
            "is_nullable": "NO",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
    ]
    return build_database_schema_db_metadata(
        dialect="mssql",
        database_names=["mock_database", "sandbox"],
        schema_names_by_database={
            "mock_database": ["dbo", "reporting"],
            "sandbox": ["stage"],
        },
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )


def _build_oracle_mock_metadata(engine: sa.Engine) -> DBMetadata:
    schema_name = "MOCK_USER"
    rows = [
        {
            "database_name": schema_name,
            "table_schema": schema_name,
            "table_name": "CUSTOMER_ACCOUNTS",
            "column_name": "ACCOUNT_ID",
            "data_type": "NUMBER(19,0)",
            "is_nullable": "N",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "PK_CUSTOMER_ACCOUNTS",
            "is_primary_key": True,
        },
        {
            "database_name": schema_name,
            "table_schema": schema_name,
            "table_name": "CUSTOMER_ACCOUNTS",
            "column_name": "EMAIL",
            "data_type": "VARCHAR2(320)",
            "is_nullable": "N",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": "UQ_CUSTOMER_ACCOUNTS_EMAIL",
            "is_primary_key": False,
        },
        {
            "database_name": schema_name,
            "table_schema": schema_name,
            "table_name": "CUSTOMER_ACCOUNTS",
            "column_name": "CREATED_AT",
            "data_type": "TIMESTAMP(6)",
            "is_nullable": "N",
            "udt_name": None,
            "table_type": "BASE TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": schema_name,
            "table_schema": schema_name,
            "table_name": "DAILY_BALANCE_V",
            "column_name": "BALANCE_DATE",
            "data_type": "DATE",
            "is_nullable": "N",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": schema_name,
            "table_schema": schema_name,
            "table_name": "DAILY_BALANCE_V",
            "column_name": "BALANCE_AMOUNT",
            "data_type": "NUMBER(12,2)",
            "is_nullable": "N",
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
    ]
    return build_schema_db_metadata(
        dialect="oracle",
        schema_names=[schema_name],
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )


def _build_clickhouse_mock_metadata(engine: sa.Engine) -> DBMetadata:
    rows = [
        {
            "database_name": "mock_database",
            "table_schema": None,
            "table_name": "events_local",
            "column_name": "event_id",
            "data_type": "UInt64",
            "is_nullable": False,
            "udt_name": None,
            "table_type": "BASE_TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": None,
            "table_name": "events_local",
            "column_name": "event_time",
            "data_type": "DateTime64(3)",
            "is_nullable": False,
            "udt_name": None,
            "table_type": "BASE_TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": None,
            "table_name": "events_local",
            "column_name": "source",
            "data_type": "Enum8('web' = 1, 'mobile' = 2, 'api' = 3)",
            "is_nullable": False,
            "udt_name": None,
            "table_type": "BASE_TABLE",
            "enum_values": "web,mobile,api",
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "mock_database",
            "table_schema": None,
            "table_name": "events_local",
            "column_name": "payload_json",
            "data_type": "Nullable(String)",
            "is_nullable": True,
            "udt_name": None,
            "table_type": "BASE_TABLE",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "analytics_archive",
            "table_schema": None,
            "table_name": "daily_metrics_mv",
            "column_name": "metric_date",
            "data_type": "Date",
            "is_nullable": False,
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
        {
            "database_name": "analytics_archive",
            "table_schema": None,
            "table_name": "daily_metrics_mv",
            "column_name": "gross_revenue",
            "data_type": "Decimal(18, 2)",
            "is_nullable": False,
            "udt_name": None,
            "table_type": "VIEW",
            "enum_values": None,
            "indexes": None,
            "is_primary_key": False,
        },
    ]
    return build_database_db_metadata(
        dialect="clickhouse",
        database_names=["analytics_archive", "mock_database"],
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )


def _build_mongodb_mock_metadata(engine: sa.Engine) -> DBMetadata:
    tables = [
        DBTable(
            database_name="mock_database",
            schema_name=None,
            name="users",
            type=DBTableType.BASE_TABLE,
            columns=[
                DBColumn(name="_id", dtype=DataType.STRING, nullable=False, index=True, indexes=["_id_"], primary_key=True),
                DBColumn(
                    name="profile",
                    dtype=DataType.DICTIONARY,
                    nullable=False,
                    index=False,
                    indexes=None,
                    primary_key=False,
                ),
                DBColumn(
                    name="created_at",
                    dtype=DataType.DATETIME,
                    nullable=False,
                    index=True,
                    indexes=["created_at_1"],
                    primary_key=False,
                ),
            ],
        ),
        DBTable(
            database_name="mock_database",
            schema_name=None,
            name="events",
            type=DBTableType.BASE_TABLE,
            columns=[
                DBColumn(name="_id", dtype=DataType.STRING, nullable=False, index=True, indexes=["_id_"], primary_key=True),
                DBColumn(
                    name="event_type",
                    dtype=DataType.STRING,
                    nullable=False,
                    index=True,
                    indexes=["event_type_1"],
                    primary_key=False,
                ),
                DBColumn(
                    name="payload",
                    dtype=DataType.DICTIONARY,
                    nullable=False,
                    index=False,
                    indexes=None,
                    primary_key=False,
                ),
            ],
        ),
        DBTable(
            database_name="analytics_archive",
            schema_name=None,
            name="audit_log",
            type=DBTableType.BASE_TABLE,
            columns=[
                DBColumn(name="_id", dtype=DataType.STRING, nullable=False, index=True, indexes=["_id_"], primary_key=True),
                DBColumn(
                    name="actor_id",
                    dtype=DataType.STRING,
                    nullable=False,
                    index=True,
                    indexes=["actor_id_1_timestamp_-1"],
                    primary_key=False,
                ),
                DBColumn(
                    name="timestamp",
                    dtype=DataType.DATETIME,
                    nullable=False,
                    index=True,
                    indexes=["actor_id_1_timestamp_-1"],
                    primary_key=False,
                ),
            ],
        ),
    ]
    return build_database_db_metadata(
        dialect="mongodb",
        database_names=["analytics_archive", "mock_database"],
        tables=tables,
        database_name=engine.url.database,
    )


_MOCK_METADATA_BUILDERS = {
    "postgres": _build_postgres_mock_metadata,
    "mysql": _build_mysql_mock_metadata,
    "clickhouse": _build_clickhouse_mock_metadata,
    "mssql": _build_mssql_mock_metadata,
    "oracle": _build_oracle_mock_metadata,
    "mongodb": _build_mongodb_mock_metadata,
}


def _build_mock_metadata(connection_type: str, engine: sa.Engine) -> DBMetadata:
    metadata = _MOCK_METADATA_BUILDERS[connection_type](engine)
    metadata.connection_string = engine.url.render_as_string(hide_password=True)
    if metadata.database_name is None:
        metadata.database_name = engine.url.database
    return metadata


class GetMockDBConnection(SqlConnectionOutputBaseNode):
    TITLE = "Get Mock DB Connection"
    EMOJI = "🔌"
    CATEGORY = "Mock Data"
    CACHABLE = False
    TAGS = frozenset({"Testing"})

    # --- Inputs ---
    connection_type: Literal[tuple(_MOCK_METADATA_BUILDERS.keys())] = InputField()

    # --- Outputs ---
    connection: sa.Engine = OutputField()

    async def process(self):
        connection_type = _normalize_connection_type(self.connection_type)
        try:
            self.connection = _build_mock_sql_engine(connection_type)
        except KeyError as exc:
            raise ValueError(f"Unsupported mock DB connection type: {self.connection_type}") from exc

    async def infer_metadata(self):
        engine = getattr(self, "connection", None)
        connection_type = _normalize_connection_type(self.connection_type)
        if not isinstance(engine, sa.Engine):
            engine = _build_mock_sql_engine(connection_type)

        return {
            "connection": _build_mock_metadata(connection_type, engine)
        }
