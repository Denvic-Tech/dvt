import json

import pandas as pd
import pyarrow as pa
import pytest

from core.metadata import get_df_metadata

from services.gateway.routes.project.data.preview import dataframe_preview_values

from src.modules.kafka_consumption.domain.entities import RawMessage
from src.modules.kafka_consumption.domain.value_objects import TopicPartition
from src.modules.kafka_consumption.infra.dataframe import messages_to_dataframe


@pytest.mark.parametrize("empty", [False, True])
def test_kafka_preview_preserves_schema_and_data_without_decoding_binary(empty):
    messages = () if empty else (
        RawMessage(TopicPartition("orders", 0), 0, None, None, b"\xff", None,
                   (("same", b"\xfe"), ("same", None), ("empty", b""))),
    )
    frame = messages_to_dataframe(messages)
    original = frame.copy(deep=True)
    metadata = get_df_metadata(frame)
    values = dataframe_preview_values(frame)
    json.dumps(values)
    pd.testing.assert_frame_equal(frame, original)
    assert get_df_metadata(frame) == metadata
    if empty:
        assert values == []
    else:
        row = dict(zip(frame.columns, values[0], strict=True))
        assert row["key"] == "<binary: 1 bytes>"
        assert row["value"] is None
        assert row["headers"] == [
            {"key": "same", "value": "<binary: 1 bytes>"},
            {"key": "same", "value": None},
            {"key": "empty", "value": "<binary: 0 bytes>"},
        ]


def test_preview_keeps_scalar_and_nested_values():
    frame = pd.DataFrame({
        "value": pd.Series([b"\xff", b"", None], dtype=pd.ArrowDtype(pa.binary())),
        "nested": pd.Series([{"x": [b"a"]}, {"x": []}, None],
                            dtype=pd.ArrowDtype(pa.struct([("x", pa.list_(pa.binary()))]))),
        "time": pd.to_datetime(["2026-09-30T00:00:00Z", None, None]),
        "number": [1, 2, 3],
        "text": ["value", "", None],
    })
    original = frame.copy(deep=True)
    values = dataframe_preview_values(frame)
    assert values[0] == ["<binary: 1 bytes>", {"x": ["<binary: 1 bytes>"]},
                         "2026-09-30T00:00:00.000Z", 1, "value"]
    assert values[1][:2] == ["<binary: 0 bytes>", {"x": []}]
    assert values[2][:2] == [None, None]
    pd.testing.assert_frame_equal(frame, original)
