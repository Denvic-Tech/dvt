from typing import Any, AsyncGenerator

from redis.asyncio import Redis, ConnectionPool

import config


def _build_redis_url() -> str:
    auth = f":{config.VALKEY.VALKEY_PASSWORD}@" if config.VALKEY.VALKEY_PASSWORD else ""
    return f"redis://{auth}{config.VALKEY.VALKEY_HOST}:{config.VALKEY.VALKEY_PORT}/{config.VALKEY.VALKEY_DB}"

_pool = ConnectionPool.from_url(
    _build_redis_url(),
    decode_responses=False,
    max_connections=512,
    socket_timeout=5,
)

async def get_redis() -> AsyncGenerator[Any, Any]:
    redis = await Redis.from_url(
        _build_redis_url(),
        decode_responses=True,
        max_connections=10,
        socket_timeout=5,
        socket_connect_timeout=5,
        retry_on_timeout=True
    )
    try:
        yield redis
    finally:
        await redis.aclose()


async def get_redis_bytes() -> AsyncGenerator[Redis, None]:
    # Создаем клиент, использующий этот глобальный пул
    # Это происходит мгновенно, без создания новых сокетов
    redis = Redis(connection_pool=_pool)
    try:
        yield redis
    finally:
        # ВАЖНО: НЕ вызываем aclose(), иначе закроем весь пул для всех!
        # Просто выходим, клиент сам вернет соединение в пул.
        pass