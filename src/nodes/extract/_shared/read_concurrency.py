"""Concurrent partition query limit of ReadTableFromDBV3/ReadQueryFromDBV3."""

from __future__ import annotations

from sqlalchemy import Engine

from core.db.concurrency import dialect_read_concurrency

from src.logger import logger

import config


def resolve_read_concurrency(max_concurrent_queries: int | None, engine: Engine) -> int | None:
    """Resolve the per-read query limit: node input, then dialect default; ``None`` is unlimited.

    An explicit node value always wins. Otherwise the ``dialect`` policy uses the per-dialect
    default (``DB_READ_CONCURRENCY_<DIALECT>`` overrides it); the ``legacy`` policy and unknown
    dialects keep reads unlimited, bounded only by the consumer's thread pool.
    """
    if max_concurrent_queries is not None:
        limit, source = max_concurrent_queries, "node"
    elif config.OTHER.DB_CONCURRENCY_POLICY == "dialect":
        dialect_name = engine.dialect.name
        limit = dialect_read_concurrency(dialect_name, config.OTHER.DB_READ_CONCURRENCY_OVERRIDES)
        source = f"dialect:{dialect_name}"
    else:
        limit, source = None, "legacy"

    logger.info(f"DB read concurrent queries={limit or 'unlimited'} source={source}")
    return limit
