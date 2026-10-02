from dataclasses import dataclass

from .value_objects import (
    IsolationLevel,
    OffsetRange,
    PartitionOffsets,
    ReadCursor,
    ReadLimits,
    StopReason,
    TopicPartition,
)


@dataclass(frozen=True)
class ReadPlan:
    read_id: str
    topic: str
    group_id: str
    ranges: tuple[OffsetRange, ...]
    limits: ReadLimits
    isolation_level: IsolationLevel = "read_committed"
    cluster_id: str | None = None
    connection_id: str | None = None


@dataclass(frozen=True)
class RawMessage:
    topic_partition: TopicPartition
    offset: int
    timestamp_ms: int | None
    timestamp_type: str | None
    key: bytes | None
    value: bytes | None
    headers: tuple[tuple[str, bytes | None], ...] = ()

    @property
    def payload_bytes(self) -> int:
        return (
            len(self.key or b"")
            + len(self.value or b"")
            + sum(len(key.encode("utf-8")) + len(value or b"") for key, value in self.headers)
        )


@dataclass(frozen=True)
class ReadBatch:
    messages: tuple[RawMessage, ...]
    # Scan position may pass control/aborted records. Never use it for commit.
    next_position: int
    exhausted: bool
    byte_limit_reached: bool = False


@dataclass(frozen=True)
class ChunkReceipt:
    read_id: str
    part_number: int
    offsets: tuple[PartitionOffsets, ...]
    message_count: int
    payload_bytes: int
    fingerprint: str
    cursor: ReadCursor


@dataclass(frozen=True)
class ReadSummary:
    topic: str
    group_id: str
    partitions: tuple[PartitionOffsets, ...]
    read_id: str | None = None
    cluster_id: str | None = None
    connection_id: str | None = None
    isolation_level: IsolationLevel = "read_committed"
    messages_read: int | None = None
    bytes_read: int | None = None
    stop_reason: StopReason | None = None


@dataclass(frozen=True)
class PartitionCommitResult:
    partition: int
    requested: int
    current: int | None
    resulting: int
    status: str


@dataclass(frozen=True)
class CommitResult:
    partitions: tuple[PartitionCommitResult, ...]

    @property
    def partitions_committed(self) -> int:
        return sum(item.status == "committed" for item in self.partitions)
