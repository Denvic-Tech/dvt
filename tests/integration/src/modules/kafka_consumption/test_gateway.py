from unittest.mock import patch

import pytest
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaTimeoutError

from src.modules.kafka_consumption import OffsetRange, TopicPartition, build_kafka_gateway
from src.modules.kafka_consumption.domain.exceptions import KafkaMessageTooLargeError
from src.modules.kafka_consumption.infra.dataframe import messages_to_dataframe
from src.modules.kafka_consumption.infra.exceptions import KafkaSnapshotLostError

pytestmark = pytest.mark.docker_required


def gateway_for(broker):
    return build_kafka_gateway(
        properties=broker.dvt_properties, secrets=broker.dvt_secrets, check_cancelled=lambda: None
    )


def read(gateway, tp, start, end, **kwargs):
    return gateway.read(
        OffsetRange(tp, start, end),
        isolation_level="read_committed",
        max_records=kwargs.get("max_records", 100),
        max_bytes=kwargs.get("max_bytes"),
        total_max_bytes=kwargs.get("total_max_bytes"),
        target_bytes=1024 * 1024,
        max_message_bytes=1024 * 1024,
    )


def test_manual_read_positions_and_explicit_commit(kafka_container, kafka_resources):
    resources = kafka_resources
    topic, group = resources.topic(), resources.group()
    resources.publish(
        topic,
        [
            {
                "partition": 0,
                "key": b"\xff",
                "value": b"text",
                "headers": [("dup", b"\x00"), ("dup", None)],
                "timestamp_ms": 1_700_000_000_000,
            },
            {"partition": 0, "key": b"", "value": None},
            {"partition": 1, "value": b"other"},
        ],
    )
    gateway = gateway_for(kafka_container)
    partitions = tuple(TopicPartition(topic, p) for p in gateway.partitions(topic))
    assert len(partitions) == 3
    assert gateway.cluster_id()
    assert gateway.committed(group, partitions) == dict.fromkeys(partitions)
    assert gateway.bounds(partitions, "read_committed") == {
        partitions[0]: (0, 2),
        partitions[1]: (0, 1),
        partitions[2]: (0, 0),
    }
    positions = gateway.offsets_for_timestamp(partitions, 1_700_000_000_000, "read_committed")
    assert positions[partitions[0]] == 0
    batch = read(gateway, partitions[0], 0, 2, max_records=1)
    assert batch.next_position == 1 and not batch.exhausted
    assert batch.messages[0].key == b"\xff"
    assert batch.messages[0].headers == (("dup", b"\x00"), ("dup", None))
    assert messages_to_dataframe(batch.messages).value.iloc[0] == "text"
    assert resources.committed(topic, group) == {0: None, 1: None, 2: None}
    gateway.commit(group, {partitions[0]: batch.messages[-1].offset + 1})
    assert resources.committed(topic, group) == {0: 1, 1: None, 2: None}
    rest = read(gateway, partitions[0], 1, 2)
    assert rest.messages[0].value is None and rest.exhausted
    with pytest.raises(KafkaSnapshotLostError):
        read(gateway, partitions[0], 0, 3)


def test_prefetch_failure_recovers_real_broker_records(
    kafka_container,
    kafka_resources,
    monkeypatch,
):
    topic, group = kafka_resources.topic(), kafka_resources.group()
    kafka_resources.publish(
        topic,
        [{"partition": 0, "value": bytes([offset])} for offset in range(3)],
    )
    tp = TopicPartition(topic, 0)
    gateway = gateway_for(kafka_container)
    original_poll_once = KafkaConsumer._poll_once
    faults = []
    consumers = []

    def poll_once(consumer, timer, max_records, update_offsets=True):
        if not consumers:
            # Fill the real fetch buffer without consuming it so _poll_once takes
            # its fetched_records -> network prefetch -> return branch.
            futures = consumer._fetcher.send_fetches()
            assert futures
            for future in futures:
                consumer._client.poll(timeout_ms=10000, future=future)
                assert future.succeeded()
        consumers.append(consumer)
        before = {
            partition: state.position.offset
            for partition, state in consumer._subscription.assignment.items()
            if state.position is not None
        }
        network_poll = consumer._client.poll

        def inject(timeout_ms=None, future=None):
            advanced = {
                partition: state.position.offset
                for partition, state in consumer._subscription.assignment.items()
                if state.position is not None
                and state.position.offset > before.get(partition, state.position.offset)
            }
            if timeout_ms == 0 and advanced and not faults:
                faults.append(advanced)
                raise KafkaTimeoutError("injected after real fetched_records, before return")
            return network_poll(timeout_ms=timeout_ms, future=future)

        with patch.object(consumer._client, "poll", side_effect=inject):
            return original_poll_once(consumer, timer, max_records, update_offsets)

    monkeypatch.setattr(KafkaConsumer, "_poll_once", poll_once)
    batch = read(gateway, tp, 0, 3)
    assert faults, "Required prefetch fault was not reached"
    assert list(faults[0].values()) == [3]
    assert [message.offset for message in batch.messages] == [0, 1, 2]
    assert [message.value for message in batch.messages] == [bytes([offset]) for offset in range(3)]
    assert batch.exhausted and batch.next_position == 3
    assert all(consumer._closed for consumer in consumers)
    assert kafka_resources.committed(topic, group) == {0: None, 1: None, 2: None}


def test_byte_boundary_does_not_skip_record(kafka_container, kafka_resources):
    topic = kafka_resources.topic()
    kafka_resources.publish(
        topic,
        [
            {"partition": 0, "value": b"123"},
            {"partition": 0, "value": b"4567"},
            {"partition": 0, "value": b"x"},
        ],
    )
    tp = TopicPartition(topic, 0)
    gateway = gateway_for(kafka_container)
    batch = read(gateway, tp, 0, 3, max_bytes=5, total_max_bytes=5)
    assert [m.offset for m in batch.messages] == [0]
    assert batch.next_position == 1 and batch.byte_limit_reached
    with pytest.raises(KafkaMessageTooLargeError):
        read(gateway, tp, 1, 3, max_bytes=3, total_max_bytes=3)


def test_read_committed_uses_stable_boundary(kafka_container, kafka_resources):
    topic = kafka_resources.topic()
    tp = TopicPartition(topic, 0)
    gateway = gateway_for(kafka_container)
    producer = KafkaProducer(
        bootstrap_servers=kafka_container.get_bootstrap_server(),
        transactional_id="dvt-tx-" + topic,
        enable_idempotence=True,
    )
    try:
        producer.init_transactions()
        producer.begin_transaction()
        producer.send(topic, partition=0, value=b"aborted").get(timeout=30)
        producer.abort_transaction()
        producer.begin_transaction()
        producer.send(topic, partition=0, value=b"committed").get(timeout=30)
        producer.commit_transaction()
        stable_end = gateway.bounds([tp], "read_committed")[tp][1]
        producer.begin_transaction()
        producer.send(topic, partition=0, value=b"pending").get(timeout=30)
        assert gateway.bounds([tp], "read_committed")[tp][1] == stable_end
        assert gateway.bounds([tp], "read_uncommitted")[tp][1] > stable_end
        batch = read(gateway, tp, 0, stable_end)
        assert [m.value for m in batch.messages] == [b"committed"]
        assert batch.exhausted
        producer.abort_transaction()
    finally:
        producer.close()
