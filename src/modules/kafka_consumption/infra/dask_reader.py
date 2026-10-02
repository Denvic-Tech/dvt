"""Local lazy adapter. Shared state contains receipts, never message payload or frames."""

from dataclasses import replace
from threading import RLock

import dask
import dask.dataframe as dd

from ..domain.entities import ReadSummary
from ..domain.exceptions import KafkaInputError
from ..domain.value_objects import PartitionPosition, ReadCursor
from .dataframe import messages_to_dataframe
from .exceptions import KafkaSnapshotLostError


def read_slot_count(plan, max_plan_tasks):
    limits = plan.limits
    count = sum(r.end - r.start for r in plan.ranges)
    if limits.max_messages is not None:
        count = min(count, limits.max_messages)
    size = count * limits.max_message_bytes
    if limits.max_bytes is not None:
        size = min(size, limits.max_bytes)
    slots = (
        min(
            count,
            (
                (count + limits.rows_per_partition - 1) // limits.rows_per_partition
                + (size + limits.target_partition_bytes - 1) // limits.target_partition_bytes
                + 1
            ),
        )
        if count
        else 1
    )
    if slots > max_plan_tasks:
        raise KafkaInputError(
            f"Kafka read needs {slots} tasks; planning limit is {max_plan_tasks}. "
            "Reduce max_messages/max_bytes or increase chunk targets."
        )
    return slots


def _cursor(result):
    return result[1].cursor


def _frame(result, reader, number):
    with reader.lock:
        reader.delivered.add(number)
        # Delayed consumers need the same completion barrier as DataFrame.compute.
        # Only original output IDs count; cursor-only dependencies cannot publish.
        reader.finish()
    return result[0]


def _finish(_meta, _operation_id, *, reader, **_):
    reader.finish()


def _fail(_meta, _operation_id, _exc, *, reader, **_):
    reader.invalidate()


class KafkaDaskReader:
    def __init__(
        self,
        plan,
        *,
        read_chunk,
        replay_chunk,
        publish,
        invalidate,
        check_cancelled,
        formats=None,
        max_plan_tasks=10000,
    ):
        self.plan = plan
        self.read_chunk = read_chunk
        self.replay_chunk = replay_chunk
        self.publish = publish
        self.invalidate_variables = invalidate
        self.check_cancelled = check_cancelled
        self.formats = formats or {}
        self.slots = read_slot_count(plan, max_plan_tasks)
        self.receipts = {}
        self.delivered = set()
        self.failed = False
        self.published = False
        self.lock = RLock()

    def __dask_tokenize__(self):
        return ("kafka-read", self.plan.read_id)

    def __getstate__(self):
        raise TypeError("Kafka reading supports only local synchronous/threaded schedulers")

    def invalidate(self):
        with self.lock:
            self.failed = True
            self.published = False
            self.invalidate_variables()

    def read(self, cursor, number):
        with self.lock:
            try:
                self.check_cancelled()
                if self.failed:
                    raise KafkaSnapshotLostError("Kafka read was invalidated; start a new run")
                previous = self.receipts.get(number)
                if previous is None:
                    messages, receipt = self.read_chunk(self.plan, cursor, number)
                else:
                    messages, receipt = self.replay_chunk(self.plan, previous)
                frame = messages_to_dataframe(messages, **self.formats)
                if number == self.slots - 1 and receipt.cursor.stop_reason is None:
                    raise KafkaSnapshotLostError("Kafka graph exhausted before terminal cursor")
                self.receipts[number] = receipt
            except BaseException:
                self.invalidate()
                raise
            else:
                return frame, receipt

    def finish(self):
        with self.lock:
            try:
                self.check_cancelled()
                if self.failed:
                    raise KafkaSnapshotLostError("Kafka read was invalidated; start a new run")
                if len(self.receipts) != self.slots or len(self.delivered) != self.slots:
                    return
                terminal = self.receipts[self.slots - 1].cursor
                if terminal.stop_reason is None:
                    raise KafkaSnapshotLostError("Kafka read has no terminal cursor")
                if self.published:
                    return
                totals = {}
                for number in range(self.slots):
                    for offset in self.receipts[number].offsets:
                        old = totals.get(offset.partition)
                        totals[offset.partition] = (
                            offset
                            if old is None
                            else replace(
                                offset,
                                start_offset=old.start_offset,
                                message_count=old.message_count + offset.message_count,
                                payload_bytes=old.payload_bytes + offset.payload_bytes,
                            )
                        )
                self.publish(
                    ReadSummary(
                        topic=self.plan.topic,
                        group_id=self.plan.group_id,
                        partitions=tuple(totals[p] for p in sorted(totals)),
                        read_id=self.plan.read_id,
                        cluster_id=self.plan.cluster_id,
                        connection_id=self.plan.connection_id,
                        isolation_level=self.plan.isolation_level,
                        messages_read=sum(r.message_count for r in self.receipts.values()),
                        bytes_read=sum(r.payload_bytes for r in self.receipts.values()),
                        stop_reason=terminal.stop_reason,
                    )
                )
                self.published = True
            except BaseException:
                self.invalidate()
                raise

    def dataframe(self):
        meta = messages_to_dataframe((), **self.formats)
        cursor = ReadCursor(
            tuple(PartitionPosition(r.topic_partition, r.start) for r in self.plan.ranges),
            self.plan.limits.max_messages,
            self.plan.limits.max_bytes,
        )
        frames = []
        for number in range(self.slots):
            result = dask.delayed(self.read, pure=True)(
                cursor, number, dask_key_name=f"kafka-read-{self.plan.read_id}-{number}"
            )
            cursor = dask.delayed(_cursor, pure=True)(result)
            frames.append(dask.delayed(_frame, pure=True)(result, self, number))
        with dask.config.set({"dataframe.convert-string": False}):
            frame = dd.from_delayed(frames, meta=meta)
        return frame.add_callbacks(
            on_end=_finish,
            on_error=_fail,
            metadata={"reader": self},
            metadata_token=self.plan.read_id,
            operation_id=f"kafka-{self.plan.read_id}",
            copy_meta_mode="none",
            copy_partition_mode="none",
            partition_dispatch_mode="sync",
        )
