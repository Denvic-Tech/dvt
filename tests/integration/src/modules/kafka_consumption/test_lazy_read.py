import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from kafka import KafkaProducer
from kafka.admin import KafkaAdminClient, NewPartitions

from src.node_dsl.cancellation import CancellationToken
from src.node_dsl.exceptions import NodeExecutionCancelled
from src.node_dsl.variables import UnresolvedValue
from src.nodes.extract.read_kafka_messages import ReadKafkaMessages
from src.pipeline.execution_mode import PipelineExecutionMode

pytestmark = pytest.mark.docker_required


def make_node(broker, topic, group, **kwargs):
    return ReadKafkaMessages(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="read",
        connection=SimpleNamespace(
            id="test-connection", properties=broker.dvt_properties, secrets=broker.dvt_secrets
        ),
        topic=topic,
        group_id=group,
        **kwargs,
    )


def test_lazy_snapshot_arrow_count_and_no_autocommit(kafka_container, kafka_resources):
    r = kafka_resources
    topic, group = r.topic(partitions=2), r.group()
    r.publish(
        topic,
        [
            {
                "partition": 0,
                "key": b"\xff",
                "value": b"text",
                "headers": [("dup", b"\x00"), ("dup", None)],
            },
            {"partition": 0, "key": b"", "value": None},
            {"partition": 1, "value": b"other"},
        ],
    )
    n = make_node(kafka_container, topic, group, rows_per_partition=1, max_messages=3)
    asyncio.run(n.execute(PipelineExecutionMode.FULL))
    old_ref = n.output_variables["kafka_offsets"]
    assert isinstance(old_ref.value, UnresolvedValue)
    r.publish(topic, [{"partition": 0, "value": b"later"}])
    admin = KafkaAdminClient(bootstrap_servers=kafka_container.get_bootstrap_server())
    try:
        admin.create_partitions({topic: NewPartitions(total_count=3)})
    finally:
        admin.close()
    n.output.head(1)
    assert isinstance(old_ref.value, UnresolvedValue)
    frame = n.output.compute(scheduler="threads")
    assert len(frame) == 3
    assert set(frame.partition) == {0, 1}
    assert all(isinstance(dtype, pd.ArrowDtype) for dtype in frame.dtypes)
    first = frame[frame.key.notna()].iloc[0]
    assert first.key == b"\xff"
    assert first.headers == [{"key": "dup", "value": b"\x00"}, {"key": "dup", "value": None}]
    assert frame.value.isna().sum() == 1
    assert {p["partition"]: p["next_offset"] for p in old_ref.value["partitions"]} == {0: 2, 1: 1}
    assert r.committed(topic, group) == {0: None, 1: None, 2: None}
    assert len(n.output.compute()) == 3
    assert n.output_variables["kafka_messages_read"].value == 3
    print("KAFKA_READ_EXAMPLE", old_ref.value)


@pytest.mark.parametrize(
    ("settings", "values"),
    [
        ({"max_bytes": 8, "rows_per_partition": 1}, ["abc", "def"]),
        ({"max_bytes": 6, "rows_per_partition": 1}, ["abc", "def"]),
        ({"start_mode": "latest"}, []),
        ({"start_mode": "explicit", "start_offsets": {"0": 1, "1": 0}}, ["ghi", "def"]),
        (
            {
                "start_mode": "timestamp",
                "start_timestamp": datetime.fromtimestamp(1700000000.002, UTC),
            },
            ["ghi"],
        ),
    ],
)
def test_limits_and_positions(kafka_container, kafka_resources, settings, values):
    topic, group = kafka_resources.topic(partitions=2), kafka_resources.group()
    kafka_resources.publish(
        topic,
        [
            {"partition": 0, "value": b"abc", "timestamp_ms": 1700000000000},
            {"partition": 0, "value": b"ghi", "timestamp_ms": 1700000000002},
            {"partition": 1, "value": b"def", "timestamp_ms": 1700000000001},
        ],
    )
    n = make_node(kafka_container, topic, group, **settings)
    n.process()
    assert list(n.output.compute().value) == values
    assert kafka_resources.committed(topic, group) == {0: None, 1: None}


def test_error_and_cancellation_leave_group_unchanged(kafka_container, kafka_resources):
    topic, group = kafka_resources.topic(partitions=2), kafka_resources.group()
    kafka_resources.publish(
        topic,
        [
            {"partition": 0, "value": b"good"},
            {"partition": 1, "value": b"\xff"},
        ],
    )
    n = make_node(kafka_container, topic, group, rows_per_partition=1)
    n.process()
    with pytest.raises(Exception, match="decode"):
        n.output.compute()
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)
    n = make_node(kafka_container, topic, group, rows_per_partition=1, value_format="binary")
    stopped = [False]
    n._cancellation = CancellationToken(lambda: stopped[0])
    n.process()
    n.output.head(1)
    stopped[0] = True
    with pytest.raises(NodeExecutionCancelled):
        n.output.compute()
    assert isinstance(n.output_variables["kafka_offsets"].value, UnresolvedValue)
    assert kafka_resources.committed(topic, group) == {0: None, 1: None}


def test_transaction_stable_snapshot(kafka_container, kafka_resources):
    topic, group = kafka_resources.topic(partitions=2), kafka_resources.group()
    producer = KafkaProducer(
        bootstrap_servers=kafka_container.get_bootstrap_server(),
        transactional_id="reader-" + topic,
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
        producer.begin_transaction()
        producer.send(topic, partition=0, value=b"pending").get(timeout=30)
        n = make_node(kafka_container, topic, group, rows_per_partition=1)
        n.process()
        producer.commit_transaction()
        assert list(n.output.compute().value) == ["committed"]
        data = n.output_variables["kafka_offsets"].value
        assert data["messages_read"] == 1
        assert data["partitions"][0]["next_offset"] == 3
        assert kafka_resources.committed(topic, group) == {0: None, 1: None}
    finally:
        producer.close()
