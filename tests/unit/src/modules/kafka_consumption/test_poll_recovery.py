"""Exercise real KafkaConsumer.poll/_poll_once with a position-aware fake fetch."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from kafka import KafkaConsumer
from kafka.errors import KafkaTimeoutError
from kafka.structs import OffsetAndMetadata, TopicPartition as SDKTopicPartition

from src.modules.kafka_consumption import OffsetRange, TopicPartition
from src.modules.kafka_consumption.infra.exceptions import (
    KafkaSnapshotLostError,
    KafkaUnavailableError,
)
from src.modules.kafka_consumption.infra.gateways import kafka_python


@pytest.fixture
def sdk_reader(monkeypatch):
    consumers = []

    def make(*, offsets=(0, 1, 2), fail_at=2, repeat=False, cancel=False, lose_snapshot=False):
        consumer = KafkaConsumer(
            bootstrap_servers=[],
            api_version=(3, 6),
            enable_auto_commit=False,
        )
        consumers.append(consumer)
        tp = SDKTopicPartition("retry-topic", 0)
        end = offsets[-1] + 1
        faults = []
        close = MagicMock(wraps=consumer.close)
        monkeypatch.setattr(consumer, "close", close)
        monkeypatch.setattr(kafka_python, "KafkaConsumer", lambda **kwargs: consumer)
        monkeypatch.setattr(
            consumer,
            "beginning_offsets",
            lambda partitions: {tp: end if lose_snapshot and faults else 0},
        )
        monkeypatch.setattr(consumer, "end_offsets", lambda partitions: {tp: end})
        monkeypatch.setattr(consumer._coordinator, "poll", lambda **kwargs: True)
        monkeypatch.setattr(consumer, "_update_fetch_positions", lambda **kwargs: True)

        def fetched_records(max_records, **kwargs):
            position = consumer.position(tp)
            selected = [offset for offset in offsets if offset >= position][: min(2, max_records)]
            consumer._subscription.assignment[tp].position = OffsetAndMetadata(
                selected[-1] + 1 if selected else end,
                "",
                -1,
            )
            return {
                tp: [
                    SimpleNamespace(
                        topic=tp.topic,
                        partition=0,
                        offset=offset,
                        timestamp=None,
                        timestamp_type=None,
                        key=None,
                        value=b"xx",
                        headers=[],
                    )
                    for offset in selected
                ]
            }, False

        def network_poll(timeout_ms=None, **kwargs):
            position = consumer.position(tp)
            if timeout_ms == 0 and position == fail_at and (repeat or not faults):
                faults.append(position)
                raise KafkaTimeoutError("injected after SDK advanced its position")
            return []

        monkeypatch.setattr(consumer._fetcher, "fetched_records", fetched_records)
        monkeypatch.setattr(consumer._fetcher, "send_fetches", lambda: [object()])
        monkeypatch.setattr(consumer._client, "poll", network_poll)

        def check_cancelled():
            if cancel and faults:
                raise RuntimeError("cancelled after failed poll")

        gateway = kafka_python.KafkaPythonGateway({}, check_cancelled=check_cancelled)

        def read(**limits):
            options = {
                "isolation_level": "read_committed",
                "max_records": 100,
                "max_bytes": None,
                "total_max_bytes": None,
                "target_bytes": 100,
                "max_message_bytes": 100,
            }
            options.update(limits)
            return gateway.read(OffsetRange(TopicPartition(tp.topic, 0), 0, end), **options)

        return SimpleNamespace(read=read, faults=faults, close=close, consumer=consumer)

    yield make
    for consumer in consumers:
        if not consumer._closed:
            consumer.close(autocommit=False)


def assert_closed(reader):
    assert reader.consumer._closed
    assert all(call.kwargs["autocommit"] is False for call in reader.close.call_args_list)


def test_retry_returns_records_lost_by_sdk_prefetch(sdk_reader):
    reader = sdk_reader()
    batch = reader.read()
    assert reader.faults == [2]
    assert [message.offset for message in batch.messages] == [0, 1, 2]
    assert batch.next_position == 3 and batch.exhausted
    assert_closed(reader)


@pytest.mark.parametrize(
    "limits, expected, next_position, byte_limit",
    [
        ({"max_records": 5}, [0, 1, 2, 3, 4], 5, False),
        ({"max_bytes": 9, "total_max_bytes": 9}, [0, 1, 2, 3], 4, True),
    ],
)
def test_retry_preserves_accepted_records_and_budgets(
    sdk_reader,
    limits,
    expected,
    next_position,
    byte_limit,
):
    reader = sdk_reader(offsets=tuple(range(6)), fail_at=4)
    batch = reader.read(**limits)
    assert reader.faults == [4]  # Records 0,1 were returned by a successful earlier poll.
    assert [message.offset for message in batch.messages] == expected
    assert sum(message.payload_bytes for message in batch.messages) == 2 * len(expected)
    assert batch.next_position == next_position
    assert batch.byte_limit_reached is byte_limit
    assert not batch.exhausted
    assert_closed(reader)


def test_retry_accepts_gaps_without_skipping_available_records(sdk_reader):
    reader = sdk_reader(offsets=(0, 3, 7), fail_at=4)
    batch = reader.read()
    assert reader.faults == [4]
    assert [message.offset for message in batch.messages] == [0, 3, 7]
    assert batch.next_position == 8 and batch.exhausted
    assert_closed(reader)


def test_exhausted_retries_raise_and_close(sdk_reader):
    reader = sdk_reader(offsets=tuple(range(6)), fail_at=4, repeat=True)
    with pytest.raises(KafkaUnavailableError):
        reader.read()
    assert len(reader.faults) == 3  # Configured bound; never an infinite recovery loop.
    assert_closed(reader)


def test_cancellation_during_retry_raises_and_closes(sdk_reader):
    reader = sdk_reader(offsets=tuple(range(6)), fail_at=4, cancel=True)
    with pytest.raises(RuntimeError, match="cancelled"):
        reader.read()
    assert reader.faults == [4]
    assert_closed(reader)


def test_snapshot_loss_during_retry_raises_and_closes(sdk_reader):
    reader = sdk_reader(lose_snapshot=True)
    with pytest.raises(KafkaSnapshotLostError):
        reader.read()
    assert reader.faults == [2]
    assert_closed(reader)
