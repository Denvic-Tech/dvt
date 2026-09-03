from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CacheNamespaces:
    data: str
    data_index: str
    metadata: str
    metadata_index: str

    def __post_init__(self) -> None:
        values = {
            "data": self.data,
            "data_index": self.data_index,
            "metadata": self.metadata,
            "metadata_index": self.metadata_index,
        }
        for name, value in values.items():
            if not value or not value.strip():
                raise ValueError(f"{name} namespace must be a non-empty string")


@dataclass(frozen=True, slots=True)
class PipelineCacheSettings:
    namespaces: CacheNamespaces
    default_ttl: int
    index_separator: str

    def __post_init__(self) -> None:
        if self.default_ttl <= 0:
            raise ValueError("default_ttl must be greater than zero")
        if not self.index_separator:
            raise ValueError("index_separator must be a non-empty string")


@dataclass(frozen=True, slots=True)
class RedisStoreSettings:
    redis_url: str
    key_prefix: str
    default_ttl: int
    idle_connection_ttl_sec: int
    idle_sweep_interval_sec: int
    separator: str = ":::"

    def __post_init__(self) -> None:
        if not self.redis_url:
            raise ValueError("redis_url must be a non-empty string")
        if self.default_ttl <= 0:
            raise ValueError("default_ttl must be greater than zero")
        if self.idle_connection_ttl_sec <= 0:
            raise ValueError("idle_connection_ttl_sec must be greater than zero")
        if self.idle_sweep_interval_sec <= 0:
            raise ValueError("idle_sweep_interval_sec must be greater than zero")
        if not self.separator:
            raise ValueError("separator must be a non-empty string")
