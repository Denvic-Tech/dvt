import re
from typing import List, Optional, Any, Set
from cachetools import TTLCache, cached  # type: ignore

from core.types import KafkaMetadata
from core.types import KafkaBroker, KafkaTopic, KafkaCluster


def _normalize_bootstrap(value: Optional[str | List[str]]) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        servers = value
    else:
        servers = [s.strip() for s in value.split(",") if s.strip()]

    def _clean(s: str) -> str:
        return re.sub(r"\s+", "", s)

    return sorted(set(_clean(s) for s in servers))


def _mk_conn_str(bootstrap: List[str]) -> str:
    return "kafka://" + ("bootstrap=" + ",".join(bootstrap) if bootstrap else "bootstrap=<unknown>")


def _get_bootstrap_from_producer(producer: Any) -> List[str]:
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
        topics_filter: Optional[List[str]] = None,
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
    try:
        producer._client.poll(timeout_ms=int(timeout * 1000))
    except Exception:
        pass

    cluster = producer._client.cluster

    # --- brokers ---
    brokers: List[KafkaBroker] = []
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
        all_names: Set[str] = set(cluster.topics())
    except Exception:
        all_names = set()

    names: List[str]
    if topics_filter is None:
        names = sorted(all_names)
    else:
        tf = set(topics_filter)
        names = sorted(n for n in all_names if n in tf)

    topics: List[KafkaTopic] = []
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
