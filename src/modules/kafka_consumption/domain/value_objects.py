from dataclasses import dataclass
from typing import Literal

from .exceptions import KafkaInputError

IsolationLevel = Literal["read_committed", "read_uncommitted"]
StopReason = Literal["snapshot_exhausted", "max_messages", "max_bytes"]


def nonnegative(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise KafkaInputError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True, order=True)
class TopicPartition:
    topic: str
    partition: int

    def __post_init__(self):
        if not isinstance(self.topic, str) or not self.topic.strip():
            raise KafkaInputError("topic must be nonempty")
        nonnegative(self.partition, "partition")


@dataclass(frozen=True)
class OffsetRange:
    topic_partition: TopicPartition
    start: int
    end: int

    def __post_init__(self):
        nonnegative(self.start, "start")
        nonnegative(self.end, "end")
        if self.start > self.end:
            raise KafkaInputError("start must not exceed end")


@dataclass(frozen=True)
class ReadLimits:
    max_messages: int | None = 100_000
    max_bytes: int | None = 67_108_864
    rows_per_partition: int = 10_000
    target_partition_bytes: int = 8_388_608
    max_message_bytes: int = 16_777_216

    def __post_init__(self):
        for name in (
            "max_messages",
            "max_bytes",
            "rows_per_partition",
            "target_partition_bytes",
            "max_message_bytes",
        ):
            value = getattr(self, name)
            if value is None and name in {"max_messages", "max_bytes"}:
                continue
            nonnegative(value, name)
            if value == 0:
                raise KafkaInputError(f"{name} must be positive")


@dataclass(frozen=True)
class PartitionPosition:
    topic_partition: TopicPartition
    next_offset: int

    def __post_init__(self):
        nonnegative(self.next_offset, "next_offset")


@dataclass(frozen=True)
class ReadCursor:
    positions: tuple[PartitionPosition, ...]
    remaining_messages: int | None
    remaining_bytes: int | None
    next_partition_index: int = 0
    stop_reason: StopReason | None = None

    def __post_init__(self):
        for name in ("remaining_messages", "remaining_bytes", "next_partition_index"):
            value = getattr(self, name)
            if value is not None:
                nonnegative(value, name)


@dataclass(frozen=True)
class PartitionOffsets:
    partition: int
    next_offset: int
    start_offset: int | None = None
    last_message_offset: int | None = None
    message_count: int | None = None
    payload_bytes: int | None = None

    def __post_init__(self):
        for name in (
            "partition",
            "next_offset",
            "start_offset",
            "last_message_offset",
            "message_count",
            "payload_bytes",
        ):
            value = getattr(self, name)
            if value is not None:
                nonnegative(value, name)
        if self.start_offset is not None and self.start_offset > self.next_offset:
            raise KafkaInputError("start_offset exceeds next_offset")
        if self.last_message_offset is not None:
            if self.last_message_offset + 1 != self.next_offset:
                raise KafkaInputError("next_offset must follow last_message_offset")
            if self.start_offset is not None and self.last_message_offset < self.start_offset:
                raise KafkaInputError("last_message_offset precedes start_offset")
