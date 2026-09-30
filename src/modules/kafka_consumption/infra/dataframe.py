import codecs
from collections.abc import Sequence

import pandas as pd
import pyarrow as pa

from ..domain.entities import RawMessage
from ..domain.exceptions import KafkaInputError
from .exceptions import KafkaDecodeError


def kafka_arrow_schema(
    *, key_format="binary", value_format="text", timestamp_unit="ns"
) -> pa.Schema:
    if key_format not in {"text", "binary"} or value_format not in {"text", "binary"}:
        raise KafkaInputError("Kafka format must be text or binary")
    if timestamp_unit not in {"s", "ms", "us", "ns"}:
        raise KafkaInputError("Unsupported timestamp precision")
    return pa.schema(
        [
            pa.field("topic", pa.string(), nullable=False),
            pa.field("partition", pa.int32(), nullable=False),
            pa.field("offset", pa.int64(), nullable=False),
            pa.field("timestamp", pa.timestamp(timestamp_unit, tz="UTC")),
            pa.field("timestamp_type", pa.string()),
            pa.field("key", pa.string() if key_format == "text" else pa.binary()),
            pa.field("value", pa.string() if value_format == "text" else pa.binary()),
            pa.field(
                "headers",
                pa.list_(
                    pa.struct(
                        [
                            pa.field("key", pa.string()),
                            pa.field("value", pa.binary()),
                        ]
                    )
                ),
                nullable=False,
            ),
        ]
    )


def messages_to_dataframe(
    messages: Sequence[RawMessage],
    *,
    key_format="binary",
    value_format="text",
    key_encoding="utf-8",
    value_encoding="utf-8",
    timestamp_unit="ns",
) -> pd.DataFrame:
    schema = kafka_arrow_schema(
        key_format=key_format, value_format=value_format, timestamp_unit=timestamp_unit
    )
    for fmt, encoding in ((key_format, key_encoding), (value_format, value_encoding)):
        if fmt == "text":
            try:
                codecs.lookup(encoding)
            except LookupError:
                raise KafkaInputError("Unknown Kafka text encoding") from None

    def decode(value, fmt, encoding, message):
        if value is None or fmt == "binary":
            return value
        try:
            return value.decode(encoding, errors="strict")
        except (UnicodeError, LookupError):
            tp = message.topic_partition
            raise KafkaDecodeError(
                f"Kafka decode failed: {tp.topic}/{tp.partition}/{message.offset}"
            ) from None

    rows = [
        {
            "topic": m.topic_partition.topic,
            "partition": m.topic_partition.partition,
            "offset": m.offset,
            "timestamp": (
                pd.Timestamp(m.timestamp_ms, unit="ms", tz="UTC")
                if m.timestamp_ms is not None
                else None
            ),
            "timestamp_type": m.timestamp_type,
            "key": decode(m.key, key_format, key_encoding, m),
            "value": decode(m.value, value_format, value_encoding, m),
            "headers": [{"key": key, "value": value} for key, value in m.headers],
        }
        for m in messages
    ]
    return pa.Table.from_pylist(rows, schema=schema).to_pandas(types_mapper=pd.ArrowDtype)


def kafka_dataframe_metadata(**formats):
    from core.metadata.df_metadata import get_df_metadata

    metadata = get_df_metadata(messages_to_dataframe((), **formats))
    nonnullable = {"topic", "partition", "offset", "headers"}
    return metadata.model_copy(
        update={
            "columns": [
                column.model_copy(update={"nullable": column.name not in nonnullable})
                for column in metadata.columns
            ],
        }
    )
