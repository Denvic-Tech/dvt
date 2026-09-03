from typing import Any, Optional

import orjson

import sqlalchemy as sa

from .protocol import CacheEngine


class SAEngineCacheEngine(CacheEngine[sa.Engine]):
    """
    Универсальный движок для sqlalchemy.Engine.
    """
    name = "simple-sqlalchemy-v1"

    def can_handle(self, obj: Any) -> bool:
        return isinstance(obj, sa.Engine)

    def dump(self, obj: sa.Engine) -> tuple[bytes, Optional[dict]]:
        url = obj.url

        payload = {
            "drivername": url.drivername,
            "username": url.username,
            "password": url.password,
            "host": url.host,
            "port": url.port,
            "database": url.database,
            "query": url.query,
        }

        return orjson.dumps(payload), None

    def load(
            self,
            data: bytes,
            *,
            meta: Optional[dict] = None
    ):

        url_object = sa.URL.create(**orjson.loads(data))
        return sa.create_engine(url_object)
