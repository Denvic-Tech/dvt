import contextlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from cachetools import TTLCache, cached  # type: ignore

from core.types import KafkaBroker, KafkaCluster, KafkaMetadata, KafkaTopic


def _normalize_bootstrap(value: str | list[str] | None) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        servers = value
    else:
        servers = [s.strip() for s in value.split(",") if s.strip()]

    def _clean(s: str) -> str:
        cleaned = re.sub(r"\s+", "", s)
        if "://" in cleaned:
            cleaned = cleaned.split("://", 1)[1]
        if "@" in cleaned:
            cleaned = cleaned.rsplit("@", 1)[1]
        return cleaned

    return sorted({_clean(s) for s in servers})


def _mk_conn_str(bootstrap: list[str]) -> str:
    return "kafka://" + ("bootstrap=" + ",".join(bootstrap) if bootstrap else "bootstrap=<unknown>")


def build_kafka_metadata(
    *,
    cluster_metadata: Mapping[str, Any],
    topics_metadata: Sequence[Mapping[str, Any]],
    bootstrap_servers: str | list[str] | None = None,
) -> KafkaMetadata:
    """Build transport-safe Kafka metadata from Kafka Admin API responses."""
    brokers: list[KafkaBroker] = []
    for broker in cluster_metadata.get("brokers", []) or []:
        if not isinstance(broker, Mapping):
            continue
        node_id = broker.get("node_id", broker.get("nodeId"))
        host = broker.get("host")
        port = broker.get("port")
        if node_id is None or host is None or port is None:
            continue
        brokers.append(
            KafkaBroker(
                node_id=int(node_id),
                host=str(host),
                port=int(port),
                rack=None if broker.get("rack") is None else str(broker["rack"]),
            )
        )

    topics: list[KafkaTopic] = []
    for topic in topics_metadata:
        if not isinstance(topic, Mapping):
            continue
        error_code = topic.get("error_code", 0)
        if error_code not in (None, 0):
            continue
        name = topic.get("topic", topic.get("name"))
        if name is None:
            continue
        partitions = topic.get("partitions", []) or []
        partitions_count = len(partitions) if isinstance(partitions, Sequence) else 0
        replication_factor = 0
        if partitions_count:
            first_partition = partitions[0]
            if isinstance(first_partition, Mapping):
                replicas = first_partition.get("replicas", []) or []
                if isinstance(replicas, Sequence):
                    replication_factor = len(replicas)
        topic_name = str(name)
        topics.append(
            KafkaTopic(
                name=topic_name,
                partitions_count=partitions_count,
                replication_factor=replication_factor,
                is_internal=bool(topic.get("is_internal", topic_name.startswith("_"))),
            )
        )

    controller_id = cluster_metadata.get("controller_id")
    bootstrap = _normalize_bootstrap(bootstrap_servers)
    return KafkaMetadata(
        cluster=KafkaCluster(
            controller_id=None if controller_id is None else int(controller_id),
            brokers=brokers,
        ),
        topics=sorted(topics, key=lambda topic: topic.name),
        bootstrap_servers=bootstrap,
        connection_string=_mk_conn_str(bootstrap),
    )


def _get_bootstrap_from_producer(producer: Any) -> list[str]:
    """
    Пытается извлечь bootstrap_servers из KafkaProducer.
    """
    try:
        conf = getattr(producer, "config", None)
        if conf and "bootstrap_servers" in conf:
            return _normalize_bootstrap(conf["bootstrap_servers"])
    except Exception:
        pass

    try:
        cluster = producer._client.cluster
        bs = [f"{n.host}:{n.port}" for n in cluster.brokers()]
        return _normalize_bootstrap(bs)
    except Exception:
        return []


kafka_metadata_cache = TTLCache(maxsize=100, ttl=2)  # 5 минут, как у БД


@cached(  # type: ignore
    cache=kafka_metadata_cache,
    key=lambda producer, topics_filter=None, timeout=5.0:
    ",".join(_get_bootstrap_from_producer(producer)) + "|" +
    ",".join(sorted(topics_filter or []))
)
def load_kafka_metadata(
        producer: Any,
        topics_filter: list[str] | None = None,
        timeout: float = 5.0,
) -> KafkaMetadata:
    """
    Загружает минимальную метадату Kafka, используя уже созданный kafka.KafkaProducer.
    Никаких новых подключений не создаётся.

    :param producer: готовый KafkaProducer
    :param topics_filter: список имён тем; если None — все доступные
    :param timeout: таймаут ожидания обновления метадаты (сек)
    """
    # Обновим локальную метадату продьюсера
    with contextlib.suppress(Exception):
        producer._client.poll(timeout_ms=int(timeout * 1000))

    cluster = producer._client.cluster

    # --- brokers ---
    brokers: list[KafkaBroker] = []
    try:
        for node in cluster.brokers():
            brokers.append(
                KafkaBroker(
                    node_id=node.nodeId,
                    host=node.host,
                    port=node.port,
                    rack=getattr(node, "rack", None),
                )
            )
    except Exception:
        brokers = []

    # --- topics ---
    try:
        all_names: set[str] = set(cluster.topics())
    except Exception:
        all_names = set()

    names: list[str]
    if topics_filter is None:
        names = sorted(all_names)
    else:
        tf = set(topics_filter)
        names = sorted(n for n in all_names if n in tf)

    topics: list[KafkaTopic] = []
    for name in names:
        try:
            parts = cluster.partitions_for_topic(name) or set()
            partitions_count = len(parts)
            # Посчитаем фактор репликации по любой партиции
            replication_factor = 0
            if partitions_count:
                pid = next(iter(parts))
                # В kafka-python публичного доступа к replica set нет,
                # поэтому берём из защищённой структуры _partitions.
                tp = cluster._partitions.get((name, pid))
                replication_factor = len(getattr(tp, "replicas", []) or [])

        except Exception:
            partitions_count = 0
            replication_factor = 0

        topics.append(
            KafkaTopic(
                name=name,
                partitions_count=partitions_count,
                replication_factor=replication_factor,
                is_internal=name.startswith("_"),
            )
        )

    # --- cluster header ---
    try:
        controller_id = getattr(cluster, "controller_id", None)
    except Exception:
        controller_id = None

    kcluster = KafkaCluster(controller_id=controller_id, brokers=brokers)

    bootstrap = _get_bootstrap_from_producer(producer)
    return KafkaMetadata(
        cluster=kcluster,
        topics=topics,
        bootstrap_servers=bootstrap,
        connection_string=_mk_conn_str(bootstrap),
    )
