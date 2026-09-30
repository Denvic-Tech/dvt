from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from ..domain.value_objects import PartitionOffsets

Position = Annotated[StrictInt, Field(ge=0)]


class PartitionOffsetsSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    partition: Position
    next_offset: Position
    start_offset: Position | None = None
    last_message_offset: Position | None = None
    message_count: Position | None = None
    payload_bytes: Position | None = None

    @model_validator(mode="after")
    def validate_positions(self):
        PartitionOffsets(**self.model_dump())
        return self


class KafkaOffsetsSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: StrictInt
    topic: Annotated[str, Field(min_length=1)]
    group_id: Annotated[str, Field(min_length=1)]
    partitions: list[PartitionOffsetsSchema]
    read_id: str | None = None
    cluster_id: str | None = None
    connection_id: str | None = None
    isolation_level: Literal["read_committed", "read_uncommitted"] = "read_committed"
    messages_read: Position | None = None
    bytes_read: Position | None = None
    stop_reason: Literal["snapshot_exhausted", "max_messages", "max_bytes"] | None = None

    @model_validator(mode="after")
    def validate_envelope(self):
        if self.schema_version != 1:
            raise ValueError("Unsupported kafka_offsets schema_version")
        if not self.topic.strip() or not self.group_id.strip():
            raise ValueError("topic and group_id must be nonempty")
        ids = [part.partition for part in self.partitions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate partitions")
        return self
