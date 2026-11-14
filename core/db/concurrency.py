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

``write_chunk_rows`` is the INSERT batch of one write_v3 write when the node sets no
``chunksize``. ClickHouse gets large synchronous blocks: at 1000 rows per INSERT the per-request
server wait dominated. Other dialects keep 1000.

write_v4 does not use it: WriteDataFrameToDBV4 ignores the node ``chunksize`` and, without
``rows_per_batch``, sizes the batches of every partition by bytes over its estimated row width
(``core/db/write_v4/batching.py``; under the ``legacy`` policy 1000 rows). Each executor keeps its
target next to its code. Linux container, write seconds / peak RSS MiB at rows per batch; row
widths by the estimate: numeric 16 B, wide_mixed 198 B, wide_text 8.2 KB (4 strings of 2048
chars, two of them object columns):

- ClickHouse INSERT (8 threads), 16 MB and at most 1 000 000 rows: numeric 20M, 100k/250k/500k/
  1M/2.5M rows 0.81/0.70/0.64/0.72/0.71 s, RSS 1002/1038/1098/1201/1507; wide_mixed 5M in 8
  partitions, 25k/50k/100k/200k/625k 2.06/1.83/1.56/1.48/2.19 s, RSS 2305/2359/2465/2723/4319;
  wide_text 160k, 500/1000/2000/4000/8000/20 000 4.73/2.84/2.65/2.72/2.37/6.48 s, RSS
  1775/1910/2038/2669/3526/6171. 16 MB gives wide rows about 2000 rows per INSERT and
  wide_mixed about 85 000 (the former 100 000-row default); larger targets mostly add memory.
- PostgreSQL COPY CSV buffer (4 threads), 4 MB of Arrow data: wide_mixed 5M in 64 partitions,
  1000/10 000/78 125 rows 20.7/16.7/22.9 s (runs vary more than that: 13.8 s at 1000 in another
  run), RSS 540/582/761; wide_text 500/2000/20 000 rows (4/16/164 MB) 18.1/14.8/18.1 s, RSS
  2027/2246/3333.
- SQL Server ``executemany`` call (8 threads), 8 MB of parameter buffers or estimated values,
  whichever is larger, and at most 10 000 rows: wide_mixed (840 B/row of buffers) 5000/10 000/
  20 000/40 000/78 125 rows 20.8/15.4/17.1/17.3/17.7 s, RSS 1047/1078/1152/1301/1562; numeric
  (64 B/row) 10k/50k/125k/625k 9.75/10.43/9.60/10.96 s, RSS 862/906/984/1432, hence the row cap;
  wide_text (nvarchar(max) is streamed: 96 B/row of buffers) 1000/5000/20 000 rows 31.9/53.9/
  53.7 s, RSS 2377/2891/4811, hence the values.
  Earlier, 5M wide_mixed rows/s at 1000/5000/10 000/20 000 rows per call: 341 139/416 453/
  430 183/413 348; the former floor of 10 000 is gone, so the ``legacy`` 1000 rows apply as is.
- MySQL ``executemany`` call (4 threads), 16 MB of estimated values and at most 10 000 rows:
  PyMySQL streams a call as statements of at most 4 MB, so next to the server rows per call
  barely matter (wide_mixed 1000/10 000/78 125 rows 53.8/51.7/51.2 s, RSS 761/767/835; numeric
  10k/100k/625k 14.0/14.4/14.0 s, RSS 587/691/838, hence the row cap); a call ends with a partial
  statement, and over a slower network (Windows host to Docker Desktop, 1M wide_mixed) 1000 rows
  per call gave 58 647 rows/s, 10 000 rows 82 257-85 267. wide_text is bound by the server's
  disk (about 50 KB written per row, the long columns go to their own pages): alternating runs at
  10 000 rows per call took 394/221/1337 s and at the automatic ~2000 rows 568/747/880 s, both
  at ~120 rows/s once the disk slowed, RSS 1359-1371 MiB either way.
- SQLAlchemy INSERT (other dialects and fallbacks) keeps 1000 rows: per-row Python work dominates,
  larger batches only cost memory (PostgreSQL executemany at 1000/20 000/100 000 rows 14.6k-14.9k
  rows/s, RSS 814/1079/1667 MiB; SQL Server 8.6k rows/s at 1000, 7.1k at 20 000).
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
    # Rows per INSERT of one write_v3 write when the node sets no ``chunksize``.
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
