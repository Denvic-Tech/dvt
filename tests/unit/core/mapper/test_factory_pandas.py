import pandas as pd
import sqlalchemy as sa
import pytest
from sqlalchemy.orm import DeclarativeBase

from core.mapper.factory._pandas import build_table_from_df, build_mapper_from_df


class Base(DeclarativeBase):
    pass


def test_build_table_from_df_transliterates_and_preserves_ascii(test_db_engine):
    df = pd.DataFrame({"Name": ["Alice"], "Код": [1]})

    metadata = sa.MetaData()
    table = build_table_from_df(
        df=df,
        table_name="products",
        dialect=test_db_engine.dialect,
        metadata=metadata,
        primary_key_cols=None,
    )

    rename_map = getattr(table, "rename_map", {})

    assert rename_map["Name"] == "Name"
    assert rename_map["Код"] != "Код"
    assert rename_map["Код"].islower()
    assert rename_map["Код"] in table.c


def test_build_table_from_df_resets_named_index(test_db_engine):
    df = pd.DataFrame({"value": [10, 20, 30]})
    df.index.name = "idx"

    metadata = sa.MetaData()
    table = build_table_from_df(
        df=df,
        table_name="indexed",
        dialect=test_db_engine.dialect,
        metadata=metadata,
        primary_key_cols=None,
    )

    assert "idx" in table.c


def test_build_table_from_df_adds_surrogate_pk_when_missing(test_db_engine):
    df = pd.DataFrame({"name": ["Alice", "Bob"]})

    metadata = sa.MetaData()
    table = build_table_from_df(
        df=df,
        table_name="people",
        dialect=test_db_engine.dialect,
        metadata=metadata,
        primary_key_cols=None,
        add_surrogate_pk_if_missing=True,
        surrogate_pk_name="id",
    )

    assert "id" in table.c
    assert list(table.primary_key.columns)[0].name == "id"


def test_build_table_from_df_raises_on_nullable_pk(test_db_engine):
    df = pd.DataFrame({"id": [1, None], "name": ["Alice", "Bob"]})

    metadata = sa.MetaData()
    with pytest.raises(ValueError):
        build_table_from_df(
            df=df,
            table_name="people",
            dialect=test_db_engine.dialect,
            metadata=metadata,
            primary_key_cols="id",
        )


def test_build_mapper_from_df_creates_mapper_and_to_dict(test_db_engine):
    df = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})

    metadata = sa.MetaData()
    mapped_cls = build_mapper_from_df(
        df=df,
        Base=Base,
        table_name="people",
        dialect=test_db_engine.dialect,
        metadata=metadata,
        primary_key_cols="id",
    )

    instance = mapped_cls()
    instance.id = 10
    instance.name = "Eve"

    assert hasattr(mapped_cls, "__table__")
    assert instance.to_dict() == {"id": 10, "name": "Eve"}
