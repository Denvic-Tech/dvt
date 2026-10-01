"""Final acceptance gaps using the shared session KRaft broker."""

import pytest
from kafka.admin import KafkaAdminClient
from kafka.structs import TopicPartition as SDKTopicPartition
from tests.integration.src.modules.kafka_consumption.test_lazy_read import make_node

from src.modules.kafka_consumption import TopicPartition, build_kafka_gateway
from src.modules.kafka_consumption.domain.exceptions import KafkaInputError, KafkaPositionError
from src.modules.kafka_consumption.infra.exceptions import KafkaSnapshotLostError
from src.node_dsl.variables import UnresolvedValue

pytestmark = pytest.mark.docker_required


def test_missing_position_policies_and_earliest_override(kafka_container, kafka_resources):
    r = kafka_resources
    topic, group = r.topic(partitions=2), r.group()
    r.publish(topic, [{"partition": p, "value": b"value"} for p in (0, 1)])
    with pytest.raises(KafkaPositionError):
        make_node(kafka_container, topic, group, missing_offset_policy="error").process()
    node = make_node(kafka_container, topic, group, missing_offset_policy="latest")
    node.process()
    assert isinstance(node.output_variables["kafka_offsets"].value, UnresolvedValue)
    assert node.output.compute().empty
    assert node.output_variables["kafka_offsets"].value["partitions"] == []
    assert r.committed(topic, group) == {0: None, 1: None}
    gateway = build_kafka_gateway(
        properties=kafka_container.dvt_properties, secrets=kafka_container.dvt_secrets,
        check_cancelled=lambda: None,
    )
    gateway.commit(group, {TopicPartition(topic, p): 1 for p in (0, 1)})
    node = make_node(kafka_container, topic, group)
    node.process()
    assert node.output.compute().empty
    node = make_node(kafka_container, topic, group, start_mode="earliest")
    node.process()
    assert len(node.output.compute()) == 2
    assert r.committed(topic, group) == {0: 1, 1: 1}


def test_deleted_history_invalidates_snapshot_and_stale_group(kafka_container, kafka_resources):
    r = kafka_resources
    topic, group = r.topic(partitions=2), r.group()
    r.publish(topic, [{"partition": 0, "value": b"value"} for _ in range(3)])
    gateway = build_kafka_gateway(
        properties=kafka_container.dvt_properties, secrets=kafka_container.dvt_secrets,
        check_cancelled=lambda: None,
    )
    gateway.commit(group, {TopicPartition(topic, 0): 0})
    node = make_node(kafka_container, topic, group)
    node.process()
    admin = KafkaAdminClient(bootstrap_servers=kafka_container.get_bootstrap_server())
    try:
        # Deterministically move log-start offset instead of waiting for retention timers.
        admin.delete_records({SDKTopicPartition(topic, 0): 2})
    finally:
        admin.close()
    with pytest.raises(KafkaSnapshotLostError):
        node.output.compute()
    assert isinstance(node.output_variables["kafka_offsets"].value, UnresolvedValue)
    with pytest.raises(KafkaPositionError):
        make_node(kafka_container, topic, group).process()
    assert r.committed(topic, group) == {0: 0, 1: None}


def test_unknown_topic_and_partition_fail_without_autocreate(kafka_container, kafka_resources):
    topic, group = kafka_resources.topic(partitions=2), kafka_resources.group()
    with pytest.raises(KafkaInputError):
        make_node(kafka_container, topic, group, partitions=[2]).process()
    with pytest.raises(KafkaInputError):
        make_node(kafka_container, topic + "-missing", group).process()
    admin = KafkaAdminClient(bootstrap_servers=kafka_container.get_bootstrap_server())
    try:
        assert topic + "-missing" not in admin.list_topics()
    finally:
        admin.close()
    assert kafka_resources.committed(topic, group) == {0: None, 1: None}
