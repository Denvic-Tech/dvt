from typing import Optional, List

from pydantic import BaseModel


class KafkaBroker(BaseModel):
    node_id: int
    host: str
    port: int
    rack: Optional[str] = None


class KafkaTopic(BaseModel):
    name: str
    partitions_count: int
    replication_factor: int
    is_internal: bool = False


class KafkaCluster(BaseModel):
    controller_id: Optional[int] = None
    brokers: List[KafkaBroker] = []
