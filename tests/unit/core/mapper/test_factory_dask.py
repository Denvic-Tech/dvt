import dask.dataframe as dd
import pandas as pd

from core.mapper.factory_dask import compute_dask_df_stats, get_sqla_type, build_mapper_from_dask_df
from core.mapper import type_decorators as td
import sqlalchemy as sa


def test_compute_dask_df_stats_collects_minimal_info(test_db_engine):
    pdf = pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["a", None, "c"],
        "payload": pd.Series([b"a", None, b"c"], dtype=object),
        "amount": [10, 20, 30],
    })
    ddf = dd.from_pandas(pdf, npartitions=2)

    stats = compute_dask_df_stats(ddf, test_db_engine.dialect)

    assert bool(stats["id"]["has_nulls"]) is False
    assert "min" in stats["amount"]
    assert "max" in stats["amount"]
    assert "sample" not in stats["payload"]
    assert "max_len" not in stats["name"]


def test_get_sqla_type_for_dask_stats(test_db_engine):
    pdf = pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["a", "b", "c"],
    })
    ddf = dd.from_pandas(pdf, npartitions=1)

    stats = compute_dask_df_stats(ddf, test_db_engine.dialect)

    name_type = get_sqla_type("name", stats["name"], test_db_engine.dialect)
    id_type = get_sqla_type("id", stats["id"], test_db_engine.dialect)

    assert isinstance(name_type, td.StringyType)
    assert id_type in (sa.Integer, sa.BigInteger)

    object_stats = {
        "dtype": object,
        "has_nulls": False,
        "sample": pd.Series(["value"]),
    }
    obj_type = get_sqla_type("payload", object_stats, test_db_engine.dialect)
    assert isinstance(obj_type, td.StringyType)


def test_build_mapper_from_dask_df(test_db_engine):
    pdf = pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]})
    ddf = dd.from_pandas(pdf, npartitions=2)

    base, mapped_cls = build_mapper_from_dask_df(
        df=ddf,
        table_name="people",
        engine=test_db_engine,
        primary_key_cols="id",
    )

    instance = mapped_cls()
    instance.id = 1
    instance.name = "Alice"

    assert hasattr(mapped_cls, "__table__")
    assert instance.to_dict() == {"id": 1, "name": "Alice"}
