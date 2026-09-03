from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext import asyncio as asa

from core.hashing import get_hash


def create_sa_engine_fingerprint(engine: sa.Engine | asa.AsyncEngine) -> str:
    url = engine.url.render_as_string(hide_password=False)
    return f"sa_engine:{get_hash(url).hex()}"


__all__ = ["create_sa_engine_fingerprint"]
