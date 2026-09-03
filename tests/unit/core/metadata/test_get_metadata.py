import importlib

import pandas as pd
import dask.dataframe as dd

metadata_module = importlib.import_module("core.metadata.get_metadata")

from core.metadata.get_metadata import get_metadata
from core.types import DataFrameMetadata, JSONMetadata, JSONNodeKind
from core.types.metadata import SeriesMetadata


def test_get_metadata_returns_df_metadata():
    df = pd.DataFrame({"a": [1, 2, 3]})

    meta = get_metadata(df)

    assert isinstance(meta, DataFrameMetadata)


def test_get_metadata_returns_dask_df_metadata():
    pdf = pd.DataFrame({"a": [1, 2, 3]})
    ddf = dd.from_pandas(pdf, npartitions=2)

    meta = get_metadata(ddf)

    assert isinstance(meta, DataFrameMetadata)


def test_get_metadata_returns_series_metadata():
    series = pd.Series([1, 2], name="s")

    meta = get_metadata(series)

    assert isinstance(meta, SeriesMetadata)


def test_get_metadata_returns_json_metadata_for_dict() -> None:
    payload = {"items": [{"id": 1}, {"id": 2}]}

    meta = get_metadata(payload)

    assert isinstance(meta, JSONMetadata)
    assert meta.root is not None
    assert meta.root.kind == JSONNodeKind.OBJECT
    assert any(candidate.display_path == "$.items" for candidate in meta.flatten_candidates)


def test_get_metadata_dispatches_engine_and_kafka(monkeypatch, test_db_engine):
    sentinel_db = object()
    sentinel_kafka = object()

    def fake_db_metadata(engine, fernet_key=None):
        assert engine is test_db_engine
        return sentinel_db

    def fake_kafka_metadata(producer):
        return sentinel_kafka

    class FakeKafkaProducer:
        pass

    monkeypatch.setattr(metadata_module, "load_db_metadata", fake_db_metadata)
    monkeypatch.setattr(metadata_module, "load_kafka_metadata", fake_kafka_metadata)
    monkeypatch.setattr(metadata_module, "KafkaProducer", FakeKafkaProducer)

    assert get_metadata(test_db_engine) is sentinel_db
    assert get_metadata(FakeKafkaProducer()) is sentinel_kafka


def test_get_metadata_returns_none_for_unknown():
    class Unknown:
        pass

    assert get_metadata(Unknown()) is None
