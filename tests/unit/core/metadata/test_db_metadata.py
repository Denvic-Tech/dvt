import warnings
from types import SimpleNamespace

import sqlalchemy as sa

from core.metadata.db_metadata import (
    _rows_to_db_metadata,
    get_sa_type_for_dialect,
    load_db_metadata,
)
from core.metadata.db_metadata.helpers import (
    build_database_db_metadata,
    build_database_schema_db_metadata,
    build_schema_db_metadata,
)
from core.types import DataType, DBTable, DBTableType


def test_get_sa_type_for_dialect_fallback():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        sa_type = get_sa_type_for_dialect("unknown", "strange")

    assert isinstance(sa_type, sa.sql.sqltypes.Text)
    assert any("Unsupported dialect" in str(w.message) for w in captured)


def test_rows_to_db_metadata_maps_fields():
    rows = [
        SimpleNamespace(
            database_name="db",
            table_schema="public",
            table_name="items",
            table_type="BASE TABLE",
            column_name="id",
            data_type="INTEGER",
            is_nullable="NO",
            udt_name=None,
            enum_values=None,
            indexes="idx_items_id [btree]",
            is_primary_key=True,
        ),
        SimpleNamespace(
            database_name="db",
            table_schema="public",
            table_name="items",
            table_type="BASE TABLE",
            column_name="name",
            data_type="TEXT",
            is_nullable="YES",
            udt_name=None,
            enum_values=None,
            indexes=None,
            is_primary_key=False,
        ),
    ]

    metadata = _rows_to_db_metadata(dialect="sqlite", rows=rows, database_name="db")

    assert metadata.database_name == "db"
    assert len(metadata.tables) == 1

    table = metadata.tables[0]
    assert table.name == "items"
    assert table.schema_name == "public"
    assert table.type == DBTableType.BASE_TABLE

    columns = {col.name: col for col in table.columns}
    assert columns["id"].nullable is False
    assert columns["id"].index is True
    assert columns["id"].primary_key is True
    assert columns["name"].nullable is True
    assert columns["name"].dtype in (DataType.STRING, DataType.OBJECT, DataType.UNKNOWN)


def test_load_db_metadata_sqlite(test_db_engine):
    metadata = load_db_metadata(test_db_engine)

    assert metadata.database_name is None
    assert metadata.connection_string == "sqlite://"

    tables = {table.name: table for table in metadata.tables}
    assert {"sample_users", "sample_orders", "sample_events"}.issubset(tables)

    users_columns = {column.name: column for column in tables["sample_users"].columns}
    assert users_columns["id"].primary_key is True
    assert users_columns["email"].nullable is False
    assert users_columns["created_at"].dtype in (DataType.DATETIME, DataType.STRING, DataType.UNKNOWN)

    orders_columns = {column.name: column for column in tables["sample_orders"].columns}
    assert orders_columns["amount"].dtype == DataType.FLOAT
    assert orders_columns["note"].nullable is True


def test_build_schema_db_metadata_preserves_empty_schema():
    metadata = build_schema_db_metadata(
        dialect="postgresql",
        schema_names=["archive", "public"],
        tables=[
            DBTable(
                database_name="analytics",
                schema_name="public",
                name="items",
                columns=[],
                type=DBTableType.BASE_TABLE,
            )
        ],
        database_name="analytics",
    )

    assert metadata.tables == []
    assert [schema.name for schema in metadata.schemas] == ["archive", "public"]
    assert metadata.schemas[0].tables == []
    assert [table.name for table in metadata.schemas[1].tables] == ["items"]


def test_build_database_schema_db_metadata_preserves_empty_schema():
    metadata = build_database_schema_db_metadata(
        dialect="postgresql",
        database_names=["analytics"],
        schema_names_by_database={"analytics": ["archive", "public"]},
        tables=[
            DBTable(
                database_name="analytics",
                schema_name="public",
                name="items",
                columns=[],
                type=DBTableType.BASE_TABLE,
            )
        ],
        database_name="analytics",
    )

    assert metadata.schemas == []
    assert len(metadata.databases) == 1
    assert metadata.databases[0].name == "analytics"
    assert [schema.name for schema in metadata.databases[0].schemas] == ["archive", "public"]
    assert metadata.databases[0].schemas[0].tables == []
    assert [table.name for table in metadata.databases[0].schemas[1].tables] == ["items"]


def test_build_database_db_metadata_preserves_empty_database():
    metadata = build_database_db_metadata(
        dialect="postgresql",
        database_names=["analytics", "warehouse"],
        tables=[
            DBTable(
                database_name="analytics",
                schema_name=None,
                name="items",
                columns=[],
                type=DBTableType.BASE_TABLE,
            )
        ],
        database_name="analytics",
    )

    assert metadata.schemas == []
    assert [database.name for database in metadata.databases] == ["analytics", "warehouse"]
    assert [table.name for table in metadata.databases[0].tables] == ["items"]
    assert metadata.databases[1].tables == []
