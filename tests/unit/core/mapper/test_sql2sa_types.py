import sqlalchemy as sa
from sqlalchemy.sql import sqltypes
import pytest

from core.mapper.sql2sa_types import (
    get_ch_sa_type,
    get_ischema_names,
    get_sqlite_sa_type,
    get_mysql_sa_type,
    get_pg_sa_type,
)


def test_get_ischema_names_sqlite(test_db_engine):
    names = get_ischema_names(test_db_engine.dialect)
    assert isinstance(names, dict)
    assert "INTEGER" in names


def test_get_ischema_names_unsupported():
    class DummyDialect:
        name = "unknown"

    with pytest.raises(ValueError):
        get_ischema_names(DummyDialect())


def test_get_sqlite_sa_type_returns_type():
    sa_type = get_sqlite_sa_type("VARCHAR")
    assert isinstance(sa_type, sqltypes.TypeEngine)


def test_get_mysql_sa_type_enum():
    sa_type = get_mysql_sa_type("enum", enum_values="a,b")
    assert isinstance(sa_type, sqltypes.Enum)


def test_get_mysql_sa_type_invalid():
    with pytest.raises(ValueError):
        get_mysql_sa_type("not_a_type")


def test_get_pg_sa_type_user_defined_enum():
    sa_type = get_pg_sa_type("USER-DEFINED", enum_values="a,b")
    assert isinstance(sa_type, sqltypes.Enum)


@pytest.mark.parametrize(
    ("sql_type", "expected_type_name"),
    [
        ("Int32", "Int32"),
        ("Nullable(Int32)", "Int32"),
        ("Array(String)", "Array"),
        ("DateTime64(3, 'UTC')", "DateTime64"),
        ("LowCardinality(String)", "String"),
        ("Enum8('a' = 1, 'b' = 2)", "Enum8"),
    ],
)
def test_get_ch_sa_type_normalizes_clickhouse_dialect_results(sql_type, expected_type_name):
    sa_type = get_ch_sa_type(sql_type)

    assert isinstance(sa_type, sqltypes.TypeEngine)
    assert type(sa_type).__name__ == expected_type_name
