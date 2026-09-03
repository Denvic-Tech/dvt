from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import text

from core.db.write_v4 import WriteColumnMapping
from core.db.write_v4.column_resolution import (
    resolve_existing_table_write_columns,
    resolve_typed_create_write_columns,
)
from core.types import DataFrameMetadata, DBColumn, DataType


def _df_metadata(*columns: DBColumn) -> DataFrameMetadata:
    return DataFrameMetadata(columns=list(columns))


def _column(name: str, dtype: DataType = DataType.INT, nullable: bool = False) -> DBColumn:
    return DBColumn(name=name, dtype=dtype, nullable=nullable, index=False)


def _reflect_table(engine: sa.Engine, table_name: str) -> sa.Table:
    return sa.Table(table_name, sa.MetaData(), autoload_with=engine)


def test_typed_create_resolves_cyrillic_column_to_physical_name() -> None:
    engine = sa.create_engine("sqlite://")

    result = resolve_typed_create_write_columns(
        engine=engine,
        dataframe_metadata=_df_metadata(_column("Код")),
        table_name="products",
    )

    assert [(item.source_name, item.target_name) for item in result.effective_column_mapping] == [
        ("Код", "kod"),
    ]
    assert result.columns[0].requested_target_name == "Код"
    assert result.columns[0].effective_target_name == "kod"
    assert result.columns[0].status == "normalized_target"


def test_typed_create_resolves_transliteration_collisions_like_ddl_builder() -> None:
    engine = sa.create_engine("sqlite://")

    result = resolve_typed_create_write_columns(
        engine=engine,
        dataframe_metadata=_df_metadata(_column("Код"), _column("Код!")),
        table_name="products",
    )

    assert [(item.source_name, item.target_name) for item in result.effective_column_mapping] == [
        ("Код", "kod"),
        ("Код!", "kod_1"),
    ]


def test_existing_table_resolves_cyrillic_source_to_reflected_transliteration() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (kod INTEGER NOT NULL, naimenovanie TEXT)"))

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "products"),
        dataframe_metadata=_df_metadata(
            _column("Код"),
            _column("Наименование", DataType.STRING, True),
        ),
    )

    assert [(item.source_name, item.target_name) for item in result.effective_column_mapping] == [
        ("Код", "kod"),
        ("Наименование", "naimenovanie"),
    ]
    assert [row.status for row in result.columns[:2]] == [
        "auto_transliterated",
        "auto_transliterated",
    ]


def test_existing_table_resolves_exact_uppercase_target_name() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE products ("KOD" INTEGER NOT NULL)'))

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "products"),
        dataframe_metadata=_df_metadata(_column("kod")),
    )

    assert [(item.source_name, item.target_name) for item in result.effective_column_mapping] == [
        ("kod", "KOD"),
    ]
    assert result.columns[0].status == "case_resolved"


def test_write_column_mapping_normalizes_sql_dtype_strings() -> None:
    assert WriteColumnMapping(source_name="a", target_name="a", dtype="Float64").dtype == DataType.FLOAT
    assert WriteColumnMapping(source_name="a", target_name="a", dtype="Int64").dtype == DataType.INT
    assert WriteColumnMapping(source_name="a", target_name="a", dtype="String").dtype == DataType.STRING


def test_existing_table_explicit_mapping_takes_priority_over_auto_transliteration() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE products (kod INTEGER NOT NULL, custom_code INTEGER NOT NULL)")
        )

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "products"),
        dataframe_metadata=_df_metadata(_column("Код")),
        column_mapping=[
            WriteColumnMapping(source_name="Код", target_name="custom_code", dtype=DataType.INT),
        ],
    )

    assert [(item.source_name, item.target_name) for item in result.effective_column_mapping] == [
        ("Код", "custom_code"),
    ]
    assert result.columns[0].status == "explicit_mapping"


def test_existing_table_duplicate_effective_targets_are_diagnosed() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (kod INTEGER NOT NULL)"))

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "products"),
        dataframe_metadata=_df_metadata(_column("Код"), _column("kod")),
    )

    assert result.effective_column_mapping == []
    assert [row.status for row in result.columns[:2]] == [
        "duplicate_effective_target",
        "duplicate_effective_target",
    ]
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "duplicate_effective_targets",
        "missing_columns_ignored",
    ]


def test_existing_table_suggests_add_column_for_dataframe_column_missing_in_db() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (id INTEGER NOT NULL)"))

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "products"),
        dataframe_metadata=_df_metadata(
            _column("id"),
            _column("name", DataType.STRING, True),
        ),
    )

    row = next(row for row in result.columns if row.source_name == "name")

    assert row.status == "missing_in_db"
    assert row.source_dtype == "STRING"
    assert row.db_dtype is None
    assert row.suggested_action is not None
    assert row.suggested_action.type == "add_column"
    assert row.suggested_action.column_name == "name"
    assert row.suggested_action.column is not None
    assert row.suggested_action.column.name == "name"
    assert row.suggested_action.column.dtype == DataType.STRING


def test_existing_table_suggests_drop_column_for_db_column_missing_in_dataframe() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE products (id INTEGER NOT NULL, obsolete TEXT)"))

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "products"),
        dataframe_metadata=_df_metadata(_column("id")),
    )

    row = next(row for row in result.columns if row.db_name == "obsolete")

    assert row.status == "missing_in_dataframe"
    assert row.source_dtype is None
    assert row.db_dtype == "TEXT"
    assert row.suggested_action is not None
    assert row.suggested_action.type == "drop_column"
    assert row.suggested_action.column_name == "obsolete"
    assert row.suggested_action.column is None


def test_existing_table_suggests_recreate_column_for_type_mismatch() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE metrics (score TEXT)"))

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "metrics"),
        dataframe_metadata=_df_metadata(_column("score", DataType.FLOAT, True)),
    )

    row = result.columns[0]

    assert result.effective_column_mapping == []
    assert row.status == "type_mismatch"
    assert row.source_dtype == "FLOAT"
    assert row.db_dtype == "TEXT"
    assert row.suggested_action is not None
    assert row.suggested_action.type == "recreate_column"
    assert row.suggested_action.column_name == "score"
    assert row.suggested_action.column is not None
    assert row.suggested_action.column.name == "score"
    assert row.suggested_action.column.dtype == DataType.FLOAT


def test_existing_table_suggested_action_uses_explicit_mapping_target_name() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE metrics (id INTEGER NOT NULL)"))

    result = resolve_existing_table_write_columns(
        table=_reflect_table(engine, "metrics"),
        dataframe_metadata=_df_metadata(_column("Сумма", DataType.FLOAT, True)),
        column_mapping=[
            WriteColumnMapping(source_name="Сумма", target_name="amount", dtype=DataType.FLOAT),
        ],
    )

    row = next(row for row in result.columns if row.source_name == "Сумма")

    assert row.status == "missing_in_db"
    assert row.suggested_action is not None
    assert row.suggested_action.type == "add_column"
    assert row.suggested_action.column_name == "amount"
    assert row.suggested_action.column is not None
    assert row.suggested_action.column.name == "amount"
