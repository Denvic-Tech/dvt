from db_connection.connectors.kafka import build_kafka_config

from .domain.gateways.kafka import CheckCancelled, KafkaGateway
from .infra.gateways.kafka_python import KafkaPythonGateway, KafkaRuntimeSettings


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
