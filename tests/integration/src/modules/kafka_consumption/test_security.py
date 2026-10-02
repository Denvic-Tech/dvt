from uuid import uuid4

import pytest
from db_connection.connectors.kafka import build_kafka_config
from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic

from src.modules.kafka_consumption import OffsetRange, TopicPartition, build_kafka_gateway
from src.modules.kafka_consumption.infra.exceptions import KafkaUnavailableError
from src.modules.kafka_consumption.infra.gateways.kafka_python import KafkaRuntimeSettings

pytestmark = pytest.mark.docker_required


def test_security_read_commit_and_reject_bad_credentials(kafka_security_container):
    broker = kafka_security_container
    config = build_kafka_config(broker.dvt_properties, broker.dvt_secrets)
    admin = KafkaAdminClient(**config)
    topic, group = "dvt-security-" + uuid4().hex, "dvt-group-" + uuid4().hex
    producer = None
    try:
        admin.create_topics([NewTopic(topic, 2, 1)])
        producer = KafkaProducer(**config)
        producer.send(topic, partition=0, value=b"secured").get(timeout=30)
        gateway = build_kafka_gateway(
            properties=broker.dvt_properties,
            secrets=broker.dvt_secrets,
            check_cancelled=lambda: None,
        )
        tp = TopicPartition(topic, 0)
        assert gateway.bounds([tp], "read_committed")[tp] == (0, 1)
        batch = gateway.read(
            OffsetRange(tp, 0, 1),
            isolation_level="read_committed",
            max_records=10,
            max_bytes=100,
            total_max_bytes=100,
            target_bytes=100,
            max_message_bytes=100,
        )
        assert batch.messages[0].value == b"secured"
        gateway.commit(group, {tp: 1})
        assert gateway.committed(group, [tp])[tp] == 1

        properties, credentials = dict(broker.dvt_properties), dict(broker.dvt_secrets)
        if credentials:
            credentials["sasl_plain_password"] = "incorrect"
        else:
            # System trust does not trust the ephemeral CA.
            properties.pop("ssl_ca_pem")
        bad = build_kafka_gateway(
            properties=properties,
            secrets=credentials,
            check_cancelled=lambda: None,
            settings=KafkaRuntimeSettings(attempts=1, request_timeout_ms=5000),
        )
        with pytest.raises((KafkaUnavailableError,)):
            bad.partitions(topic)
    finally:
        if producer is not None:
            producer.close()
        try:
            admin.delete_consumer_groups([group])
            admin.delete_topics([topic])
        finally:
            admin.close()
