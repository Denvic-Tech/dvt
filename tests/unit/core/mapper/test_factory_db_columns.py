import sqlalchemy as sa
import pytest
from sqlalchemy.dialects import oracle, postgresql

from core.mapper.factory._db_columns import build_table_from_db_columns
from core.types import DBColumn, DataType


def test_build_table_from_db_columns_does_not_use_primary_key_flags_when_primary_key_cols_missing(test_db_engine):
    columns = [
        DBColumn(name="id", dtype=DataType.INT, nullable=False, primary_key=True),
        DBColumn(name="Имя", dtype=DataType.STRING, nullable=False),
    ]

    metadata = sa.MetaData()
    table = build_table_from_db_columns(
        table_name="people",
        columns=columns,
        dialect=test_db_engine.dialect,
        metadata=metadata,
    )

    assert list(table.primary_key.columns) == []
    rename_map = getattr(table, "rename_map", {})
    assert rename_map["Имя"] != "Имя"
    assert rename_map["Имя"].islower()


def test_build_table_from_db_columns_preserves_ascii_case_in_column_names_and_ddl(test_db_engine):
    columns = [
        DBColumn(name="Period", dtype=DataType.STRING, nullable=False),
    ]

    metadata = sa.MetaData()
    table = build_table_from_db_columns(
        table_name="people",
        columns=columns,
        dialect=test_db_engine.dialect,
        metadata=metadata,
    )

    assert "Period" in table.c
    assert table.c["Period"].name == "Period"
    assert table.c["Period"].name.quote is True

    rename_map = getattr(table, "rename_map", {})
    assert rename_map["Period"] == "Period"

    ddl_pg = str(sa.schema.CreateTable(table).compile(dialect=postgresql.dialect()))
    ddl_oracle = str(sa.schema.CreateTable(table).compile(dialect=oracle.dialect()))

    assert '"Period"' in ddl_pg
    assert '"Period"' in ddl_oracle
    assert '"Period" VARCHAR2' in ddl_oracle


def test_build_table_from_db_columns_uses_explicit_primary_key_cols(test_db_engine):
    columns = [
        DBColumn(name="id", dtype=DataType.INT, nullable=False, primary_key=False),
        DBColumn(name="name", dtype=DataType.STRING, nullable=False),
    ]

    metadata = sa.MetaData()
    table = build_table_from_db_columns(
        table_name="people",
        columns=columns,
        dialect=test_db_engine.dialect,
        metadata=metadata,
        primary_key_cols="id",
    )

    assert [column.name for column in table.primary_key.columns] == ["id"]


def test_build_table_from_db_columns_adds_surrogate_pk(test_db_engine):
    columns = [
        DBColumn(name="name", dtype=DataType.STRING, nullable=False),
    ]

    metadata = sa.MetaData()
    table = build_table_from_db_columns(
        table_name="people",
        columns=columns,
        dialect=test_db_engine.dialect,
        metadata=metadata,
        add_surrogate_pk_if_missing=True,
        surrogate_pk_name="id",
    )

    assert "id" in table.c
    assert list(table.primary_key.columns)[0].name == "id"


def test_build_table_from_db_columns_raises_on_nullable_pk_when_primary_key_cols_explicit(test_db_engine):
    columns = [
        DBColumn(name="id", dtype=DataType.INT, nullable=True, primary_key=True),
        DBColumn(name="name", dtype=DataType.STRING, nullable=False),
    ]

    metadata = sa.MetaData()
    with pytest.raises(ValueError):
        build_table_from_db_columns(
            table_name="people",
            columns=columns,
            dialect=test_db_engine.dialect,
            metadata=metadata,
            primary_key_cols="id",
        )
