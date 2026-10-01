from collections.abc import Callable, Mapping, Sequence
from typing import Protocol

from ..entities import ReadBatch
from ..value_objects import IsolationLevel, OffsetRange, TopicPartition

CheckCancelled = Callable[[], None]


class KafkaGateway(Protocol):
    def partitions(self, topic: str) -> tuple[int, ...]: ...
    def cluster_id(self) -> str | None: ...
    def bounds(
        self, partitions: Sequence[TopicPartition], isolation_level: IsolationLevel
    ) -> Mapping[TopicPartition, tuple[int, int]]: ...
    def offsets_for_timestamp(
        self,
        partitions: Sequence[TopicPartition],
        timestamp_ms: int,
        isolation_level: IsolationLevel,
    ) -> Mapping[TopicPartition, int | None]: ...
    def committed(
        self, group_id: str, partitions: Sequence[TopicPartition]
    ) -> Mapping[TopicPartition, int | None]: ...
    def read(
        self,
        offset_range: OffsetRange,
        *,
        isolation_level: IsolationLevel,
        max_records: int,
        max_bytes: int | None,
        total_max_bytes: int | None,
        target_bytes: int,
        max_message_bytes: int,
    ) -> ReadBatch: ...
    def commit(self, group_id: str, positions: Mapping[TopicPartition, int]) -> None: ...
