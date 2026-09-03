from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa

from core.db.ddl import (
    build_db_columns_from_df_metadata,
    build_engine_from_connection_string,
    ensure_schema_exists,
    extract_create_table_column_names,
    extract_create_table_table_and_schema,
    extract_create_table_table_name,
    get_primary_key_cols,
    get_sqlglot_dialect,
)
from core.types import Column, DataFrameMetadata, DBColumn, DBMetadata, DataType


def test_get_sqlglot_dialect_maps_mssql_to_tsql() -> None:
    assert get_sqlglot_dialect("mssql") == "tsql"


def test_get_sqlglot_dialect_maps_sqlserver_to_tsql() -> None:
    assert get_sqlglot_dialect("sqlserver") == "tsql"


def test_get_sqlglot_dialect_maps_postgresql_to_postgres() -> None:
    assert get_sqlglot_dialect("postgresql") == "postgres"


def test_extract_create_table_table_name_parses_mssql_sql() -> None:
    sql = """
    CREATE TABLE dbo.stg_users (
        id INT PRIMARY KEY,
        name NVARCHAR(100)
    )
    """
    assert extract_create_table_table_name(sql, sa_dialect_name="mssql") == "stg_users"


def test_extract_create_table_table_and_schema_parses_mssql_sql() -> None:
    sql = "CREATE TABLE dbo.stg_users (id INT PRIMARY KEY, name NVARCHAR(100))"
    table_name, schema_name = extract_create_table_table_and_schema(sql, sa_dialect_name="mssql")
    assert table_name == "stg_users"
    assert schema_name == "dbo"


def test_extract_create_table_column_names_preserves_order() -> None:
    sql = "CREATE TABLE dbo.stg_users (id INT, name NVARCHAR(100), created_at DATETIME)"
    assert extract_create_table_column_names(sql, sa_dialect_name="mssql") == [
        "id",
        "name",
        "created_at",
    ]


def test_get_primary_key_cols_prefers_explicit_string() -> None:
    columns = [DBColumn(name="id", dtype=DataType.INT, index=True)]
    assert get_primary_key_cols(index_col="id", columns=columns) == "id"


def test_get_primary_key_cols_prefers_explicit_list() -> None:
    columns = [DBColumn(name="id", dtype=DataType.INT, index=True)]
    assert get_primary_key_cols(index_col=["id", "tenant_id"], columns=columns) == ["id", "tenant_id"]


def test_get_primary_key_cols_infers_from_index_flags() -> None:
    columns = [
        DBColumn(name="id", dtype=DataType.INT, index=True),
        DBColumn(name="tenant_id", dtype=DataType.INT, index=True),
        DBColumn(name="name", dtype=DataType.STRING, index=False),
    ]
    assert get_primary_key_cols(index_col=None, columns=columns) == ["id", "tenant_id"]


def test_build_db_columns_from_df_metadata() -> None:
    metadata = DataFrameMetadata(
        columns=[
            Column(name="id", dtype=DataType.INT, nullable=False, index=True),
            Column(name="name", dtype=DataType.STRING, nullable=True, index=False),
        ]
    )

    db_columns = build_db_columns_from_df_metadata(metadata)

    assert [c.name for c in db_columns] == ["id", "name"]
    assert db_columns[0].dtype == DataType.INT
    assert db_columns[0].index is True
    assert db_columns[1].dtype == DataType.STRING


def test_build_engine_from_connection_string_overrides_clickhouse_http_timeout() -> None:
    engine = build_engine_from_connection_string(
        connection_string=(
            "clickhouse+http://user:pass@clickhouse.example:8443/DVT_Test"
            "?protocol=https&timeout=300&verify=False"
        ),
        connect_timeout_sec=10,
    )

    assert engine.url.query["timeout"] == "10"
    assert engine.url.query["protocol"] == "https"
    assert engine.url.query["verify"] == "False"


def test_build_engine_from_connection_string_preserves_clickhouse_timeout_by_default() -> None:
    engine = build_engine_from_connection_string(
        connection_string=(
            "clickhouse+http://user:pass@clickhouse.example:8443/DVT_Test"
            "?protocol=https&timeout=300&verify=False"
        ),
    )

    assert engine.url.query["timeout"] == "300"


def test_build_engine_and_ensure_schema_exists_sqlite_noop() -> None:
    db_name = f"ddl_utils_{uuid4().hex}"
    connection_string = f"sqlite:///file:{db_name}?mode=memory&cache=shared&uri=true"
    engine = build_engine_from_connection_string(connection_string=connection_string)
    keeper_conn = engine.connect()

    try:
        ensure_schema_exists(engine=engine, schema_name="analytics")

        # No exception and engine is usable.
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE t1 (id INTEGER PRIMARY KEY)"))

        assert sa.inspect(engine).has_table("t1") is True
    finally:
        keeper_conn.close()
