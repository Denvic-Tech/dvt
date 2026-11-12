"""Per-dialect DB concurrency defaults shared by write_v3/write_v4 and read_v3.

Values come from Linux container measurements. Oracle (and MySQL reads) are not
measured yet. psycopg writes and pyodbc reads slow down with more dask threads (GIL convoy);
ClickHouse over HTTP and server-compile-bound MSSQL writes speed up.

``bulk_write_workers`` is the default of a write that goes through the dialect's bulk path (write_v4
PostgreSQL ``COPY FROM STDIN``, ``core/db/write_v4/executors/pg.py``); the executor applies it only
when the target takes that path. PostgreSQL: the server does the per-row work of COPY, so more
connections keep it busy (Linux container, wide_mixed pipeline, rows/s at 1/2/4/8 threads: 1M
203k/360k/380-541k/256-695k, 5M 230k/394k/648-703k/399k-1018k; 8 is unstable), hence 4. Its
``write_workers`` stays 1 for executemany (write_v3, write_v4 without COPY): per-value Python work
convoys on the GIL (1M: 28 957 rows/s at 1 thread, 6 652 at 4).

MSSQL bulk path (write_v4 pyodbc ``fast_executemany``, ``core/db/write_v4/executors/mssql.py``)
keeps ``write_workers`` 8, so it has no ``bulk_write_workers``: wide_mixed 5M rows/s at 1/2/4/8
threads 99 779/176 405/320 706/427 249 (SQLAlchemy INSERT at 8: 9 461), no deadlocks or lock
escalations. The MySQL bulk path (PyMySQL ``executemany`` in one transaction per partition,
``executors/mysql.py``) keeps ``write_workers`` 4 as well: 5M rows/s at 1/2/4/8 threads
57 706/93 217/96 487/97 616 (SQLAlchemy INSERT at 4: 44 766); literal rendering in PyMySQL holds
the GIL, so 8 threads only add memory.

``write_chunk_rows`` is the INSERT batch of one write when the node sets no ``chunksize``.
ClickHouse gets large synchronous blocks: at 1000 rows per INSERT the per-request server wait
dominated. Other dialects keep 1000. The MSSQL bulk path raises any smaller ``chunksize`` to its
own floor of 10 000 rows per ``executemany`` call (5M rows/s at 1000/5000/10 000/20 000 rows per
call: 341 139/416 453/430 183/413 348), so write_v3 and the INSERT path keep 1000. The MySQL
bulk path does the same with 10 000: next to the server it is flat (5M rows/s at
1000/5000/20 000: 93 007/96 544/93 283), but every statement is a round trip, so over a slower
network (Windows host to Docker Desktop, 1M) 1000 rows per call gave 58 647 rows/s and the
floor 82 257-85 267.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class DialectConcurrency:
    # Dask threads of one write (``num_workers`` of the sink compute).
    write_workers: int
    # Partition queries of one read node running at the same time.
    read_queries: int
    # Rows per INSERT of one write when the node sets no ``chunksize``.
    write_chunk_rows: int = 1_000
    # Dask threads of one write through the dialect's bulk path (PostgreSQL COPY); ``None``: none.
    bulk_write_workers: int | None = None


DIALECT_CONCURRENCY: dict[str, DialectConcurrency] = {
    "postgresql": DialectConcurrency(
        write_workers=1, read_queries=2, write_chunk_rows=1_000, bulk_write_workers=4
    ),
    "mssql": DialectConcurrency(write_workers=8, read_queries=1, write_chunk_rows=1_000),
    "mysql": DialectConcurrency(write_workers=4, read_queries=2, write_chunk_rows=1_000),
    "sqlite": DialectConcurrency(write_workers=1, read_queries=1, write_chunk_rows=1_000),
    "clickhouse": DialectConcurrency(write_workers=8, read_queries=4, write_chunk_rows=100_000),
    "oracle": DialectConcurrency(write_workers=8, read_queries=2, write_chunk_rows=1_000),
}


# Substring markers of ``engine.dialect.name`` in the order of read_v3/write_v4 ``resolve_dialect``.
_DIALECT_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("clickhouse", ("clickhouse",)),
    ("postgresql", ("postgres",)),
    ("mysql", ("mysql", "mariadb")),
    ("mssql", ("mssql", "sqlserver")),
    ("oracle", ("oracle",)),
    ("sqlite", ("sqlite",)),
)


def dialect_key(dialect_name: str | None) -> str | None:
    """Map ``engine.dialect.name`` to a ``DIALECT_CONCURRENCY`` key; MariaDB uses ``mysql``."""
    name = (dialect_name or "").lower()
    for key, markers in _DIALECT_MARKERS:
        if any(marker in name for marker in markers):
            return key
    return None


def dialect_write_workers(
    dialect_name: str | None,
    overrides: Mapping[str, int] | None = None,
) -> int | None:
    """Default write workers of a dialect; ``overrides`` win; ``None`` for an unknown dialect."""
    key = dialect_key(dialect_name)
    if key is None:
        return None
    if overrides and key in overrides:
        return overrides[key]
    return DIALECT_CONCURRENCY[key].write_workers


def dialect_bulk_write_workers(dialect_name: str | None) -> int | None:
    """Default write workers of the dialect's bulk path; ``None`` without one or if unknown."""
    key = dialect_key(dialect_name)
    if key is None:
        return None
    return DIALECT_CONCURRENCY[key].bulk_write_workers


def dialect_read_concurrency(
    dialect_name: str | None,
    overrides: Mapping[str, int] | None = None,
) -> int | None:
    """Default concurrent read queries of a dialect; ``overrides`` win; ``None`` if unknown."""
    key = dialect_key(dialect_name)
    if key is None:
        return None
    if overrides and key in overrides:
        return overrides[key]
    return DIALECT_CONCURRENCY[key].read_queries


def dialect_write_chunk_rows(dialect_name: str | None) -> int | None:
    """Default rows per INSERT of a dialect; ``None`` for an unknown dialect."""
    key = dialect_key(dialect_name)
    if key is None:
        return None
    return DIALECT_CONCURRENCY[key].write_chunk_rows
