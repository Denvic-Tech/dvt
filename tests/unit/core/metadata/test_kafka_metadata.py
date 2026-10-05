from types import SimpleNamespace

from core.metadata.kafka_metadata import (
    _mk_conn_str,
    _normalize_bootstrap,
    build_kafka_metadata,
    kafka_metadata_cache,
    load_kafka_metadata,
)


class FakeNode:
    def __init__(self, node_id, host, port, rack=None):
        self.nodeId = node_id
        self.host = host
        self.port = port
        self.rack = rack


class FakePartition:
    def __init__(self, replicas):
        self.replicas = replicas


class FakeCluster:
    def __init__(self):
        self._brokers = [FakeNode(1, "localhost", 9092)]
        self._topics = {"topic_a", "_internal"}
        self._partitions = {("topic_a", 0): FakePartition([1, 2])}
        self.controller_id = 1

    def brokers(self):
        return self._brokers

    def topics(self):
        return self._topics

    def partitions_for_topic(self, name):
        return {0} if name in self._topics else set()


class FakeClient:
    def __init__(self):
        self.cluster = FakeCluster()

    def poll(self, timeout_ms=0):
        return None


class FakeProducer:
    def __init__(self):
        self.config = {"bootstrap_servers": ["localhost:9092", "localhost:9092"]}
        self._client = FakeClient()


def test_normalize_bootstrap():
    assert _normalize_bootstrap(" localhost:9092 , localhost:9092 ") == ["localhost:9092"]
    assert _normalize_bootstrap(["a:1", "b:2"]) == ["a:1", "b:2"]


def test_mk_conn_str():
    assert _mk_conn_str(["a:1"]) == "kafka://bootstrap=a:1"
    assert _mk_conn_str([]) == "kafka://bootstrap=<unknown>"


def test_build_kafka_metadata_from_admin_response_is_safe():
    metadata = build_kafka_metadata(
        cluster_metadata={
            "controller_id": 2,
            "brokers": [
                {"node_id": 1, "host": "broker-a", "port": 9092, "rack": "rack-a"},
                {"node_id": 2, "host": "broker-b", "port": 9092, "rack": None},
            ],
        },
        topics_metadata=[
            {
                "error_code": 0,
                "topic": "orders",
                "is_internal": False,
                "partitions": [
                    {"partition": 0, "replicas": [1, 2]},
                    {"partition": 1, "replicas": [2, 1]},
                ],
            },
            {
                "error_code": 0,
                "topic": "_internal",
                "partitions": [{"partition": 0, "replicas": [1]}],
            },
        ],
        bootstrap_servers=["SASL_SSL://alice:TOP-SECRET@broker-a:9092"],
    )

    assert metadata.cluster.controller_id == 2
    assert [(broker.node_id, broker.host) for broker in metadata.cluster.brokers] == [
        (1, "broker-a"),
        (2, "broker-b"),
    ]
    topics = {topic.name: topic for topic in metadata.topics}
    assert topics["orders"].partitions_count == 2
    assert topics["orders"].replication_factor == 2
    assert topics["_internal"].is_internal is True
    assert metadata.bootstrap_servers == ["broker-a:9092"]
    serialized = metadata.model_dump_json()
    assert "TOP-SECRET" not in serialized
    assert "alice" not in serialized


def test_load_kafka_metadata_basic():
    kafka_metadata_cache.clear()
    producer = FakeProducer()

    metadata = load_kafka_metadata(producer)

    assert metadata.bootstrap_servers == ["localhost:9092"]
    assert metadata.connection_string == "kafka://bootstrap=localhost:9092"
    assert metadata.cluster.controller_id == 1
    assert len(metadata.cluster.brokers) == 1

    topics = {topic.name: topic for topic in metadata.topics}
    assert topics["topic_a"].partitions_count == 1
    assert topics["topic_a"].replication_factor == 2
    assert topics["_internal"].is_internal is True


def test_load_kafka_metadata_filter_topics():
    kafka_metadata_cache.clear()
    producer = FakeProducer()

    metadata = load_kafka_metadata(producer, topics_filter=["topic_a"])

    assert [topic.name for topic in metadata.topics] == ["topic_a"]
