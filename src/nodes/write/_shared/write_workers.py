"""Write workers (dask threads of the sink) of WriteDataFrameToDBV3/V4, INSERT chunk rows of V3 and
rows per batch of V4."""

from __future__ import annotations

from sqlalchemy import Engine

from core.db.concurrency import (
    dialect_bulk_write_workers,
    dialect_key,
    dialect_write_chunk_rows,
    dialect_write_workers,
)

from src.logger import logger

import config

# Rows per INSERT under the ``legacy`` policy or for an unknown dialect (the former node default).
LEGACY_WRITE_CHUNK_ROWS = 1_000


def resolve_write_workers(project_settings: object, engine: Engine) -> int:
    """Resolve threads for one write: project setting, then dialect default, then legacy.

    ``project_settings.workers_count > 0`` always wins. Otherwise the ``dialect`` policy uses the
    per-dialect default (``DB_WRITE_WORKERS_<DIALECT>`` overrides it); the ``legacy`` policy or
    an unknown dialect uses ``BULK_INSERT_NUM_WORKERS``. The result is capped by
    ``SQL_BULK_INSERT_MAX_WORKERS``.
    """
    project_workers = getattr(project_settings, "workers_count", None) or 0
    requested: int | None = None
    source = "legacy"
    if project_workers > 0:
        requested, source = project_workers, "project"
    elif config.OTHER.DB_CONCURRENCY_POLICY == "dialect":
        dialect_name = engine.dialect.name
        requested = dialect_write_workers(dialect_name, config.OTHER.DB_WRITE_WORKERS_OVERRIDES)
        source = f"dialect:{dialect_name}"
    if requested is None:
        requested, source = config.OTHER.BULK_INSERT_NUM_WORKERS, "legacy"

    workers = max(1, min(requested, config.OTHER.SQL_BULK_INSERT_MAX_WORKERS))
    logger.info(f"DB write workers={workers} source={source} requested={requested}")
    return workers


def resolve_bulk_write_workers(project_settings: object, engine: Engine) -> int | None:
    """Resolve threads for a write through the dialect's bulk path (PostgreSQL COPY), or None.

    ``None`` keeps ``resolve_write_workers`` for the bulk path too: an explicit setting wins, so a
    positive ``project_settings.workers_count``, the ``legacy`` policy and a
    ``DB_WRITE_WORKERS_<DIALECT>`` override all return ``None``, as does a dialect without a bulk
    default. Otherwise the dialect's ``bulk_write_workers`` capped by ``SQL_BULK_INSERT_MAX_WORKERS``.
    The executor uses it only when the target takes the bulk path and it exceeds the write workers.
    """
    dialect_name = engine.dialect.name
    workers: int | None = None
    if (getattr(project_settings, "workers_count", None) or 0) > 0:
        source = "project"
    elif config.OTHER.DB_CONCURRENCY_POLICY != "dialect":
        source = "legacy"
    elif dialect_key(dialect_name) in (config.OTHER.DB_WRITE_WORKERS_OVERRIDES or {}):
        source = f"override:{dialect_name}"
    else:
        source = f"dialect:{dialect_name}"
        bulk = dialect_bulk_write_workers(dialect_name)
        if bulk is not None:
            workers = max(1, min(bulk, config.OTHER.SQL_BULK_INSERT_MAX_WORKERS))
    logger.info(f"DB bulk write workers={workers} source={source}")
    return workers


def resolve_write_chunksize(node_chunksize: int | None, engine: Engine) -> int:
    """Resolve rows per INSERT: explicit node value, then dialect default, then legacy 1000.

    A node ``chunksize`` that is not ``None`` always wins. Otherwise the ``dialect`` policy uses
    the per-dialect ``write_chunk_rows``; the ``legacy`` policy or an unknown dialect uses
    ``LEGACY_WRITE_CHUNK_ROWS``.
    """
    if node_chunksize is not None:
        chunksize, source = node_chunksize, "node"
    else:
        chunksize, source = None, "legacy"
        if config.OTHER.DB_CONCURRENCY_POLICY == "dialect":
            dialect_name = engine.dialect.name
            chunksize, source = dialect_write_chunk_rows(dialect_name), f"dialect:{dialect_name}"
        if chunksize is None:
            chunksize, source = LEGACY_WRITE_CHUNK_ROWS, "legacy"
    logger.info(f"DB write chunksize={chunksize} source={source}")
    return chunksize


def resolve_rows_per_batch(node_rows_per_batch: int | None) -> int | None:
    """Resolve rows per batch of WriteDataFrameToDBV4: explicit node value, else automatic.

    A node ``rows_per_batch`` that is not ``None`` always wins. Otherwise the ``dialect`` policy
    returns ``None``: every write_v4 executor sizes its batches itself (by bytes on the bulk
    paths). The ``legacy`` policy turns that off and uses ``LEGACY_WRITE_CHUNK_ROWS`` on every path.
    """
    if node_rows_per_batch is not None:
        rows, source = node_rows_per_batch, "node"
    elif config.OTHER.DB_CONCURRENCY_POLICY == "dialect":
        rows, source = None, "auto"
    else:
        rows, source = LEGACY_WRITE_CHUNK_ROWS, "legacy"
    logger.info(f"DB write rows_per_batch={rows if rows is not None else 'auto'} source={source}")
    return rows
