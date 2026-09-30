from unittest.mock import MagicMock

import pytest
from kafka.errors import KafkaTimeoutError, TopicAuthorizationFailedError

from src.modules.kafka_consumption.domain.value_objects import TopicPartition
from src.modules.kafka_consumption.infra.exceptions import KafkaCommitError
from src.modules.kafka_consumption.infra.gateways.kafka_python import (
    KafkaPythonGateway,
    KafkaRuntimeSettings,
)
from src.node_dsl.exceptions import NodeExecutionCancelled


@pytest.mark.parametrize("failure", ["partial", "lost", "cancel", "auth", "retry_success"])
def test_submission_failure_retry_and_close(monkeypatch, failure):
    consumer = MagicMock()
    configs = []
    def factory(**config):
        configs.append(config)
        return consumer
    monkeypatch.setattr(
        "src.modules.kafka_consumption.infra.gateways.kafka_python.KafkaConsumer", factory
    )
    saved = {}
    cancelled = [False]
    calls = []
    def check():
        if cancelled[0]:
            raise NodeExecutionCancelled("stop")
    def commit(*, offsets, timeout_ms):
        calls.append(offsets)
        assert timeout_ms == 30000
        if failure == "auth":
            raise TopicAuthorizationFailedError("secret-payload")
        pairs = list(offsets.items())
        for tp, value in pairs[:1] if failure == "partial" else pairs:
            saved[tp.partition] = value.offset
        if failure == "cancel":
            cancelled[0] = True
        elif failure == "retry_success" and len(calls) > 1:
            return
        else:
            raise KafkaTimeoutError("secret-payload")
    consumer.commit.side_effect = commit
    gateway = KafkaPythonGateway({}, settings=KafkaRuntimeSettings(attempts=2), check_cancelled=check)
    positions = {TopicPartition("topic", 0): 5, TopicPartition("topic", 1): 7}
    if failure == "retry_success":
        gateway.commit("group", positions)
    else:
        expected = NodeExecutionCancelled if failure == "cancel" else KafkaCommitError
        with pytest.raises(expected) as error:
            gateway.commit("group", positions)
        assert "secret-payload" not in str(error.value)
        assert "may already be saved" in " ".join(error.value.__notes__)
    assert len(calls) == (1 if failure in {"cancel", "auth"} else 2)
    assert saved == ({} if failure == "auth" else {0: 5} if failure == "partial" else {0: 5, 1: 7})
    consumer.close.assert_called_once_with(autocommit=False, timeout_ms=30000)
    assert configs[0]["enable_auto_commit"] is False
    consumer.position.assert_not_called()
    consumer.seek.assert_not_called()


def test_stop_before_send_closes_without_commit(monkeypatch):
    consumer = MagicMock()
    stopped = [False]
    def factory(**_):
        stopped[0] = True
        return consumer
    def check():
        if stopped[0]:
            raise NodeExecutionCancelled("stop")
    monkeypatch.setattr(
        "src.modules.kafka_consumption.infra.gateways.kafka_python.KafkaConsumer", factory
    )
    with pytest.raises(NodeExecutionCancelled):
        KafkaPythonGateway({}, check_cancelled=check).commit("group", {TopicPartition("topic", 0): 5})
    consumer.commit.assert_not_called()
    consumer.close.assert_called_once_with(autocommit=False, timeout_ms=30000)


def test_close_error_does_not_leak_driver_details(monkeypatch):
    consumer = MagicMock()
    consumer.close.side_effect = KafkaTimeoutError("secret-close")
    monkeypatch.setattr(
        "src.modules.kafka_consumption.infra.gateways.kafka_python.KafkaConsumer",
        lambda **_: consumer,
    )
    with pytest.raises(KafkaCommitError) as error:
        KafkaPythonGateway({}).commit("group", {TopicPartition("topic", 0): 5})
    assert "secret-close" not in str(error.value)
    assert "may already be saved" in str(error.value)
    consumer.commit.assert_called_once()
