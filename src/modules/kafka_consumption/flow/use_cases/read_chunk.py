from hashlib import sha256

from ...domain.entities import ChunkReceipt, ReadPlan
from ...domain.gateways.kafka import CheckCancelled, KafkaGateway
from ...domain.value_objects import OffsetRange, PartitionOffsets, PartitionPosition, ReadCursor
from ..exceptions import KafkaConsumptionFlowError


class ReadKafkaChunk:
    def __init__(self, gateway: KafkaGateway, check_cancelled: CheckCancelled):
        self.gateway = gateway
        self.check_cancelled = check_cancelled

    def execute(self, plan: ReadPlan, cursor: ReadCursor, part_number: int):
        self.check_cancelled()
        positions = list(cursor.positions)
        remaining_messages, remaining_bytes = cursor.remaining_messages, cursor.remaining_bytes
        index = cursor.next_partition_index
        reason = cursor.stop_reason
        messages, offsets = [], []
        payload_bytes = 0
        limits = plan.limits
        while reason is None:
            if all(p.next_offset >= r.end for p, r in zip(positions, plan.ranges, strict=True)):
                reason = "snapshot_exhausted"
                break
            if remaining_messages == 0:
                reason = "max_messages"
                break
            if remaining_bytes == 0:
                reason = "max_bytes"
                break
            if (
                len(messages) >= limits.rows_per_partition
                or payload_bytes >= limits.target_partition_bytes
            ):
                break
            position, original = positions[index], plan.ranges[index]
            index = (index + 1) % len(positions)
            if position.next_offset >= original.end:
                continue
            self.check_cancelled()
            rows = limits.rows_per_partition - len(messages)
            batch = self.gateway.read(
                OffsetRange(position.topic_partition, position.next_offset, original.end),
                isolation_level=plan.isolation_level,
                max_records=min(rows, remaining_messages)
                if remaining_messages is not None
                else rows,
                max_bytes=remaining_bytes,
                total_max_bytes=limits.max_bytes,
                target_bytes=limits.target_partition_bytes - payload_bytes,
                max_message_bytes=limits.max_message_bytes,
            )
            if batch.next_position <= position.next_offset and not batch.byte_limit_reached:
                raise KafkaConsumptionFlowError("Kafka chunk made no progress")
            positions[(index - 1) % len(positions)] = PartitionPosition(
                position.topic_partition, batch.next_position
            )
            count = len(batch.messages)
            size = sum(m.payload_bytes for m in batch.messages)
            if count:
                offsets.append(
                    PartitionOffsets(
                        partition=position.topic_partition.partition,
                        start_offset=position.next_offset,
                        next_offset=batch.messages[-1].offset + 1,
                        last_message_offset=batch.messages[-1].offset,
                        message_count=count,
                        payload_bytes=size,
                    )
                )
            messages.extend(batch.messages)
            payload_bytes += size
            if remaining_messages is not None:
                remaining_messages -= count
            if remaining_bytes is not None:
                remaining_bytes -= size
            if batch.byte_limit_reached:
                reason = "max_bytes"
        self.check_cancelled()
        next_cursor = ReadCursor(
            tuple(positions), remaining_messages, remaining_bytes, index, reason
        )
        fingerprint = sha256(repr(tuple(messages)).encode("utf-8")).hexdigest()
        receipt = ChunkReceipt(
            plan.read_id,
            part_number,
            tuple(offsets),
            len(messages),
            payload_bytes,
            fingerprint,
            next_cursor,
        )
        return tuple(messages), receipt

    def replay(self, plan: ReadPlan, receipt: ChunkReceipt):
        """Read only previously accepted ranges; never consume the global budget again."""
        messages = []
        for offset in receipt.offsets:
            self.check_cancelled()
            tp = next(
                r.topic_partition
                for r in plan.ranges
                if r.topic_partition.partition == offset.partition
            )
            batch = self.gateway.read(
                OffsetRange(tp, offset.start_offset, offset.next_offset),
                isolation_level=plan.isolation_level,
                max_records=offset.message_count,
                max_bytes=offset.payload_bytes,
                total_max_bytes=plan.limits.max_bytes,
                target_bytes=offset.payload_bytes + 1,
                max_message_bytes=plan.limits.max_message_bytes,
            )
            messages.extend(batch.messages)
        self.check_cancelled()
        fingerprint = sha256(repr(tuple(messages)).encode("utf-8")).hexdigest()
        if fingerprint != receipt.fingerprint:
            raise KafkaConsumptionFlowError(
                f"Kafka chunk changed: read_id={plan.read_id}, part={receipt.part_number}"
            )
        return tuple(messages), receipt
