from ...domain.entities import CommitResult, ReadSummary
from ...domain.exceptions import KafkaInputError
from ...domain.gateways.kafka import CheckCancelled, KafkaGateway
from ...domain.policies import monotonic_commit
from ...domain.value_objects import TopicPartition, nonnegative


class CommitKafkaOffsets:
    """Explicit acknowledgement, assuming exclusive ownership of the group.

    Checking current offsets is not compare-and-set. No rollback is possible after
    submission: a failed/cancelled request may already have changed some partitions.
    """

    def __init__(self, gateway: KafkaGateway, check_cancelled: CheckCancelled):
        self.gateway = gateway
        self.check_cancelled = check_cancelled

    def execute(self, offsets: ReadSummary) -> CommitResult:
        self.check_cancelled()
        if not isinstance(offsets, ReadSummary):
            raise KafkaInputError("Expected validated Kafka offsets")
        if not isinstance(offsets.group_id, str) or not offsets.group_id.strip():
            raise KafkaInputError("group_id must be nonempty")
        TopicPartition(offsets.topic, 0)
        if offsets.isolation_level not in {"read_committed", "read_uncommitted"}:
            raise KafkaInputError("Invalid isolation level")
        if offsets.cluster_id is not None and (
            not isinstance(offsets.cluster_id, str) or not offsets.cluster_id.strip()
        ):
            raise KafkaInputError("cluster_id must be nonempty when provided")
        partitions = tuple(TopicPartition(offsets.topic, p.partition) for p in offsets.partitions)
        if len(set(partitions)) != len(partitions):
            raise KafkaInputError("Duplicate partitions")
        for part in offsets.partitions:
            nonnegative(part.next_offset, "next_offset")

        self.check_cancelled()
        available = self.gateway.partitions(offsets.topic)
        if any(p.partition not in available for p in partitions):
            raise KafkaInputError("Unknown Kafka partition")
        if offsets.cluster_id is not None:
            self.check_cancelled()
            actual = self.gateway.cluster_id()
            if actual != offsets.cluster_id:
                raise KafkaInputError("Kafka cluster context mismatch or unavailable")
        if not partitions:
            self.check_cancelled()
            return CommitResult(())

        self.check_cancelled()
        bounds = self.gateway.bounds(partitions, offsets.isolation_level)
        self.check_cancelled()
        current = self.gateway.committed(offsets.group_id, partitions)
        decisions = tuple(
            monotonic_commit(part.partition, part.next_offset, current[tp], bounds[tp][1])
            for part, tp in zip(offsets.partitions, partitions, strict=True)
        )
        positions = {
            tp: result.requested
            for tp, result in zip(partitions, decisions, strict=True)
            if result.status == "committed"
        }
        self.check_cancelled()
        if positions:
            self.gateway.commit(offsets.group_id, positions)
        self.check_cancelled()
        return CommitResult(decisions)
