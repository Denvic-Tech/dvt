from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.node_dsl import IO, KafkaConnectionRecord
from src.nodes.connection.get_exist_kafka_connection import node as module


@pytest.mark.asyncio
@pytest.mark.parametrize("connection_id", ["catalog-id", 17])
async def test_resolves_record_without_producer(monkeypatch, connection_id):
    record = SimpleNamespace(id=str(connection_id), name="test", kind="queue", type="kafka")
    service = SimpleNamespace(get=AsyncMock(return_value=record))
    monkeypatch.setattr(module, "build_connection_service", lambda **kwargs: service)
    instance = object.__new__(module.GetExistKafkaConnection)
    instance.connection_id = connection_id
    user = object()
    monkeypatch.setattr(module.GetExistKafkaConnection, "_get_user", AsyncMock(return_value=user))
    result = await instance._get_connection_from_db()
    assert result.record is record
    service.get.assert_awaited_once_with(str(connection_id), actor=user)
    assert not module.GetExistKafkaConnection.input_fields()["connection_id"].is_hidden
    assert (
        module.GetExistKafkaConnection.input_fields()["connection_id"].resolved_type
        == IO.KAFKA_CONNECTION_ID
    )


@pytest.mark.asyncio
async def test_infer_metadata_uses_record_and_does_not_serialize_secrets(monkeypatch):
    record = SimpleNamespace(
        id="kafka-1",
        name="Kafka",
        kind="queue",
        type="kafka",
        driver=None,
        driver_options=None,
        properties={
            "bootstrap_servers": ["broker:9093"],
            "security_protocol": "SASL_SSL",
            "ssl_ca_pem": "CA-SECRET-BODY",
            "sasl_mechanism": "PLAIN",
            "sasl_plain_username": "alice",
        },
        secrets={"sasl_plain_password": "PASSWORD-SECRET"},
    )
    connection = KafkaConnectionRecord(record)
    captured = {}

    class FakeGateway:
        def describe_metadata(self):
            return {
                "cluster": {
                    "controller_id": 1,
                    "brokers": [{"node_id": 1, "host": "broker", "port": 9093}],
                },
                "topics": [
                    {
                        "error_code": 0,
                        "topic": "orders",
                        "is_internal": False,
                        "partitions": [{"partition": 0, "replicas": [1]}],
                    }
                ],
            }

    def build_gateway(**kwargs):
        captured.update(kwargs)
        return FakeGateway()

    monkeypatch.setattr(module, "build_kafka_gateway", build_gateway)
    instance = object.__new__(module.GetExistKafkaConnection)
    instance.connection = connection
    instance._cancellation = SimpleNamespace(raise_if_requested=lambda: None)

    metadata = await instance.infer_metadata()

    assert captured["properties"] is record.properties
    assert captured["secrets"] is record.secrets
    kafka_metadata = metadata["connection"]
    assert kafka_metadata.cluster.brokers[0].host == "broker"
    assert kafka_metadata.topics[0].partitions_count == 1
    assert kafka_metadata.bootstrap_servers == ["broker:9093"]
    serialized = kafka_metadata.model_dump_json()
    assert "PASSWORD-SECRET" not in serialized
    assert "CA-SECRET-BODY" not in serialized
    assert "alice" not in serialized
