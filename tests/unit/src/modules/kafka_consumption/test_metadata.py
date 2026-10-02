from unittest.mock import MagicMock

import pytest
from kafka.errors import KafkaTimeoutError

from src.modules.kafka_consumption import facade as kafka_facade
from src.modules.kafka_consumption.infra.gateways import kafka_python
from src.modules.kafka_consumption.infra.exceptions import KafkaUnavailableError
from src.modules.kafka_consumption.infra.gateways.kafka_python import (
    KafkaPythonGateway,
    KafkaRuntimeSettings,
)


def test_describe_metadata_uses_admin_client_only(monkeypatch):
    admin = MagicMock()
    admin.describe_cluster.return_value = {
        "cluster_id": "cluster-1",
        "controller_id": 1,
        "brokers": [{"node_id": 1, "host": "broker", "port": 9092}],
    }
    admin.describe_topics.return_value = [
        {
            "error_code": 0,
            "topic": "orders",
            "is_internal": False,
            "partitions": [{"partition": 0, "replicas": [1]}],
        }
    ]
    monkeypatch.setattr(kafka_python, "KafkaAdminClient", lambda **_kwargs: admin)

    consumer = MagicMock(side_effect=AssertionError("metadata lookup must not create a consumer"))
    monkeypatch.setattr(kafka_python, "KafkaConsumer", consumer)

    snapshot = KafkaPythonGateway({"bootstrap_servers": ["broker:9092"]}).describe_metadata()

    assert snapshot["cluster"]["cluster_id"] == "cluster-1"
    assert snapshot["topics"][0]["topic"] == "orders"
    admin.describe_cluster.assert_called_once_with()
    admin.describe_topics.assert_called_once_with()
    admin.create_topics.assert_not_called()
    admin.close.assert_called_once_with()
    consumer.assert_not_called()


def test_describe_metadata_failure_is_bounded_and_redacted(monkeypatch):
    admin = MagicMock()
    admin.describe_cluster.side_effect = KafkaTimeoutError("PASSWORD-SECRET")
    monkeypatch.setattr(kafka_python, "KafkaAdminClient", lambda **_kwargs: admin)

    gateway = KafkaPythonGateway(
        {"bootstrap_servers": ["broker:9092"]},
        settings=KafkaRuntimeSettings(attempts=1),
    )
    with pytest.raises(KafkaUnavailableError) as error:
        gateway.describe_metadata()

    assert "PASSWORD-SECRET" not in str(error.value)
    admin.close.assert_called_once_with()


def test_build_gateway_reuses_shared_kafka_config(monkeypatch):
    properties = {
        "bootstrap_servers": ["broker:9093"],
        "security_protocol": "SASL_SSL",
        "ssl_ca_pem": "TEST-CA",
        "sasl_mechanism": "SCRAM-SHA-512",
        "sasl_plain_username": "alice",
    }
    secrets = {"sasl_plain_password": "TEST-PASSWORD"}
    configured = {
        "bootstrap_servers": ["broker:9093"],
        "security_protocol": "SASL_SSL",
        "ssl_context": object(),
        "sasl_mechanism": "SCRAM-SHA-512",
        "sasl_plain_username": "alice",
        "sasl_plain_password": "TEST-PASSWORD",
    }
    captured = {}

    def fake_build_kafka_config(actual_properties, actual_secrets):
        captured["properties"] = actual_properties
        captured["secrets"] = actual_secrets
        return configured

    monkeypatch.setattr(kafka_facade, "build_kafka_config", fake_build_kafka_config)

    gateway = kafka_facade.build_kafka_gateway(
        properties=properties,
        secrets=secrets,
        check_cancelled=lambda: None,
    )

    assert captured == {"properties": properties, "secrets": secrets}
    for key, value in configured.items():
        assert gateway._config[key] is value or gateway._config[key] == value
