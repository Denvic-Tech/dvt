import pytest

from src.modules.data_catalog.domain import ConnectionLocator, RawLocator
from src.modules.data_catalog.domain.policies import (
    DbConnectionCoordinates,
    DbTableLocator,
    build_physical_key,
    canonical_dialect,
    db_connection_coordinates,
    describe_db_table,
    normalize_locator,
)


def _coordinates(*, database: str | None = "main", port: int | None = 5432) -> DbConnectionCoordinates:
    return DbConnectionCoordinates(host="DB.Local", port=port, database=database)


@pytest.mark.parametrize(
    "connection_type,expected",
    [("postgres", "postgresql"), ("mariadb", "mysql"), ("sqlserver", "mssql"), ("oracle", "oracle"), ("unknown", None)],
)
def test_canonical_dialect(connection_type, expected):
    assert canonical_dialect(connection_type) == expected


def test_postgres_defaults_schema_to_public_and_database_to_connection():
    locator = normalize_locator(RawLocator(table="Orders"), _coordinates(), dialect="postgresql")
    assert (locator.database, locator.schema, locator.table) == ("main", "public", "Orders")
    assert build_physical_key(locator) == "postgresql://db.local:5432/main/public/orders"
    assert describe_db_table(locator) == "main.public.Orders @ DB.Local:5432"


def test_schema_qualified_table_name_is_split():
    locator = normalize_locator(RawLocator(table='"stage"."Orders"'), _coordinates(), dialect="postgresql")
    assert (locator.schema, locator.table) == ("stage", "Orders")


def test_mssql_defaults_schema_to_dbo_and_named_instance_has_no_port():
    connection = ConnectionLocator(
        id="c", type="mssql", revision="r", properties={"host": "srv", "instance_name": "INST", "database": "db"}
    )
    coordinates = db_connection_coordinates(connection)
    assert coordinates == DbConnectionCoordinates(host="srv\\INST", port=None, database="db")

    locator = normalize_locator(RawLocator(table="t"), coordinates, dialect="mssql")
    assert locator.schema == "dbo"
    assert build_physical_key(locator) == "mssql://srv\\inst:/db/dbo/t"
    assert describe_db_table(locator) == "db.dbo.t @ srv\\INST"


def test_dialects_without_schemas_drop_schema_and_clickhouse_maps_schema_to_database():
    mysql = normalize_locator(RawLocator(table="t", schema="ignored"), _coordinates(), dialect="mysql")
    assert mysql.schema is None and mysql.database == "main"

    clickhouse = normalize_locator(
        RawLocator(table="t", schema="analytics"), _coordinates(port=8123), dialect="clickhouse"
    )
    assert (clickhouse.database, clickhouse.schema) == ("analytics", None)
    assert build_physical_key(clickhouse) == "clickhouse://db.local:8123/analytics//t"


def test_explicit_node_values_win_over_connection_defaults():
    locator = normalize_locator(
        RawLocator(table="t", schema="s", database="other"), _coordinates(), dialect="postgresql"
    )
    assert (locator.database, locator.schema) == ("other", "s")


def test_typed_locator_roundtrips_through_universal_locator():
    typed = DbTableLocator("postgresql", "db", 5432, "main", "public", "Orders")
    universal = typed.to_locator()

    assert universal.kind == "db_table"
    assert universal.parts["port"] == 5432
    assert DbTableLocator.from_locator(universal) == typed


def test_connection_properties_with_string_port_and_missing_host_are_tolerated():
    connection = ConnectionLocator(id="c", type="postgres", revision="r", properties={"port": "5433"})
    assert db_connection_coordinates(connection) == DbConnectionCoordinates(host="", port=5433, database=None)
