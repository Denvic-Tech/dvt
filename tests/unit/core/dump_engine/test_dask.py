import pickle

import dask.dataframe as dd
import pandas as pd
import pandas.testing as tm
import pytest

from core.dump_engine._dask import DaskMetaCacheEngine
from core.dump_engine.utils import pick_engine_for


def test_can_handle_dask_dataframe(simple_ddf):
    engine = DaskMetaCacheEngine()

    assert engine.can_handle(simple_ddf) is True
    assert engine.can_handle(pd.DataFrame({"a": [1, 2, 3]})) is False


def test_dump_meta_only_payload(simple_ddf):
    engine = DaskMetaCacheEngine()

    data, meta = engine.dump(simple_ddf)

    assert isinstance(data, (bytes, bytearray))
    assert meta is not None
    assert meta.get("meta_only") is True
    assert meta.get("npartitions") == simple_ddf.npartitions

    meta_frame = pickle.loads(data)
    tm.assert_frame_equal(meta_frame, simple_ddf._meta)


def test_load_preserves_schema_and_partitions(simple_ddf):
    engine = DaskMetaCacheEngine()

    data, meta = engine.dump(simple_ddf)
    restored = engine.load(data, meta=meta)

    assert isinstance(restored, dd.DataFrame)
    assert restored.npartitions == simple_ddf.npartitions
    tm.assert_frame_equal(restored._meta, simple_ddf._meta)
    assert restored.compute().empty


def test_load_invalid_partitions_defaults_to_one(simple_ddf):
    engine = DaskMetaCacheEngine()

    data, _ = engine.dump(simple_ddf)

    for bad_meta in (
        {"npartitions": "oops"},
        {"npartitions": 0},
        {"npartitions": -3},
        {"npartitions": None},
    ):
        restored = engine.load(data, meta=bad_meta)
        assert restored.npartitions == 1


def test_pick_engine_for_dask_meta_mode(simple_ddf):
    engine = pick_engine_for(simple_ddf, mode="meta")
    assert isinstance(engine, DaskMetaCacheEngine)

    with pytest.raises(ValueError):
        pick_engine_for(simple_ddf, mode="full")
