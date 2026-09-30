import json
from unittest.mock import MagicMock

import pandas as pd
import pyarrow as pa
import pytest

from core.metadata.df_metadata import get_df_metadata
from core.types import DataFrameMetadata, DataType
from core.types.arrow_type import arrow_type_from_metadata, arrow_type_to_metadata
from core.utils.dtype_coercion import apply_dtypes_and_casts

from src.modules.kafka_consumption import RawMessage, ReadLimits, TopicPartition
from src.modules.kafka_consumption.domain.exceptions import KafkaInputError, KafkaPositionError
from src.modules.kafka_consumption.domain.policies import monotonic_commit, select_start_position
from src.modules.kafka_consumption.infra.dataframe import (
    kafka_dataframe_metadata,
    messages_to_dataframe,
)
from src.modules.kafka_consumption.infra.exceptions import KafkaDecodeError
from src.modules.kafka_consumption.infra.gateways.kafka_python import KafkaPythonGateway
from src.modules.kafka_consumption.infra.mappers import offsets_from_json, offsets_to_json
from src.node_dsl.base_node.df_output import DFOutputBaseNode


@pytest.mark.parametrize("value", [-1, 0, True, 1.5, "2"])
def test_invalid_limits(value):
    with pytest.raises(KafkaInputError):
        ReadLimits(max_messages=value)


@pytest.mark.parametrize(
    "requested,current,status",
    [
        (4, None, "committed"),
        (4, 2, "committed"),
        (4, 4, "unchanged"),
        (4, 7, "already_ahead"),
    ],
)
def test_monotonic_commit(requested, current, status):
    result = monotonic_commit(0, requested, current, 10)
    assert result.status == status
    assert result.resulting == max(requested, current or 0)


def test_invalid_commit_and_old_position():
    with pytest.raises(KafkaPositionError):
        monotonic_commit(0, 11, None, 10)
    with pytest.raises(KafkaPositionError):
        select_start_position(mode="committed", beginning=3, end=10, committed=2)
    assert select_start_position(mode="committed", beginning=3, end=10) == 3
    assert select_start_position(mode="latest", beginning=3, end=10) == 10
    assert select_start_position(mode="timestamp", beginning=3, end=10) == 10
    assert select_start_position(mode="explicit", beginning=3, end=10, explicit_position=8) == 8


def test_json_survives_process_boundary_and_gaps():
    payload = {
        "schema_version": 1,
        "topic": "orders",
        "group_id": "g",
        "partitions": [
            {
                "partition": 0,
                "next_offset": 101,
                "start_offset": 2,
                "last_message_offset": 100,
                "message_count": 3,
            }
        ],
    }
    summary = offsets_from_json(json.dumps(payload))
    assert summary.partitions[0].message_count == 3
    assert offsets_from_json(json.dumps(offsets_to_json(summary))) == summary
    assert offsets_from_json({**payload, "partitions": []}).partitions == ()


@pytest.mark.parametrize("offset", [True, -1, 1.2, "10"])
def test_json_rejects_non_positions(offset):
    with pytest.raises((ValueError, KafkaInputError)):
        offsets_from_json(
            {
                "schema_version": 1,
                "topic": "t",
                "group_id": "g",
                "partitions": [{"partition": 0, "next_offset": offset}],
            }
        )


def test_json_rejects_duplicates_and_version():
    payload = {
        "schema_version": 1,
        "topic": "t",
        "group_id": "g",
        "partitions": [{"partition": 0, "next_offset": 0}] * 2,
    }
    with pytest.raises(ValueError):
        offsets_from_json(payload)
    with pytest.raises(ValueError):
        offsets_from_json({**payload, "schema_version": 2, "partitions": []})


@pytest.mark.parametrize(
    "key_format,value_format",
    [
        ("binary", "binary"),
        ("binary", "text"),
        ("text", "binary"),
        ("text", "text"),
    ],
)
def test_arrow_empty_full_metadata_round_trip(key_format, value_format):
    message = RawMessage(
        TopicPartition("t", 0),
        2,
        None,
        None,
        b"",
        None,
        (("repeat", b"\x00\xff"), ("repeat", None)),
    )
    formats = {"key_format": key_format, "value_format": value_format, "timestamp_unit": "us"}
    full = messages_to_dataframe([message], **formats)
    empty = messages_to_dataframe([], **formats)
    metadata = DataFrameMetadata.model_validate_json(get_df_metadata(full).model_dump_json())
    restored = DFOutputBaseNode.build_empty_pdf_from_metadata(metadata)
    assert full.dtypes.to_dict() == empty.dtypes.to_dict() == restored.dtypes.to_dict()
    assert all(isinstance(t, pd.ArrowDtype) for t in full.dtypes)
    assert all(c.dtype not in {DataType.UNKNOWN, DataType.OBJECT} for c in metadata.columns)
    assert full.headers.iloc[0] == [
        {"key": "repeat", "value": b"\x00\xff"},
        {"key": "repeat", "value": None},
    ]
    assert pd.isna(full.value.iloc[0])
    assert full.timestamp.isna().all()
    assert not kafka_dataframe_metadata(**formats).columns[0].nullable


def test_invalid_decode_has_no_payload():
    message = RawMessage(TopicPartition("t", 0), 2, None, None, None, b"secret\xff")
    with pytest.raises(KafkaDecodeError) as error:
        messages_to_dataframe([message])
    assert "secret" not in str(error.value)


def test_nested_arrow_and_unsupported_cast():
    dtype = pa.struct([pa.field("nested", pa.list_(pa.binary()), nullable=False)])
    assert arrow_type_from_metadata(arrow_type_to_metadata(dtype)) == dtype
    frame = pd.DataFrame({"data": pd.Series([b"\xff"], dtype=pd.ArrowDtype(pa.binary()))})
    with pytest.raises(TypeError, match="Unsupported"):
        apply_dtypes_and_casts(frame, {"data": "string"}, [], [])


def test_client_closed_on_error_and_cancel(monkeypatch):
    consumer = MagicMock()
    monkeypatch.setattr(
        "src.modules.kafka_consumption.infra.gateways.kafka_python.KafkaConsumer",
        lambda **kwargs: consumer,
    )
    gateway = KafkaPythonGateway({})
    with pytest.raises(RuntimeError), gateway._consumer():
        raise RuntimeError("cancelled")
    consumer.close.assert_called_once_with(autocommit=False, timeout_ms=30000)
