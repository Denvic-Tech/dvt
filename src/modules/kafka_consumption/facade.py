from db_connection.connectors.kafka import build_kafka_config

from .domain.gateways.kafka import CheckCancelled, KafkaGateway
from .flow.use_cases import CommitKafkaOffsets, PlanKafkaRead, ReadKafkaChunk
from .infra.dask_reader import KafkaDaskReader
from .infra.gateways.kafka_python import KafkaPythonGateway, KafkaRuntimeSettings

__all__ = [
    "CommitKafkaOffsets", "KafkaDaskReader", "KafkaRuntimeSettings", "PlanKafkaRead", "ReadKafkaChunk",
    "build_kafka_gateway",
]


def build_kafka_gateway(
    *,
    properties: dict,
    secrets: dict,
    check_cancelled: CheckCancelled,
    settings: KafkaRuntimeSettings | None = None,
) -> KafkaGateway:
    return KafkaPythonGateway(
        build_kafka_config(properties, secrets),
        settings=settings,
        check_cancelled=check_cancelled,
    )
