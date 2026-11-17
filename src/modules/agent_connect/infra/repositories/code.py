from __future__ import annotations

from redis.asyncio import Redis

from ...domain.entities import AgentConnectCode
from ...domain.repositories import AgentConnectCodeRepository
from ..mappers import code_to_hash, hash_to_code

_PREFIX = "agent_connect"


class ValkeyAgentConnectCodeRepository(AgentConnectCodeRepository):
    """Keeps connection requests in Valkey.

    ``agent_connect:code:<digest>`` holds the request as a hash, ``agent_connect:id:<id>`` maps
    the request id to its digest, and ``agent_connect:user:<user_id>`` is the set of digests
    the user created. Expiry is handled by key TTLs; the per-user set keeps the longest TTL.
    """

    def __init__(self, redis: Redis, *, user_index_ttl_seconds: int) -> None:
        self._redis = redis
        self._user_index_ttl_seconds = user_index_ttl_seconds

    async def get_by_digest(self, code_digest: str) -> AgentConnectCode | None:
        payload = await self._redis.hgetall(_code_key(code_digest))
        return hash_to_code(payload) if payload else None

    async def get_for_user(self, code_id: str, user_id: str) -> AgentConnectCode | None:
        digest = await self._redis.get(_id_key(code_id))
        if not digest:
            return None
        code = await self.get_by_digest(_text(digest))
        return code if code is not None and code.user_id == user_id else None

    async def list_for_user(self, user_id: str) -> list[AgentConnectCode]:
        digests = await self._redis.smembers(_user_key(user_id))
        codes: list[AgentConnectCode] = []
        stale: list[str] = []
        for raw_digest in digests:
            digest = _text(raw_digest)
            code = await self.get_by_digest(digest)
            if code is None:
                stale.append(digest)
            else:
                codes.append(code)
        if stale:
            await self._redis.srem(_user_key(user_id), *stale)
        return codes

    async def save(self, code: AgentConnectCode, *, ttl_seconds: int) -> AgentConnectCode:
        pipe = self._redis.pipeline(transaction=True)
        pipe.hset(_code_key(code.code_digest), mapping=code_to_hash(code))
        pipe.expire(_code_key(code.code_digest), ttl_seconds)
        pipe.set(_id_key(code.id), code.code_digest, ex=ttl_seconds)
        pipe.sadd(_user_key(code.user_id), code.code_digest)
        pipe.expire(_user_key(code.user_id), max(ttl_seconds, self._user_index_ttl_seconds))
        await pipe.execute()
        return code

    async def delete(self, code: AgentConnectCode) -> None:
        pipe = self._redis.pipeline(transaction=True)
        pipe.delete(_code_key(code.code_digest), _id_key(code.id))
        pipe.srem(_user_key(code.user_id), code.code_digest)
        await pipe.execute()


def _code_key(code_digest: str) -> str:
    return f"{_PREFIX}:code:{code_digest}"


def _id_key(code_id: str) -> str:
    return f"{_PREFIX}:id:{code_id}"


def _user_key(user_id: str) -> str:
    return f"{_PREFIX}:user:{user_id}"


def _text(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value
