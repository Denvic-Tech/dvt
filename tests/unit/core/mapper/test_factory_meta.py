import sqlalchemy as sa
import pandas as pd
import pytest

from core.mapper.factory._meta import build_meta_from_schema


def test_build_meta_from_schema_sqlite(test_db_engine):
    metadata = sa.MetaData()
    table = sa.Table(
        "mapper_meta_test",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("created_at", sa.DateTime),
        sa.Column("value", sa.Float),
    )
    metadata.create_all(test_db_engine, checkfirst=True)

    meta_df, dtype_map, tz_cols, naive_dt_cols = build_meta_from_schema(
        engine=test_db_engine,
        table_name="mapper_meta_test",
        schema=None,
        index_col="id",
    )

    assert isinstance(meta_df, pd.DataFrame)
    assert meta_df.index.name == "id"
    assert "name" in dtype_map
    assert "created_at" in naive_dt_cols
    assert tz_cols == []


def test_build_meta_from_schema_requires_table_for_non_clickhouse(test_db_engine):
    with pytest.raises(ValueError):
        build_meta_from_schema(
            engine=test_db_engine,
            table_name=None,
            schema=None,
            index_col="id",
        )
