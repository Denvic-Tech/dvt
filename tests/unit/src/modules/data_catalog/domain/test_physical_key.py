import pytest

from src.modules.data_catalog.domain import ConnectionLocator, RawLocator
from src.modules.data_catalog.domain.policies import (
    build_physical_key,
    canonical_dialect,
    normalize_locator,
)


def _connection(dialect: str, *, database: str | None = "main", port: int | None = 5432) -> ConnectionLocator:
    return ConnectionLocator(
        id="conn", dialect=dialect, host="DB.Local", port=port, database=database, revision="r1"
    )


@pytest.mark.parametrize(
    "connection_type,expected",
    [("postgres", "postgresql"), ("mariadb", "mysql"), ("sqlserver", "mssql"), ("oracle", "oracle"), ("unknown", None)],
)
def test_canonical_dialect(connection_type, expected):
    assert canonical_dialect(connection_type) == expected


def test_postgres_defaults_schema_to_public_and_database_to_connection():
    locator = normalize_locator(RawLocator(table="Orders"), _connection("postgres"), dialect="postgresql")
    assert (locator.database, locator.schema, locator.table) == ("main", "public", "Orders")
    assert build_physical_key(locator) == "postgresql://db.local:5432/main/public/orders"


def test_schema_qualified_table_name_is_split():
    locator = normalize_locator(
        RawLocator(table='"stage"."Orders"'), _connection("postgres"), dialect="postgresql"
    )
    assert (locator.schema, locator.table) == ("stage", "Orders")


def test_mssql_defaults_schema_to_dbo_and_named_instance_has_no_port():
    connection = ConnectionLocator(
        id="c", dialect="mssql", host="srv\\INST", port=None, database="db", revision="r"
    )
    locator = normalize_locator(RawLocator(table="t"), connection, dialect="mssql")
    assert locator.schema == "dbo"
    assert build_physical_key(locator) == "mssql://srv\\inst:/db/dbo/t"


def test_dialects_without_schemas_drop_schema_and_clickhouse_maps_schema_to_database():
    mysql = normalize_locator(RawLocator(table="t", schema="ignored"), _connection("mysql"), dialect="mysql")
    assert mysql.schema is None and mysql.database == "main"

    clickhouse = normalize_locator(
        RawLocator(table="t", schema="analytics"), _connection("clickhouse", port=8123), dialect="clickhouse"
    )
    assert (clickhouse.database, clickhouse.schema) == ("analytics", None)
    assert build_physical_key(clickhouse) == "clickhouse://db.local:8123/analytics//t"


def test_explicit_node_values_win_over_connection_defaults():
    locator = normalize_locator(
        RawLocator(table="t", schema="s", database="other"), _connection("postgres"), dialect="postgresql"
    )
    assert (locator.database, locator.schema) == ("other", "s")
