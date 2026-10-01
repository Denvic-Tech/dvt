"""Kafka consumption contracts. Flow use cases are added in the subsequent tasks."""

from .domain.entities import (
    ChunkReceipt,
    CommitResult,
    PartitionCommitResult,
    RawMessage,
    ReadBatch,
    ReadPlan,
    ReadSummary,
)
from .domain.gateways.kafka import KafkaGateway
from .domain.value_objects import (
    OffsetRange,
    PartitionOffsets,
    PartitionPosition,
    ReadCursor,
    ReadLimits,
    TopicPartition,
)
from .facade import build_kafka_gateway
from .infra.gateways.kafka_python import KafkaRuntimeSettings

__all__ = [
    "ChunkReceipt",
    "CommitResult",
    "KafkaGateway",
    "KafkaRuntimeSettings",
    "OffsetRange",
    "PartitionCommitResult",
    "PartitionOffsets",
    "PartitionPosition",
    "RawMessage",
    "ReadBatch",
    "ReadCursor",
    "ReadLimits",
    "ReadPlan",
    "ReadSummary",
    "TopicPartition",
    "build_kafka_gateway",
]
