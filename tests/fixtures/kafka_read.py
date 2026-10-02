"""In-memory domain gateway for reader unit tests, never used by integration tests."""

from src.modules.kafka_consumption.domain.entities import RawMessage, ReadBatch
from src.modules.kafka_consumption.domain.exceptions import KafkaMessageTooLargeError
from src.modules.kafka_consumption.domain.value_objects import TopicPartition


class MemoryKafka:
    def __init__(self, values=None):
        self.records = {
            p: [
                RawMessage(
                    TopicPartition("topic", p),
                    offset,
                    1700000000000 + offset,
                    "CreateTime",
                    None,
                    value,
                )
                for offset, value in entries
            ]
            for p, entries in (
                values or {0: [(i, b"abc") for i in range(5)], 1: [(i, b"def") for i in range(4)]}
            ).items()
        }
        self.starts = dict.fromkeys(self.records, 0)
        self.ends = {
            p: max((m.offset + 1 for m in messages), default=0)
            for p, messages in self.records.items()
        }
        self.commits = {}
        self.calls = []

    def partitions(self, topic):
        return tuple(sorted(self.records))

    def cluster_id(self):
        return "test-cluster"

    def bounds(self, partitions, isolation_level):
        return {tp: (self.starts[tp.partition], self.ends[tp.partition]) for tp in partitions}

    def committed(self, group_id, partitions):
        return {tp: self.commits.get(tp.partition) for tp in partitions}

    def offsets_for_timestamp(self, partitions, timestamp_ms, isolation_level):
        return {
            tp: next(
                (m.offset for m in self.records[tp.partition] if m.timestamp_ms >= timestamp_ms),
                None,
            )
            for tp in partitions
        }

    def read(
        self,
        r,
        *,
        max_records,
        max_bytes,
        total_max_bytes,
        target_bytes,
        max_message_bytes,
        isolation_level,
    ):
        self.calls.append(r)
        messages, size = [], 0
        for m in self.records[r.topic_partition.partition]:
            if not r.start <= m.offset < r.end:
                continue
            if m.payload_bytes > max_message_bytes or (
                total_max_bytes is not None and m.payload_bytes > total_max_bytes
            ):
                raise KafkaMessageTooLargeError("message too large")
            if max_bytes is not None and size + m.payload_bytes > max_bytes:
                return ReadBatch(tuple(messages), m.offset, False, True)
            messages.append(m)
            size += m.payload_bytes
            if len(messages) >= max_records or size >= target_bytes:
                return ReadBatch(tuple(messages), m.offset + 1, m.offset + 1 >= r.end)
        return ReadBatch(tuple(messages), r.end, True)
