"""Seed benchmark test databases with synthetic rows through each driver's fastest bulk path.

    python -m services.task_benchmarking.seed --db postgres --rows 1000000 --table bench_wide_1m

Data comes from ``synthetic.generate_partition``, so a table seeded with the same ``--rows``,
``--npartitions``, ``--seed`` and ``--schema`` matches what benchmark nodes generate in memory.
The measured rate doubles as the "native write ceiling" reference for each database:

- PostgreSQL: psycopg 3 ``COPY ... FROM STDIN (FORMAT csv)``, CSV encoded by Arrow,
  one transaction per partition.
- ClickHouse: clickhouse-connect ``insert_arrow`` (``--ch-insert df`` uses ``insert_df``),
  partitions are grouped into blocks of at least ``--batch-rows`` rows.
- MSSQL: pyodbc ``fast_executemany`` in batches of ``--batch-rows``, one commit per partition.

Generation and client-side encoding of upcoming partitions (one helper thread, about one driver
call ahead) overlap with loading the current one.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd
import pyarrow as pa
import pyarrow.csv as pa_csv

from . import synthetic

DB_CHOICES = ("postgres", "clickhouse", "mssql")
CH_INSERT_CHOICES = ("arrow", "df")
MSSQL_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"
_CH_DECIMAL_RE = re.compile(r"Decimal\((\d+),\s*(\d+)\)")


@dataclass(frozen=True)
class DbDefaults:
    """Connection defaults; each value can be overridden by ``<env_prefix>_<FIELD>``."""

    env_prefix: str
    port: int
    database: str
    user: str
    password: str
    batch_rows: int


# Host-side defaults match the published ports and credentials of the test databases in
# ``docker/docker-compose.tests.yaml``; inside compose ``DVT_BENCH_*_HOST/PORT`` override them.
DB_DEFAULTS: dict[str, DbDefaults] = {
    "postgres": DbDefaults("DVT_BENCH_PG", 54321, "testdb", "testuser", "testpassword", 100_000),
    "clickhouse": DbDefaults("DVT_BENCH_CH", 8124, "testdb", "testuser", "testpassword", 500_000),
    "mssql": DbDefaults("DVT_BENCH_MSSQL", 11433, "benchdb", "SA", "Str0ngP@ss!", 50_000),
}


@dataclass(frozen=True)
class SeedOptions:
    db: str
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    table: str
    rows: int
    npartitions: int
    seed: int
    schema: str
    recreate: bool
    batch_rows: int
    create_database: bool
    dry_run: bool
    ch_insert: str = "arrow"


class SeedBackend(Protocol):
    """Driver-specific operations used by ``run_seed``.

    ``prepare`` runs in a helper thread and must only do CPU work on the frame; every other
    method runs in the main thread and owns the connection.
    """

    def create_database(self) -> bool: ...

    def connect(self) -> None: ...

    def count_rows(self) -> int | None: ...

    def execute(self, statement: str) -> None: ...

    def prepare(self, frame: pd.DataFrame) -> Any: ...

    def load(self, payload: Any) -> None: ...

    def flush(self) -> None: ...

    def close(self) -> None: ...


@dataclass
class LoadStats:
    prepare_sec: float = 0.0
    load_sec: float = 0.0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.task_benchmarking.seed",
        description="Load synthetic benchmark rows into a test database (idempotent).",
    )
    parser.add_argument("--db", required=True, choices=DB_CHOICES)
    parser.add_argument("--host", help="default: $DVT_BENCH_<PG|CH|MSSQL>_HOST or localhost")
    parser.add_argument("--port", type=int, help="default: $DVT_BENCH_*_PORT or the host port")
    parser.add_argument("--database", help="default: testdb (postgres/clickhouse), benchdb (mssql)")
    parser.add_argument("--user", help="default: testuser (postgres/clickhouse), SA (mssql)")
    password = parser.add_mutually_exclusive_group()
    password.add_argument("--password", help="default: $DVT_BENCH_*_PASSWORD or compose default")
    password.add_argument("--password-env", metavar="ENV_VAR", help="read password from ENV_VAR")
    parser.add_argument("--table", default="bench_wide_5m")
    parser.add_argument("--rows", type=_positive_int, default=5_000_000)
    parser.add_argument("--npartitions", type=_positive_int, default=64)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--schema", choices=synthetic.SCHEMA_NAMES, default="wide_mixed")
    parser.add_argument(
        "--recreate", action="store_true", help="drop and reload even if already seeded"
    )
    parser.add_argument(
        "--batch-rows",
        type=_positive_int,
        help=(
            "rows per driver call: postgres COPY chunk (default 100000), clickhouse minimum "
            "insert block (default 500000), mssql executemany batch (default 50000)"
        ),
    )
    parser.add_argument(
        "--create-database", action="store_true", help="create --database if it is missing"
    )
    parser.add_argument(
        "--ch-insert",
        choices=CH_INSERT_CHOICES,
        default="arrow",
        help="clickhouse-connect insert method (default: arrow)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan and DDL without connecting"
    )
    return parser


def parse_args(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None
) -> SeedOptions:
    parser = build_parser()
    args = parser.parse_args(argv)
    env = os.environ if environ is None else environ
    defaults = DB_DEFAULTS[args.db]
    prefix = defaults.env_prefix

    if args.password is not None:
        password = args.password
    elif args.password_env:
        if args.password_env not in env:
            parser.error(f"environment variable {args.password_env} is not set")
        password = env[args.password_env]
    else:
        password = env.get(f"{prefix}_PASSWORD", defaults.password)

    port = args.port
    if port is None:
        raw_port = env.get(f"{prefix}_PORT")
        try:
            port = int(raw_port) if raw_port else defaults.port
        except ValueError:
            parser.error(f"{prefix}_PORT must be an integer, got {raw_port!r}")

    options = SeedOptions(
        db=args.db,
        host=args.host or env.get(f"{prefix}_HOST") or "localhost",
        port=port,
        database=args.database or env.get(f"{prefix}_DATABASE") or defaults.database,
        user=args.user or env.get(f"{prefix}_USER") or defaults.user,
        password=password,
        table=args.table,
        rows=args.rows,
        npartitions=args.npartitions,
        seed=args.seed,
        schema=args.schema,
        recreate=args.recreate,
        batch_rows=args.batch_rows or defaults.batch_rows,
        create_database=args.create_database,
        dry_run=args.dry_run,
        ch_insert=args.ch_insert,
    )
    try:
        synthetic.quote_identifier(args.db, options.table)
        synthetic.quote_identifier(args.db, options.database)
    except ValueError as exc:
        parser.error(str(exc))
    return options


def run_seed(
    options: SeedOptions,
    backend_factory: Callable[[SeedOptions], SeedBackend] | None = None,
) -> int:
    plan = synthetic.partition_plan(options.rows, options.npartitions)
    drop_sql = synthetic.drop_table_sql(options.db, options.table)
    create_sql = synthetic.create_table_sql(options.schema, options.db, options.table)
    target = f"{options.db}.{options.table}"

    if options.dry_run:
        _emit(
            f"dry-run: db={options.db} host={options.host} port={options.port} "
            f"database={options.database} user={options.user} table={options.table} "
            f"schema={options.schema} rows={options.rows} npartitions={len(plan)} "
            f"seed={options.seed} batch={options.batch_rows} recreate={options.recreate} "
            f"create_database={options.create_database}"
        )
        for statement in [drop_sql, *create_sql]:
            _emit(f"{statement};")
        return 0

    backend = (backend_factory or create_backend)(options)
    try:
        if options.create_database:
            created = backend.create_database()
            _emit(f"database {options.database}: {'created' if created else 'already exists'}")
        backend.connect()
        existing = backend.count_rows()
        if existing == options.rows and not options.recreate:
            _emit(
                f"already seeded: {target} in database {options.database} has {existing} rows "
                f"(use --recreate to reload)"
            )
            return 0
        if existing is not None:
            _emit(f"reloading {target}: found {existing} rows, expected {options.rows}")
        backend.execute(drop_sql)
        for statement in create_sql:
            backend.execute(statement)

        started = time.perf_counter()
        stats = _load_partitions(backend, options, plan, started)
        elapsed = time.perf_counter() - started
        rate = options.rows / elapsed if elapsed > 0 else float("inf")
        _emit(
            f"seeded {options.rows} rows into {target} in {elapsed:.2f} s "
            f"({rate:.0f} rows/s, batch={options.batch_rows})"
        )
        _emit(
            f"timing: generate+encode={stats.prepare_sec:.2f} s (overlapped with load), "
            f"load={stats.load_sec:.2f} s"
        )
        count = backend.count_rows()
        status = "ok" if count == options.rows else "MISMATCH"
        _emit(f"verify: COUNT(*) FROM {options.database}.{options.table} = {count} ({status})")
        return 0 if count == options.rows else 1
    finally:
        backend.close()


def _load_partitions(
    backend: SeedBackend,
    options: SeedOptions,
    plan: list[synthetic.PartitionSpec],
    started: float,
) -> LoadStats:
    stats = LoadStats()

    def produce(spec: synthetic.PartitionSpec) -> tuple[Any, float]:
        begin = time.perf_counter()
        frame = synthetic.generate_partition(options.schema, spec, options.seed)
        return backend.prepare(frame), time.perf_counter() - begin

    # Keep one driver call worth of partitions prepared ahead: ClickHouse groups several
    # partitions per insert, so a single-partition lookahead would leave the loader idle.
    depth = max(1, math.ceil(options.batch_rows / max(spec.rows for spec in plan)))
    loaded_rows = 0
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="seed-prepare") as pool:
        pending = deque(pool.submit(produce, spec) for spec in plan[:depth])
        for position, spec in enumerate(plan):
            payload, prepare_sec = pending.popleft().result()
            stats.prepare_sec += prepare_sec
            if position + depth < len(plan):
                pending.append(pool.submit(produce, plan[position + depth]))
            begin = time.perf_counter()
            backend.load(payload)
            if position + 1 == len(plan):
                backend.flush()
            load_sec = time.perf_counter() - begin
            stats.load_sec += load_sec
            loaded_rows += spec.rows
            total = time.perf_counter() - started
            _emit(
                f"[{options.db}] partition {position + 1}/{len(plan)} "
                f"ids {spec.id_offset}..{spec.id_offset + spec.rows - 1} rows={spec.rows} "
                f"load={load_sec:.2f}s total={total:.1f}s "
                f"({loaded_rows / total if total > 0 else 0:.0f} rows/s)"
            )
    return stats


def create_backend(options: SeedOptions) -> SeedBackend:
    backends: dict[str, Callable[[SeedOptions], SeedBackend]] = {
        "postgres": PostgresBackend,
        "clickhouse": ClickHouseBackend,
        "mssql": MssqlBackend,
    }
    return backends[options.db](options)


class PostgresBackend:
    def __init__(self, options: SeedOptions) -> None:
        self._options = options
        self._conn: Any = None
        self._table = synthetic.qualified_table_name("postgres", options.table)
        column_list = ", ".join(
            synthetic.quote_identifier("postgres", name)
            for name in synthetic.column_names(options.schema)
        )
        self._copy_sql = f"COPY {self._table} ({column_list}) FROM STDIN (FORMAT csv)"
        self._date_columns = [
            column.name
            for column in synthetic.columns(options.schema)
            if column.sql_type("postgres") == "DATE"
        ]

    def create_database(self) -> bool:
        with self._open("postgres") as conn:
            name = self._options.database
            if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                return False
            conn.execute(f"CREATE DATABASE {synthetic.quote_identifier('postgres', name)}")
            return True

    def connect(self) -> None:
        self._conn = self._open(self._options.database)

    def count_rows(self) -> int | None:
        if self._conn.execute("SELECT to_regclass(%s)", (self._table,)).fetchone()[0] is None:
            return None
        return int(self._conn.execute(f"SELECT COUNT(*) FROM {self._table}").fetchone()[0])

    def execute(self, statement: str) -> None:
        self._conn.execute(statement)

    def prepare(self, frame: pd.DataFrame) -> list[bytes]:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        for name in self._date_columns:
            index = table.schema.get_field_index(name)
            table = table.set_column(index, name, table.column(index).cast(pa.date32()))
        # Arrow quotes every string and writes NULL as an unquoted empty field, which is
        # exactly PostgreSQL CSV NULL semantics; it encodes ~5x faster than DataFrame.to_csv.
        write_options = pa_csv.WriteOptions(include_header=False)
        chunks = []
        for start in range(0, max(table.num_rows, 1), self._options.batch_rows):
            sink = pa.BufferOutputStream()
            pa_csv.write_csv(table.slice(start, self._options.batch_rows), sink, write_options)
            chunks.append(sink.getvalue().to_pybytes())
        return chunks

    def load(self, payload: list[bytes]) -> None:
        with (
            self._conn.transaction(),
            self._conn.cursor() as cursor,
            cursor.copy(self._copy_sql) as copy,
        ):
            for chunk in payload:
                copy.write(chunk)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def _open(self, dbname: str) -> Any:
        import psycopg

        options = self._options
        return psycopg.connect(
            host=options.host,
            port=options.port,
            dbname=dbname,
            user=options.user,
            password=options.password,
            autocommit=True,
            connect_timeout=15,
        )


class ClickHouseBackend:
    def __init__(self, options: SeedOptions) -> None:
        self._options = options
        self._client: Any = None
        self._buffer: list[Any] = []
        self._buffered_rows = 0
        self._table = synthetic.qualified_table_name("clickhouse", options.table)
        # ClickHouse truncates when it casts Arrow float64 into Decimal (76577.65 -> 76577.64),
        # so decimal columns are rounded client-side by Arrow's float -> decimal128 cast.
        self._decimal_types: dict[str, pa.DataType] = {}
        for column in synthetic.columns(options.schema):
            match = _CH_DECIMAL_RE.fullmatch(column.sql_type("clickhouse"))
            if match:
                precision, scale = (int(group) for group in match.groups())
                self._decimal_types[column.name] = pa.decimal128(precision, scale)

    def create_database(self) -> bool:
        client = self._open(None)
        try:
            name = self._options.database
            if int(client.command(f"EXISTS DATABASE {self._quote(name)}")):
                return False
            client.command(f"CREATE DATABASE {self._quote(name)}")
            return True
        finally:
            client.close()

    def connect(self) -> None:
        self._warn_env_proxy()
        self._client = self._open(self._options.database)

    def count_rows(self) -> int | None:
        if not int(self._client.command(f"EXISTS TABLE {self._table}")):
            return None
        return int(self._client.command(f"SELECT count() FROM {self._table}"))

    def execute(self, statement: str) -> None:
        self._client.command(statement)

    def prepare(self, frame: pd.DataFrame) -> Any:
        if self._options.ch_insert == "df":
            return frame
        table = pa.Table.from_pandas(frame, preserve_index=False)
        for name, decimal_type in self._decimal_types.items():
            index = table.schema.get_field_index(name)
            table = table.set_column(index, name, table.column(index).cast(decimal_type))
        return table

    def load(self, payload: Any) -> None:
        self._buffer.append(payload)
        self._buffered_rows += len(payload)
        if self._buffered_rows >= self._options.batch_rows:
            self._insert_buffer()

    def flush(self) -> None:
        if self._buffer:
            self._insert_buffer()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def _insert_buffer(self) -> None:
        options = self._options
        if options.ch_insert == "df":
            block = pd.concat(self._buffer, ignore_index=True)
            self._client.insert_df(options.table, block, database=options.database)
        else:
            block = pa.concat_tables(self._buffer)
            self._client.insert_arrow(options.table, block, database=options.database)
        self._buffer = []
        self._buffered_rows = 0

    def _open(self, database: str | None) -> Any:
        import clickhouse_connect

        options = self._options
        return clickhouse_connect.get_client(
            host=options.host,
            port=options.port,
            username=options.user,
            password=options.password,
            database=database or "",
            connect_timeout=15,
        )

    def _warn_env_proxy(self) -> None:
        from clickhouse_connect.driver.httputil import check_env_proxy

        if check_env_proxy("http", self._options.host, self._options.port):
            _emit(
                f"warning: clickhouse-connect will use the HTTP proxy from the environment for "
                f"{self._options.host}:{self._options.port}; if inserts fail with 'Empty query' "
                f"or HTTP 503, set NO_PROXY={self._options.host}"
            )

    @staticmethod
    def _quote(name: str) -> str:
        return synthetic.quote_identifier("clickhouse", name)


class MssqlBackend:
    def __init__(self, options: SeedOptions) -> None:
        self._options = options
        self._conn: Any = None
        self._cursor: Any = None
        self._table = synthetic.qualified_table_name("mssql", options.table)
        specs = synthetic.columns(options.schema)
        column_list = ", ".join(synthetic.quote_identifier("mssql", spec.name) for spec in specs)
        placeholders = ", ".join("?" for _ in specs)
        self._insert_sql = f"INSERT INTO {self._table} ({column_list}) VALUES ({placeholders})"
        self._date_columns = {spec.name for spec in specs if spec.sql_type("mssql") == "DATE"}

    def create_database(self) -> bool:
        conn = self._open("master", autocommit=True)
        try:
            name = self._options.database
            if conn.execute("SELECT DB_ID(?)", name).fetchone()[0] is not None:
                return False
            conn.execute(f"CREATE DATABASE {synthetic.quote_identifier('mssql', name)}")
            return True
        finally:
            conn.close()

    def connect(self) -> None:
        self._conn = self._open(self._options.database, autocommit=False)
        self._cursor = self._conn.cursor()
        self._cursor.fast_executemany = True

    def count_rows(self) -> int | None:
        cursor = self._cursor
        try:
            if cursor.execute("SELECT OBJECT_ID(?, N'U')", self._table).fetchone()[0] is None:
                return None
            return int(cursor.execute(f"SELECT COUNT_BIG(*) FROM {self._table}").fetchone()[0])
        finally:
            self._conn.commit()

    def execute(self, statement: str) -> None:
        self._cursor.execute(statement)
        self._conn.commit()

    def prepare(self, frame: pd.DataFrame) -> list[list[tuple[Any, ...]]]:
        values = []
        for name in frame.columns:
            series = frame[name]
            if name in self._date_columns:
                values.append(list(series.dt.date))
            elif pd.api.types.is_datetime64_any_dtype(series.dtype):
                values.append(list(series.dt.to_pydatetime()))
            else:
                values.append(series.to_numpy(dtype=object, na_value=None).tolist())
        rows = list(zip(*values, strict=True))
        size = self._options.batch_rows
        return [rows[start : start + size] for start in range(0, len(rows), size)]

    def load(self, payload: list[list[tuple[Any, ...]]]) -> None:
        try:
            for batch in payload:
                self._cursor.executemany(self._insert_sql, batch)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def flush(self) -> None:
        return None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def _open(self, database: str, *, autocommit: bool) -> Any:
        import pyodbc

        options = self._options
        connection_string = ";".join(
            [
                f"DRIVER={{{MSSQL_ODBC_DRIVER}}}",
                f"SERVER={options.host},{options.port}",
                f"DATABASE={_odbc_braced(database)}",
                f"UID={_odbc_braced(options.user)}",
                f"PWD={_odbc_braced(options.password)}",
                "Encrypt=yes",
                "TrustServerCertificate=yes",
            ]
        )
        return pyodbc.connect(connection_string, autocommit=autocommit, timeout=15)


def _odbc_braced(value: str) -> str:
    return "{" + value.replace("}", "}}") + "}"


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return value


def _emit(message: str) -> None:
    print(message, flush=True)  # noqa: T201 - CLI progress output


def main(argv: Sequence[str] | None = None) -> int:
    return run_seed(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
