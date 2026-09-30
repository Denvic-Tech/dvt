from datetime import datetime
from uuid import uuid4

from ...domain.entities import ReadPlan
from ...domain.exceptions import KafkaInputError
from ...domain.gateways.kafka import CheckCancelled, KafkaGateway
from ...domain.policies import select_start_position
from ...domain.value_objects import OffsetRange, ReadLimits, TopicPartition, nonnegative


class PlanKafkaRead:
    def __init__(self, gateway: KafkaGateway, check_cancelled: CheckCancelled):
        self.gateway = gateway
        self.check_cancelled = check_cancelled

    def execute(
        self,
        *,
        topic: str,
        group_id: str,
        limits: ReadLimits,
        partitions=None,
        start_mode="committed",
        missing_offset_policy="earliest",
        start_timestamp: datetime | None = None,
        start_offsets=None,
        isolation_level="read_committed",
        connection_id=None,
    ) -> ReadPlan:
        TopicPartition(topic, 0)
        if not isinstance(group_id, str) or not group_id.strip():
            raise KafkaInputError("group_id must be nonempty")
        if start_mode not in {"committed", "earliest", "latest", "timestamp", "explicit"}:
            raise KafkaInputError("Invalid start mode")
        if missing_offset_policy not in {"earliest", "latest", "error"}:
            raise KafkaInputError("Invalid missing offset policy")
        if isolation_level not in {"read_committed", "read_uncommitted"}:
            raise KafkaInputError("Invalid isolation level")
        if start_mode == "timestamp" and (
            not isinstance(start_timestamp, datetime) or start_timestamp.utcoffset() is None
        ):
            raise KafkaInputError("timestamp mode requires a timezone-aware start_timestamp")
        self.check_cancelled()
        available = self.gateway.partitions(topic)
        selected = tuple(available if partitions is None else partitions)
        for partition in selected:
            nonnegative(partition, "partition")
        if not selected or len(set(selected)) != len(selected) or set(selected) - set(available):
            raise KafkaInputError("Partitions must be nonempty, unique and available")
        tps = tuple(TopicPartition(topic, p) for p in sorted(selected))
        if start_mode == "explicit":
            if not isinstance(start_offsets, dict) or set(start_offsets) != {
                str(p) for p in selected
            }:
                raise KafkaInputError(
                    "start_offsets must contain exactly the selected partition IDs"
                )
            for value in start_offsets.values():
                nonnegative(value, "start_offset")
        self.check_cancelled()
        bounds = self.gateway.bounds(tps, isolation_level)
        committed = self.gateway.committed(group_id, tps) if start_mode == "committed" else {}
        timestamps = (
            self.gateway.offsets_for_timestamp(
                tps, int(start_timestamp.timestamp() * 1000), isolation_level
            )
            if start_mode == "timestamp"
            else {}
        )
        ranges = tuple(
            OffsetRange(
                tp,
                select_start_position(
                    mode=start_mode,
                    beginning=bounds[tp][0],
                    end=bounds[tp][1],
                    committed=committed.get(tp),
                    missing_policy=missing_offset_policy,
                    timestamp_position=timestamps.get(tp),
                    explicit_position=(start_offsets or {}).get(str(tp.partition)),
                ),
                bounds[tp][1],
            )
            for tp in tps
        )
        self.check_cancelled()
        return ReadPlan(
            read_id=str(uuid4()),
            topic=topic,
            group_id=group_id,
            ranges=ranges,
            limits=limits,
            isolation_level=isolation_level,
            cluster_id=self.gateway.cluster_id(),
            connection_id=connection_id,
        )
