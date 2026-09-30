from pydantic import ValidationError

from ..domain.entities import RawMessage, ReadSummary
from ..domain.exceptions import KafkaInputError
from ..domain.value_objects import PartitionOffsets, TopicPartition
from .schemas import KafkaOffsetsSchema


def offsets_from_json(payload: dict | str) -> ReadSummary:
    try:
        schema = (
            KafkaOffsetsSchema.model_validate_json(payload)
            if isinstance(payload, str)
            else KafkaOffsetsSchema.model_validate(payload)
        )
    except (ValidationError, ValueError, TypeError, KafkaInputError):
        # Pydantic errors can include the complete input, including arbitrary payload.
        raise KafkaInputError(
            "Invalid kafka_offsets JSON; check version, context and positions"
        ) from None
    values = schema.model_dump(exclude={"schema_version", "partitions"})
    return ReadSummary(
        **values, partitions=tuple(PartitionOffsets(**p.model_dump()) for p in schema.partitions)
    )


def offsets_to_json(summary: ReadSummary) -> dict:
    from dataclasses import asdict

    return KafkaOffsetsSchema.model_validate({"schema_version": 1, **asdict(summary)}).model_dump(
        mode="json", exclude_none=True
    )


def message_from_sdk(record) -> RawMessage:
    return RawMessage(
        TopicPartition(record.topic, record.partition),
        record.offset,
        record.timestamp if record.timestamp is not None and record.timestamp >= 0 else None,
        {0: "CreateTime", 1: "LogAppendTime"}.get(record.timestamp_type),
        record.key,
        record.value,
        tuple(record.headers or ()),
    )
