from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kafka.errors import KafkaTimeoutError, TopicAuthorizationFailedError

from src.modules.kafka_consumption import OffsetRange, TopicPartition
from src.modules.kafka_consumption.infra.exceptions import KafkaCommitError, KafkaUnavailableError
from src.modules.kafka_consumption.infra.gateways import bounded_client
from src.modules.kafka_consumption.infra.gateways.kafka_python import (
    KafkaPythonGateway,
    KafkaRuntimeSettings,
)


def test_infinite_sdk_metadata_future_is_bounded(monkeypatch):
    clock = iter([0, 0.05, 0.2])
    monkeypatch.setattr(bounded_client, "monotonic", lambda: next(clock))
    monkeypatch.setattr(bounded_client.KafkaClient, "poll", lambda *args, **kwargs: [])
    client = object.__new__(bounded_client.BoundedKafkaClient)
    client._closed = True  # No sockets were created; make the SDK destructor a no-op.
    token = bounded_client.operation_context.set((0.1, lambda: None))
    try:
        with pytest.raises(KafkaTimeoutError):
            client.poll(future=SimpleNamespace(is_done=False))
    finally:
        bounded_client.operation_context.reset(token)


def test_cancel_and_authorization_are_not_retried():
    cancel = MagicMock(side_effect=RuntimeError("cancelled"))
    operation = MagicMock()
    with pytest.raises(RuntimeError, match="cancelled"):
        KafkaPythonGateway({}, check_cancelled=cancel)._retry(operation, "commit")
    operation.assert_not_called()
    operation.side_effect = TopicAuthorizationFailedError("payload-must-not-leak")
    with pytest.raises(KafkaUnavailableError) as error:
        KafkaPythonGateway({})._retry(operation, "metadata")
    assert "payload-must-not-leak" not in str(error.value)
    assert operation.call_count == 1


def test_commit_failure_reports_uncertain_result(monkeypatch):
    consumer = MagicMock()
    consumer.commit.side_effect = KafkaTimeoutError("secret")
    monkeypatch.setattr(
        "src.modules.kafka_consumption.infra.gateways.kafka_python.KafkaConsumer",
        lambda **kwargs: consumer,
    )
    with pytest.raises(KafkaCommitError) as error:
        KafkaPythonGateway({}).commit("group", {TopicPartition("topic", 0): 12})
    assert "secret" not in str(error.value)
    consumer.close.assert_called_once_with(autocommit=False, timeout_ms=30000)


def test_empty_poll_is_not_snapshot_exhaustion(monkeypatch):
    consumer = MagicMock()
    from kafka import TopicPartition as SDKPartition

    tp = SDKPartition("t", 0)
    consumer.beginning_offsets.return_value = {tp: 0}
    consumer.end_offsets.return_value = {tp: 2}
    consumer.poll.return_value = {}
    consumer.position.return_value = 0
    monkeypatch.setattr(
        "src.modules.kafka_consumption.infra.gateways.kafka_python.KafkaConsumer",
        lambda **kwargs: consumer,
    )
    gateway = KafkaPythonGateway(
        {}, settings=KafkaRuntimeSettings(no_progress_timeout_sec=0.001),
    )
    with pytest.raises(KafkaUnavailableError, match="no progress"):
        gateway.read(OffsetRange(TopicPartition("t", 0), 0, 2),
                     isolation_level="read_committed", max_records=10, max_bytes=None,
                     total_max_bytes=None, target_bytes=100, max_message_bytes=100)
    consumer.close.assert_called_once_with(autocommit=False, timeout_ms=30000)
