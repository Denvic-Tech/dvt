"""Profile one write_v4 partition on the production write path (measurement only).

    NO_PROXY=localhost,127.0.0.1 PYTHONPATH=. .venv/Scripts/python.exe \\
        -m services.task_benchmarking.profile_write --db postgres --chunksize 1000

One partition of ``synthetic.generate_partition`` (default 62 500 rows = 1M / 16 partitions) is
wrapped in ``dd.from_pandas(npartitions=1)`` and written by ``core.db.write_v4.write_dataframe``
in append mode with ``write_workers=1``: the partition goes through ``_PartitionWriteCallable``
and ``compute(scheduler="sync")`` exactly as ``WriteDataFrameToDBV4`` runs it on one thread.
The connection record comes from ``BenchmarkSqlConnection`` and the engine from
``resolve_sql_engine`` (as in the node); the table is recreated with ``BenchmarkEnsureTable``
before every run and ``COUNT(*)`` is verified after it.

Phases, all in one process (artifacts in ``--out``):

1. ``--warmup`` + ``--repeat`` plain runs: wall and process CPU of the whole write and of the
   partition callable; nothing else is instrumented.
2. One instrumented run: ``perf_counter``/``thread_time`` wrappers around chunk-level calls only
   (``to_dict``, ``Connection.execute``, dialect ``do_execute*``/``do_commit``,
   ``client.insert``, ...). Each call is booked under its actual call path, so nested calls never
   double count. DBAPI calls and ClickHouse inserts are captured for phase 4.
3. One cProfile run of the whole write: ``profile.prof`` and pstats dumps. Partition stages are
   attributed on the difference of two stats snapshots taken at partition start and end, so they
   exclude setup work (planning, reflection, connection establishment).
4. Driver only: the captured DBAPI calls / ``client.insert`` calls are replayed on a raw
   connection of the same engine with the same SQL and parameter objects (commit per chunk),
   i.e. no DVT normalization, ``to_dict`` or SQLAlchemy processing in the timed region.

PostgreSQL over psycopg 3 takes the ``COPY ... FROM STDIN`` path of ``PostgresWriteExecutor``
unless ``DB_PG_COPY=false`` (the node passes ``config.OTHER.DB_PG_COPY`` the same way); its
replay sends the captured COPY statement and CSV buffers with one commit per partition. Likewise
SQL Server over pyodbc takes ``MssqlWriteExecutor`` (``fast_executemany`` with declared
parameters) unless ``DB_MSSQL_FAST_EXECUTEMANY=false`` and MySQL over PyMySQL takes
``MysqlWriteExecutor`` (raw ``executemany``, one transaction per partition) unless
``DB_MYSQL_BULK_INSERT=false``; their replay repeats the captured cursor calls (declarations,
``max_stmt_length``, row tuples) with one commit per partition.

Windows note: ``thread_time``/``process_time`` advance in 15.6 ms ticks, so CPU columns of
short stages are sampled estimates; whole-run CPU is exact enough.
"""

from __future__ import annotations

import argparse
import cProfile
import functools
import inspect
import io
import json
import os
import platform
import pstats
import re
import statistics
import sys
import sysconfig
import time
from collections import defaultdict
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from . import seed, synthetic

DB_CHOICES = ("clickhouse", "postgres", "mssql", "mysql")
DEFAULT_ROWS = 62_500
DEFAULT_TABLE = "bench_profile_wide"
PROFILE_ROOT = Path("tmp") / "task_benchmarking" / "profiles"
PSTATS_TOP = 40
SUMMARY_TOP = 10
REPO_ROOT = Path(__file__).resolve().parents[2]
DB_DEFAULTS: dict[str, seed.DbDefaults] = {
    **seed.DB_DEFAULTS,
    # Host port and credentials of ``mysql_test_db`` in docker/docker-compose.tests.yaml;
    # ``batch_rows`` is a seeder setting and is unused here.
    "mysql": seed.DbDefaults("DVT_BENCH_MYSQL", 33061, "testdb", "testuser", "testpassword", 0),
}
_NODE_IDS = {"user_id": "profile-write", "project_id": "profile-write", "task_id": "profile-write"}
_MISSING = object()

FuncKey = tuple[str, int, str]
# pstats layout: {func: (primitive calls, total calls, tottime, cumtime, {caller: edge})},
# where edge = (total calls, primitive calls, tottime, cumtime) of calls made by ``caller``.
StatsDict = Mapping[FuncKey, tuple[int, int, float, float, Mapping[FuncKey, tuple]]]


@dataclass(frozen=True)
class ProfileOptions:
    db: str
    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False)
    out: Path
    table: str = DEFAULT_TABLE
    rows: int = DEFAULT_ROWS
    chunksize: int | None = None
    repeat: int = 3
    warmup: int = 1
    seed: int = 42
    schema: str = "wide_mixed"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.task_benchmarking.profile_write",
        description="Profile one write_v4 partition (WriteDataFrameToDBV4 path, one thread).",
    )
    parser.add_argument("--db", required=True, choices=DB_CHOICES)
    parser.add_argument("--rows", type=seed._positive_int, default=DEFAULT_ROWS)
    parser.add_argument(
        "--chunksize",
        type=seed._positive_int,
        default=None,
        help="WriteRequest.rows_per_batch; omitted: automatic, as the node",
    )
    parser.add_argument("--repeat", type=seed._positive_int, default=3, help="plain timed runs")
    parser.add_argument(
        "--warmup", type=_non_negative_int, default=1, help="untimed runs before --repeat"
    )
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--schema", choices=synthetic.SCHEMA_NAMES, default="wide_mixed")
    parser.add_argument(
        "--out", type=Path, help=f"default: {PROFILE_ROOT.as_posix()}/<timestamp>_<db>"
    )
    parser.add_argument("--host", help="default: $DVT_BENCH_<PG|CH|MSSQL|MYSQL>_HOST or localhost")
    parser.add_argument("--port", type=int, help="default: $DVT_BENCH_*_PORT or the host port")
    parser.add_argument("--database", help="default: $DVT_BENCH_*_DATABASE or compose default")
    parser.add_argument("--user", help="default: $DVT_BENCH_*_USER or compose default")
    password = parser.add_mutually_exclusive_group()
    password.add_argument("--password", help="default: $DVT_BENCH_*_PASSWORD or compose default")
    password.add_argument("--password-env", metavar="ENV_VAR", help="read password from ENV_VAR")
    return parser


def parse_args(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> ProfileOptions:
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

    stamp = (now or datetime.now()).strftime("%Y-%m-%dT%H-%M-%S")
    options = ProfileOptions(
        db=args.db,
        host=args.host or env.get(f"{prefix}_HOST") or "localhost",
        port=port,
        database=args.database or env.get(f"{prefix}_DATABASE") or defaults.database,
        user=args.user or env.get(f"{prefix}_USER") or defaults.user,
        password=password,
        out=args.out or PROFILE_ROOT / f"{stamp}_{args.db}",
        table=args.table,
        rows=args.rows,
        chunksize=args.chunksize,
        repeat=args.repeat,
        warmup=args.warmup,
        seed=args.seed,
        schema=args.schema,
    )
    try:
        synthetic.quote_identifier(args.db, options.table)
    except ValueError as exc:
        parser.error(str(exc))
    return options


# ---------------------------------------------------------------------------------------------
# Profile helpers (pure, unit tested)
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Stage:
    """A profile stage: functions matching ``targets`` (regexes over ``func_label``).

    With ``callers`` only the time of calls made directly from a matching caller counts (pstats
    caller edges). ``parent`` names the enclosing stage; exclusive time is the stage's cumulative
    time minus the cumulative time of its child stages, so overlapping cProfile cumulative times
    are never added twice. Children must run strictly inside their parent. A stage with
    ``subtract=False`` is informational: it is shown under its parent but not subtracted from
    the parent's exclusive time (used when cProfile edges cannot isolate it exactly).
    """

    name: str
    targets: tuple[str, ...]
    callers: tuple[str, ...] = ()
    parent: str | None = None
    subtract: bool = True


def func_label(key: FuncKey) -> str:
    filename, lineno, name = key
    return f"{filename}:{lineno}({name})"


def code_pattern(func: Callable[..., Any]) -> str:
    """Exact-match pattern for the pstats key of ``func`` (decorators and methods unwrapped)."""
    target = inspect.unwrap(func)
    target = getattr(target, "__func__", target)
    code = target.__code__
    return re.escape(func_label((code.co_filename, code.co_firstlineno, code.co_name)))


def nested_code_pattern(func: Callable[..., Any], name: str) -> str:
    """Pattern for a function defined inside ``func`` (for example a returned generator)."""
    target = inspect.unwrap(func)
    target = getattr(target, "__func__", target)
    for const in target.__code__.co_consts:
        if inspect.iscode(const) and const.co_name == name:
            return re.escape(func_label((const.co_filename, const.co_firstlineno, const.co_name)))
    raise LookupError(f"{func!r} defines no nested function {name!r}")


def builtin_pattern(name: str) -> str:
    """Pattern for a C function as cProfile labels it, e.g. ``<built-in method select.select>``."""
    return re.escape(func_label(("~", 0, name)))


def attribute_stages(stats: StatsDict, stages: Sequence[Stage], *, rows: int) -> list[dict]:
    """Cumulative and exclusive time per stage; the first stage is the root (100%)."""
    names = [stage.name for stage in stages]
    if len(set(names)) != len(names):
        raise ValueError("stage names must be unique")
    known = set(names)
    for stage in stages[1:]:
        if stage.parent not in known:
            raise ValueError(f"stage {stage.name!r} has unknown parent {stage.parent!r}")

    labels = {key: func_label(key) for key in stats}

    def matching(patterns: Sequence[str]) -> set[FuncKey]:
        compiled = [re.compile(pattern) for pattern in patterns]
        return {key for key, label in labels.items() if any(p.fullmatch(label) for p in compiled)}

    measured: dict[str, tuple[int, float]] = {}
    for stage in stages:
        caller_keys = matching(stage.callers) if stage.callers else None
        calls, cumulative = 0, 0.0
        for key in matching(stage.targets):
            _primitive, total_calls, _tottime, cumtime, callers = stats[key]
            if caller_keys is None:
                calls += total_calls
                cumulative += cumtime
                continue
            for caller, edge in callers.items():
                if caller in caller_keys:
                    calls += edge[0]
                    cumulative += edge[3]
        measured[stage.name] = (calls, cumulative)

    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, str | None] = {}
    for stage in stages:
        parents[stage.name] = stage.parent
        if stage.parent is not None and stage.subtract:
            children[stage.parent].append(stage.name)

    def depth(name: str) -> int:
        level = 0
        while parents[name] is not None:
            name = parents[name]
            level += 1
        return level

    root_time = measured[stages[0].name][1]
    result = []
    for stage in stages:
        calls, cumulative = measured[stage.name]
        exclusive = cumulative - sum(measured[child][1] for child in children[stage.name])
        result.append(
            {
                "stage": stage.name if stage.subtract else f"[info] {stage.name}",
                "depth": depth(stage.name),
                "calls": calls,
                "cumulative_s": cumulative,
                "exclusive_s": exclusive,
                "pct_of_root": 100.0 * cumulative / root_time if root_time > 0 else 0.0,
                "rows_per_s": rows / cumulative if cumulative > 0 else None,
            }
        )
    return result


def diff_stats(after: StatsDict, before: StatsDict) -> dict:
    """Stats of the calls that completed between two snapshots of the same profiler."""
    result: dict = {}
    for key, (primitive, total, tottime, cumtime, callers) in after.items():
        previous = before.get(key)
        if previous is None:
            result[key] = (primitive, total, tottime, cumtime, dict(callers))
            continue
        b_primitive, b_total, b_tottime, b_cumtime, b_callers = previous
        if total == b_total:
            continue
        edges = {}
        for caller, edge in callers.items():
            b_edge = b_callers.get(caller)
            delta = (
                edge if b_edge is None else tuple(x - y for x, y in zip(edge, b_edge, strict=True))
            )
            if delta[0] > 0:
                edges[caller] = delta
        result[key] = (
            primitive - b_primitive,
            total - b_total,
            tottime - b_tottime,
            cumtime - b_cumtime,
            edges,
        )
    return result


def instrumented_rows(totals: Mapping[str, Sequence[float]], *, rows: int) -> list[dict]:
    """Tree rows from ``StageClock.totals`` (``path -> [calls, wall, cpu]``), root = partition."""
    children: dict[str, list[str]] = defaultdict(list)
    for path in totals:
        if "/" in path:
            children[path.rsplit("/", 1)[0]].append(path)
    roots = [path for path in totals if "/" not in path]
    if not roots:
        return []
    root_wall = sum(totals[path][1] for path in roots)
    result: list[dict] = []

    def visit(path: str, depth: int) -> None:
        calls, wall, cpu = totals[path]
        kids = sorted(children.get(path, []), key=lambda child: -totals[child][1])
        result.append(
            {
                "stage": path.rsplit("/", 1)[-1],
                "path": path,
                "depth": depth,
                "calls": int(calls),
                "wall_s": wall,
                "cpu_s": cpu,
                "blocked_s": wall - cpu,
                "self_wall_s": wall - sum(totals[kid][1] for kid in kids),
                "self_cpu_s": cpu - sum(totals[kid][2] for kid in kids),
                "pct_of_root": 100.0 * wall / root_wall if root_wall > 0 else 0.0,
                "rows_per_s": rows / wall if wall > 0 else None,
            }
        )
        for kid in kids:
            visit(kid, depth + 1)

    for root in roots:
        visit(root, 0)
    return result


# ---------------------------------------------------------------------------------------------
# Lightweight instrumentation
# ---------------------------------------------------------------------------------------------


class StageClock:
    """Wall/thread-CPU totals per call path of wrapped functions; active only in the partition."""

    def __init__(self) -> None:
        self.active = False
        self.totals: dict[str, list[float]] = {}
        self._stack: list[str] = []

    def call(self, name: str, func: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        if not self.active:
            return func(*args, **kwargs)
        self._stack.append(name)
        path = "/".join(self._stack)
        wall0, cpu0 = time.perf_counter(), time.thread_time()
        try:
            return func(*args, **kwargs)
        finally:
            total = self.totals.setdefault(path, [0, 0.0, 0.0])
            total[0] += 1
            total[1] += time.perf_counter() - wall0
            total[2] += time.thread_time() - cpu0
            self._stack.pop()


class Patcher:
    """Temporarily replaces attributes with wrappers; restores them on exit."""

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any]] = []

    def __enter__(self) -> Patcher:
        return self

    def __exit__(self, *exc_info: object) -> None:
        while self._undo:
            owner, attr, original = self._undo.pop()
            if original is _MISSING:
                delattr(owner, attr)
            else:
                setattr(owner, attr, original)

    def wrap(self, owner: Any, attr: str, make: Callable[[Callable], Callable]) -> None:
        static = inspect.getattr_static(owner, attr)
        if isinstance(static, staticmethod):
            replacement: Any = staticmethod(make(static.__func__))
        elif isinstance(static, classmethod):
            replacement = classmethod(make(static.__func__))
        else:
            replacement = make(static)
        self._undo.append((owner, attr, vars(owner).get(attr, _MISSING)))
        setattr(owner, attr, replacement)


def _timed(clock: StageClock, name: str) -> Callable[[Callable], Callable]:
    def make(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return clock.call(name, func, *args, **kwargs)

        return wrapper

    return make


def _timed_generator(clock: StageClock, name: str) -> Callable[[Callable], Callable]:
    """Times every ``next()`` of the generator returned by the wrapped function."""

    def make(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Iterator[Any]:
            generator = func(*args, **kwargs)
            while True:
                try:
                    item = clock.call(name, next, generator)
                except StopIteration:
                    return
                yield item

        return wrapper

    return make


@dataclass
class PartitionProbe:
    """Wraps ``_PartitionWriteCallable.__call__``: partition timing, dtypes, profile snapshots."""

    clock: StageClock
    profiler: cProfile.Profile | None = None
    snapshots: list[dict] = field(default_factory=list)
    calls: int = 0
    rows: int = 0
    wall: float = 0.0
    cpu: float = 0.0
    dtypes: dict[str, str] = field(default_factory=dict)
    index_type: str = ""

    def make(self, func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(writer: Any, pdf: Any) -> Any:
            self.calls += 1
            self.rows += len(pdf)
            if not self.dtypes:
                self.dtypes = {str(name): str(dtype) for name, dtype in pdf.dtypes.items()}
                self.index_type = type(pdf.index).__name__
            self._snapshot()
            self.clock.active = True
            wall0, cpu0 = time.perf_counter(), time.process_time()
            try:
                return self.clock.call("partition", func, writer, pdf)
            finally:
                self.wall += time.perf_counter() - wall0
                self.cpu += time.process_time() - cpu0
                self.clock.active = False
                self._snapshot()

        return wrapper

    def _snapshot(self) -> None:
        if self.profiler is not None:
            self.profiler.snapshot_stats()
            self.snapshots.append(self.profiler.stats)


# ---------------------------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------------------------


@dataclass
class RunResult:
    label: str
    write_wall_s: float
    write_cpu_s: float
    partition_wall_s: float
    partition_cpu_s: float
    partitions: int
    rows_written: int
    count: int


@dataclass
class _Context:
    options: ProfileOptions
    connection: Any
    pdf: Any
    ddf: Any
    request: Any


Installer = Callable[[Patcher, StageClock, Any], None]


def _build_context(options: ProfileOptions) -> _Context:
    import dask.dataframe as dd

    from core.db.write_v4 import (
        ExtraColumnsMode,
        MissingColumnsMode,
        WriteMode,
        WriteRequest,
        WriteTarget,
    )

    from services.task_benchmarking.nodes.benchmark_sql_connection import BenchmarkSqlConnection

    connection = BenchmarkSqlConnection(
        **_NODE_IDS,
        node_id="profile-write-connection",
        connection_type=options.db,
        host=options.host,
        port=options.port,
        database=options.database,
        user=options.user,
        password=options.password,
    ).build_record()
    spec = synthetic.PartitionSpec(index=0, id_offset=0, rows=options.rows)
    pdf = synthetic.generate_partition(options.schema, spec, options.seed)
    import config

    # Same request as WriteDataFrameToDBV4._build_request with the node defaults, one worker.
    request = WriteRequest(
        mode=WriteMode.APPEND,
        target=WriteTarget(table_name=options.table),
        rows_per_batch=options.chunksize,
        write_workers=1,
        # No bulk workers: one thread (``compute(scheduler="sync")``) keeps the partition visible
        # to cProfile, the COPY executor would otherwise run the PostgreSQL bulk default.
        bulk_write_workers=None,
        pg_copy=config.OTHER.DB_PG_COPY,
        mssql_fast_executemany=config.OTHER.DB_MSSQL_FAST_EXECUTEMANY,
        mysql_bulk_insert=config.OTHER.DB_MYSQL_BULK_INSERT,
        on_extra_df_columns=ExtraColumnsMode.IGNORE,
        on_missing_df_columns=MissingColumnsMode.IGNORE_IF_DEFAULT,
    )
    return _Context(options, connection, pdf, dd.from_pandas(pdf, npartitions=1), request)


def _engine(ctx: _Context) -> Any:
    from src.node_dsl.runtime.connections import resolve_sql_engine

    return resolve_sql_engine(ctx.connection)


def _executor_cls(request: Any, engine: Any) -> type:
    """Executor class ``write_dataframe`` resolves for this engine and request switches."""
    from core.db.write_v4.resolver import resolve_executor

    executor = resolve_executor(
        engine,
        pg_copy=request.pg_copy,
        mssql_fast_executemany=request.mssql_fast_executemany,
        mysql_bulk_insert=request.mysql_bulk_insert,
    )
    return type(executor)


def _recreate_table(ctx: _Context) -> None:
    from services.task_benchmarking.nodes.benchmark_ensure_table import BenchmarkEnsureTable

    BenchmarkEnsureTable(
        **_NODE_IDS,
        node_id="profile-write-table",
        connection=ctx.connection,
        table_name=ctx.options.table,
        schema=ctx.options.schema,
        on_exists="recreate",
    )._ensure_table()


def _count_rows(engine: Any, ctx: _Context) -> int:
    table = synthetic.qualified_table_name(ctx.options.db, ctx.options.table)
    with engine.connect() as conn:
        return int(conn.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar())


def _check_count(ctx: _Context, label: str, count: int) -> None:
    if count != ctx.options.rows:
        raise RuntimeError(f"{label}: COUNT(*) = {count}, expected {ctx.options.rows}")


def _write_once(
    ctx: _Context,
    label: str,
    *,
    install: Installer | None = None,
    profiler: cProfile.Profile | None = None,
) -> tuple[RunResult, StageClock, PartitionProbe]:
    from core.db.write_v4 import write_dataframe
    from core.db.write_v4.dask import _PartitionWriteCallable

    _recreate_table(ctx)
    clock = StageClock()
    probe = PartitionProbe(clock, profiler)
    engine = _engine(ctx)
    try:
        with Patcher() as patcher:
            patcher.wrap(_PartitionWriteCallable, "__call__", probe.make)
            if install is not None:
                install(patcher, clock, engine)
            wall0, cpu0 = time.perf_counter(), time.process_time()
            if profiler is not None:
                profiler.enable()
            try:
                result = write_dataframe(ctx.ddf, engine, ctx.request)
            finally:
                if profiler is not None:
                    profiler.disable()
                wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
        count = _count_rows(engine, ctx)
    finally:
        engine.dispose()
    _check_count(ctx, label, count)
    if result.rows_written != ctx.options.rows:
        raise RuntimeError(f"{label}: rows_written = {result.rows_written}")
    run = RunResult(
        label, wall, cpu, probe.wall, probe.cpu, probe.calls, result.rows_written, count
    )
    seed._emit(
        f"[{ctx.options.db} c{ctx.options.chunksize or 'auto'}] {label}: write {wall:.3f} s "
        f"(cpu {cpu:.3f}), partition {probe.wall:.3f} s (cpu {probe.cpu:.3f}), count {count}"
    )
    return run, clock, probe


def _is_insert(statement: str) -> bool:
    return statement.lstrip()[:6].upper() == "INSERT"


def _sql_installer(capture: list[tuple], request: Any) -> Installer:
    def install(patcher: Patcher, clock: StageClock, engine: Any) -> None:
        import pandas as pd
        from sqlalchemy.engine import base

        from core.db.write_v4.executors import sql as sql_executor
        from core.db.write_v4.executors.mssql import MssqlWriteExecutor
        from core.db.write_v4.executors.mysql import MysqlWriteExecutor

        dialect_cls = type(engine.dialect)

        def dbapi(name: str, kind: str) -> Callable[[Callable], Callable]:
            def make(func: Callable) -> Callable:
                @functools.wraps(func)
                def wrapper(dialect, cursor, statement, parameters, context=None):
                    if clock.active and _is_insert(statement):
                        capture.append((kind, statement, parameters))
                    return clock.call(name, func, dialect, cursor, statement, parameters, context)

                return wrapper

            return make

        def commit(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(dialect, dbapi_connection):
                if clock.active:
                    capture.append(("commit", None, None))
                return clock.call("DBAPI commit", func, dialect, dbapi_connection)

            return wrapper

        patcher.wrap(
            sql_executor, "align_partition_to_table", _timed(clock, "align_partition_to_table")
        )
        patcher.wrap(pd.DataFrame, "to_dict", _timed(clock, "DataFrame.to_dict"))
        patcher.wrap(base.Engine, "connect", _timed(clock, "Engine.connect (pool checkout)"))
        patcher.wrap(base.Connection, "execute", _timed(clock, "Connection.execute"))
        patcher.wrap(base.Connection, "close", _timed(clock, "Connection.close (pool checkin)"))
        patcher.wrap(dialect_cls, "do_executemany", dbapi("DBAPI executemany", "executemany"))
        patcher.wrap(dialect_cls, "do_execute", dbapi("DBAPI execute", "execute"))
        patcher.wrap(dialect_cls, "do_commit", commit)
        patcher.wrap(dialect_cls, "do_rollback", _timed(clock, "DBAPI rollback"))
        if engine.dialect.driver == "psycopg":
            _install_pg_copy(patcher, clock, capture)
        executor_cls = _executor_cls(request, engine)
        if executor_cls is MssqlWriteExecutor:
            _install_mssql_fast(patcher, clock, capture)
        elif executor_cls is MysqlWriteExecutor:
            _install_mysql_bulk(patcher, clock, capture)

    return install


def _capture_batch(
    clock: StageClock, capture: list[tuple], name: str, attrs: Callable[[Any, tuple], dict]
) -> Callable[[Callable], Callable]:
    """Times ``_execute_batch(cursor, statement, [declaration,] rows)`` and captures the call for
    replay as ``("bulk_executemany", statement, (cursor attributes, rows))``."""

    def make(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(cursor, statement, *args):
            if clock.active:
                capture.append(("bulk_executemany", statement, (attrs(cursor, args), args[-1])))
            return clock.call(name, func, cursor, statement, *args)

        return wrapper

    return make


def _install_mssql_fast(patcher: Patcher, clock: StageClock, capture: list[tuple]) -> None:
    """Timers of the SQL Server fast_executemany path; captures declarations and row tuples."""
    from core.db.write_v4.executors import mssql as mssql_executor

    def attrs(cursor: Any, args: tuple) -> dict:
        return {"fast_executemany": cursor.fast_executemany, "input_sizes": list(args[0])}

    patcher.wrap(
        mssql_executor, "align_partition_to_table", _timed(clock, "align_partition_to_table")
    )
    patcher.wrap(
        mssql_executor,
        "build_mssql_params",
        _timed(clock, "build_mssql_params (per-column conversion)"),
    )
    patcher.wrap(
        mssql_executor.MssqlWriteExecutor,
        "_execute_batch",
        _capture_batch(clock, capture, "pyodbc setinputsizes + fast executemany", attrs),
    )


def _install_mysql_bulk(patcher: Patcher, clock: StageClock, capture: list[tuple]) -> None:
    """Timers of the MySQL bulk path; captures ``max_stmt_length`` and row tuples."""
    from core.db.write_v4.executors import mysql as mysql_executor

    def attrs(cursor: Any, _args: tuple) -> dict:
        return {"max_stmt_length": cursor.max_stmt_length}

    patcher.wrap(
        mysql_executor, "align_partition_to_table", _timed(clock, "align_partition_to_table")
    )
    patcher.wrap(
        mysql_executor,
        "build_mysql_columns",
        _timed(clock, "build_mysql_columns (per-column values)"),
    )
    patcher.wrap(
        mysql_executor.MysqlWriteExecutor,
        "_execute_batch",
        _capture_batch(clock, capture, "pymysql Cursor.executemany (raw)", attrs),
    )


def _install_pg_copy(patcher: Patcher, clock: StageClock, capture: list[tuple]) -> None:
    """Timers of the PostgreSQL COPY path; captures the COPY statement and CSV buffers."""
    import psycopg

    from core.db.write_v4.executors import pg as pg_executor

    def copy_statement(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(cursor, statement, *args, **kwargs):
            if clock.active:
                capture.append(("copy", str(statement), None))
            return func(cursor, statement, *args, **kwargs)

        return wrapper

    def copy_write(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(copy, buffer):
            if clock.active:
                capture.append(("copy_data", None, bytes(buffer)))
            return clock.call("psycopg Copy.write", func, copy, buffer)

        return wrapper

    patcher.wrap(pg_executor, "align_partition_to_table", _timed(clock, "align_partition_to_table"))
    patcher.wrap(pg_executor, "build_copy_table", _timed(clock, "build_copy_table (Arrow)"))
    patcher.wrap(
        pg_executor, "iter_csv_buffers", _timed_generator(clock, "pyarrow.csv.write_csv buffer")
    )
    patcher.wrap(psycopg.Cursor, "copy", copy_statement)
    patcher.wrap(psycopg.Copy, "write", copy_write)
    patcher.wrap(psycopg.Copy, "finish", _timed(clock, "psycopg Copy.finish (end of COPY)"))


def _clickhouse_installer(capture: list[dict]) -> Installer:
    def install(patcher: Patcher, clock: StageClock, _engine: Any) -> None:
        from clickhouse_connect.driver import (
            client as ch_client,
            compression,
            httpclient,
            transform,
        )

        from core.db.write_v4.executors import ch as ch_executor

        executor = ch_executor.ClickHouseWriteExecutor

        def insert(method: str) -> Callable[[Callable], Callable]:
            # Captures (method, args, kwargs) of client.insert / client.insert_arrow for replay.
            def make(func: Callable) -> Callable:
                @functools.wraps(func)
                def wrapper(client, *args, **kwargs):
                    if clock.active:
                        capture.append((method, args, dict(kwargs)))
                    return clock.call(f"Client.{method}", func, client, *args, **kwargs)

                return wrapper

            return make

        patcher.wrap(
            ch_executor, "align_partition_to_table", _timed(clock, "align_partition_to_table")
        )
        for method in (
            "_normalize_partition",
            "_build_column_meta",
            "_prepare_column_data",
            "_build_arrow_table",
        ):
            patcher.wrap(executor, method, _timed(clock, method))
        patcher.wrap(
            ch_executor._ClickHouseClientPool,
            "_create_client",
            _timed(clock, "pool _create_client (get_client)"),
        )
        patcher.wrap(ch_client.Client, "insert", insert("insert"))
        patcher.wrap(ch_client.Client, "insert_arrow", insert("insert_arrow"))
        if hasattr(ch_client, "arrow_buffer"):
            patcher.wrap(ch_client, "arrow_buffer", _timed(clock, "arrow_buffer (Arrow IPC)"))
        patcher.wrap(
            ch_client.Client, "create_insert_context", _timed(clock, "create_insert_context")
        )
        patcher.wrap(httpclient.HttpClient, "data_insert", _timed(clock, "HttpClient.data_insert"))
        patcher.wrap(
            httpclient.HttpClient, "_raw_request", _timed(clock, "HttpClient._raw_request")
        )
        patcher.wrap(
            transform.NativeTransform,
            "build_insert",
            _timed_generator(clock, "body generator (serialize + compress)"),
        )
        patcher.wrap(
            compression.Lz4Compressor, "compress_block", _timed(clock, "lz4 compress_block")
        )

    return install


def _dbapi_shape(capture: Sequence[tuple], column_count: int) -> list[dict]:
    """How the DVT path called the DBAPI: statements, rows per call, value types."""
    shapes: dict[tuple[str, str], dict] = {}
    for kind, statement, captured in capture:
        if kind in ("commit", "copy", "copy_data"):
            continue
        # Bulk paths capture (cursor attributes, row tuples).
        parameters = captured[1] if kind == "bulk_executemany" else captured
        if parameters and isinstance(parameters[0], (dict, list, tuple)):
            rows = len(parameters)
            first = parameters[0]
        else:
            rows = len(parameters) // column_count
            first = parameters[:column_count]
        values = first.values() if isinstance(first, dict) else first
        key = (kind, statement[:120])
        shape = shapes.setdefault(
            key,
            {
                "kind": kind,
                "statement_head": statement[:160],
                "statement_chars": len(statement),
                "calls": 0,
                "rows": 0,
                "max_rows_per_call": 0,
                "value_types": [type(value).__name__ for value in values],
            },
        )
        shape["calls"] += 1
        shape["rows"] += rows
        shape["max_rows_per_call"] = max(shape["max_rows_per_call"], rows)
    return list(shapes.values())


def _copy_shape(capture: Sequence[tuple]) -> dict:
    """COPY statements and CSV buffers sent by the PostgreSQL COPY path."""
    statements = [statement for kind, statement, _ in capture if kind == "copy"]
    buffers = [len(data) for kind, _, data in capture if kind == "copy_data"]
    if not statements:
        return {}
    return {
        "statements": len(statements),
        "statement_head": statements[0][:160],
        "buffers": len(buffers),
        "bytes": sum(buffers),
        "max_buffer_bytes": max(buffers, default=0),
    }


def _align_substeps(ctx: _Context, engine: Any) -> list[dict]:
    """Replica of normalize.py:190-258 statements, timed one by one (no profiler).

    ClickHouse and the bulk paths (PostgreSQL COPY, SQL Server fast_executemany, MySQL bulk
    insert) call ``align_partition_to_table(cast_to_object=False)``, so their replica skips the
    ``astype(object)`` / ``where`` steps.
    """
    import pandas as pd
    import sqlalchemy as sa

    from core.db.write_v4 import normalize

    table = sa.Table(ctx.options.table, sa.MetaData(), autoload_with=engine)
    numeric_not_null = [
        column.name
        for column in table.columns
        if not column.nullable and normalize._is_numeric_column(column)
    ]
    samples: dict[str, list[tuple[float, float]]] = defaultdict(list)
    from core.db.write_v4.executors.sql import SQLWriteExecutor

    keeps_dtypes = (
        ctx.options.db == "clickhouse" or _executor_cls(ctx.request, engine) is not SQLWriteExecutor
    )

    def step(name: str, func: Callable[[], Any]) -> Any:
        wall0, cpu0 = time.perf_counter(), time.thread_time()
        value = func()
        samples[name].append((time.perf_counter() - wall0, time.thread_time() - cpu0))
        return value

    for _ in range(max(3, ctx.options.repeat)):
        source = ctx.pdf
        working = step("pdf.copy() (normalize.py:190)", source.copy)
        working = step(
            "normalize_index_for_db_write (normalize.py:190)",
            functools.partial(normalize.normalize_index_for_db_write, working),
        )
        working = step(
            "drop_internal_dvt_columns (normalize.py:191)",
            functools.partial(normalize.drop_internal_dvt_columns, working),
        )
        columns = [column.name for column in table.columns if column.name in working.columns]
        selected = step(
            "working[insert_column_names]", functools.partial(working.__getitem__, columns)
        )
        normalized = step("[...].copy() (normalize.py:244)", selected.copy)
        step(
            "non-nullable numeric isna().any() (normalize.py:251)",
            lambda frame=normalized: frame[numeric_not_null].isna().any(axis=0),
        )
        if keeps_dtypes:
            continue
        as_object = step(
            "astype(object) (normalize.py:258)", functools.partial(normalized.astype, object)
        )
        mask = step(
            "pd.notna(normalized) (normalize.py:258)", functools.partial(pd.notna, normalized)
        )
        step("where(mask, None) (normalize.py:258)", functools.partial(as_object.where, mask, None))

    return [
        {
            "step": name,
            "wall_s": statistics.median(wall for wall, _cpu in values),
            "cpu_s": statistics.median(cpu for _wall, cpu in values),
            "samples": len(values),
        }
        for name, values in samples.items()
    ]


# ---------------------------------------------------------------------------------------------
# Stage definitions for cProfile attribution
# ---------------------------------------------------------------------------------------------

PARTITION_ROOT = "partition (_PartitionWriteCallable.__call__)"


def setup_stages(executor_cls: type) -> list[Stage]:
    from core.db import write_v4
    from core.db.write_v4 import dask as write_dask, planner, resolver

    root = "write_dataframe (whole write)"
    execute = f"{executor_cls.__name__}.execute"
    process = "process_partitions_bounded (dask graph + sync compute)"
    by_execute = (code_pattern(executor_cls.execute),)
    return [
        Stage(root, (code_pattern(write_v4.write_dataframe),)),
        Stage(
            "plan_write (inspector.has_table, first connect)",
            (code_pattern(planner.plan_write),),
            parent=root,
        ),
        Stage("resolve_executor", (code_pattern(resolver.resolve_executor),), parent=root),
        Stage(execute, by_execute, parent=root),
        Stage(
            "_reflect_table (autoload)",
            (code_pattern(executor_cls._reflect_table),),
            by_execute,
            execute,
        ),
        Stage(
            "_normalize_partition(ddf._meta)",
            (code_pattern(executor_cls._normalize_partition),),
            by_execute,
            execute,
        ),
        Stage(process, (code_pattern(write_dask.process_partitions_bounded),), parent=execute),
        Stage(
            PARTITION_ROOT,
            (code_pattern(write_dask._PartitionWriteCallable.__call__),),
            parent=process,
        ),
    ]


def _align_stages(parent: str, align_callers: tuple[str, ...]) -> list[Stage]:
    import pandas as pd

    from core.db.write_v4 import normalize

    name = "align_partition_to_table"
    by_align = (code_pattern(normalize.align_partition_to_table),)
    return [
        Stage(name, by_align, align_callers, parent),
        Stage(
            "DataFrame.copy x2 (normalize.py:190, :244)",
            (code_pattern(pd.DataFrame.copy),),
            by_align,
            name,
        ),
        Stage(
            "normalize_index_for_db_write",
            (code_pattern(normalize.normalize_index_for_db_write),),
            by_align,
            name,
        ),
        Stage(
            "drop_internal / rename / case-mismatch checks",
            (
                code_pattern(normalize.drop_internal_dvt_columns),
                code_pattern(normalize._build_runtime_rename_map),
                code_pattern(normalize._case_mismatch_map),
            ),
            by_align,
            name,
        ),
        Stage(
            "DataFrame.__getitem__ (column selection)",
            (code_pattern(pd.DataFrame.__getitem__),),
            by_align,
            name,
        ),
        Stage(
            "non-nullable numeric NULL check (isna, any)",
            (code_pattern(pd.DataFrame.isna), code_pattern(pd.DataFrame.any)),
            by_align,
            name,
        ),
        Stage(
            "astype(object) (normalize.py:258)",
            (code_pattern(pd.DataFrame.astype),),
            by_align,
            name,
        ),
        Stage("pd.notna (normalize.py:258)", (code_pattern(pd.notna),), by_align, name),
        Stage(
            "where(mask, None) (normalize.py:258)",
            (code_pattern(pd.DataFrame.where),),
            by_align,
            name,
        ),
    ]


def _driver_stages(db: str, parent: str) -> list[Stage]:
    if db == "postgres":
        import psycopg
        from psycopg import _cursor_base, _pipeline, _queries

        executemany = "psycopg Cursor.executemany (pipeline mode)"
        generator = "pipeline generator _executemany_gen_pipeline (per-row Python)"
        by_generator = (code_pattern(_cursor_base.BaseCursor._executemany_gen_pipeline),)
        return [
            Stage(executemany, (code_pattern(psycopg.Cursor.executemany),), parent=parent),
            Stage(generator, by_generator, parent=executemany),
            Stage(
                "PostgresQuery.dump (per-row param adaptation)",
                (code_pattern(_queries.PostgresQuery.dump),),
                by_generator,
                generator,
            ),
            Stage(
                "Pipeline._communicate_gen (per-row send/fetch)",
                (code_pattern(_pipeline.BasePipeline._communicate_gen),),
                by_generator,
                generator,
            ),
            Stage(
                "select.select in wait_select (all partition calls, incl. COMMIT waits)",
                (builtin_pattern("<built-in method select.select>"),),
                parent=executemany,
                subtract=False,
            ),
        ]
    if db == "mysql":
        from pymysql import connections, cursors

        executemany = "pymysql Cursor.executemany"
        many = "Cursor._do_execute_many (multi-row INSERT rewrite)"
        execute = "Cursor.execute (multi-row INSERT, up to ~1 MB each)"
        return [
            Stage(executemany, (code_pattern(cursors.Cursor.executemany),), parent=parent),
            Stage(many, (code_pattern(cursors.Cursor._do_execute_many),), parent=executemany),
            Stage(
                "Cursor._escape_args (per-row escaping)",
                (code_pattern(cursors.Cursor._escape_args),),
                (code_pattern(cursors.Cursor._do_execute_many),),
                many,
            ),
            Stage(
                execute,
                (code_pattern(cursors.Cursor.execute),),
                (code_pattern(cursors.Cursor._do_execute_many),),
                many,
            ),
            Stage(
                "Connection._execute_command (send)",
                (code_pattern(connections.Connection._execute_command),),
                parent=execute,
            ),
            Stage(
                "Connection._read_query_result (wait + read OK packet)",
                (code_pattern(connections.Connection._read_query_result),),
                parent=execute,
            ),
        ]
    if db == "mssql":
        from sqlalchemy.connectors.pyodbc import PyODBCConnector

        return [
            Stage(
                "pyodbc Cursor.execute (native: bind + TDS + wait)",
                (builtin_pattern("<method 'execute' of 'pyodbc.Cursor' objects>"),),
                parent=parent,
            ),
            Stage(
                "SQLAlchemy do_set_input_sizes (cursor.setinputsizes per batch)",
                (code_pattern(PyODBCConnector.do_set_input_sizes),),
                # Called by Connection._exec_insertmany_context next to do_execute.
                parent="Connection.execute",
            ),
        ]
    return []


def sql_partition_stages(db: str, dialect_cls: type) -> list[Stage]:
    import pandas as pd
    import sqlalchemy as sa
    from sqlalchemy.engine import base, default
    from sqlalchemy.sql import elements

    from core.db.write_v4.dask import _PartitionWriteCallable
    from core.db.write_v4.executors.sql import SQLWriteExecutor

    insert = "SQLWriteExecutor._insert_partition"
    by_insert = (code_pattern(SQLWriteExecutor._insert_partition),)
    begin = "engine.begin() context (checkout, BEGIN, COMMIT, checkin)"
    execute = "Connection.execute"
    dbapi = "DBAPI dialect.do_executemany / do_execute"
    return [
        Stage(PARTITION_ROOT, (code_pattern(_PartitionWriteCallable.__call__),)),
        Stage(insert, by_insert, parent=PARTITION_ROOT),
        *_align_stages(insert, (code_pattern(SQLWriteExecutor._normalize_partition),)),
        Stage(
            "iloc[start:stop] chunk slicing",
            (code_pattern(pd.core.indexing._iLocIndexer.__getitem__),),
            by_insert,
            insert,
        ),
        Stage(
            "DataFrame.to_dict(orient='records')",
            (code_pattern(pd.DataFrame.to_dict),),
            by_insert,
            insert,
        ),
        Stage("sa.insert(table)", (code_pattern(sa.insert),), by_insert, insert),
        Stage(begin, (code_pattern(base.Engine.begin),), parent=insert),
        Stage("Engine.connect (pool checkout)", (code_pattern(base.Engine.connect),), parent=begin),
        Stage("Connection.begin", (code_pattern(base.Connection.begin),), parent=begin),
        Stage("COMMIT (dialect.do_commit)", (code_pattern(dialect_cls.do_commit),), parent=begin),
        Stage(
            "Connection.close (pool checkin)", (code_pattern(base.Connection.close),), parent=begin
        ),
        Stage(execute, (code_pattern(base.Connection.execute),), by_insert, insert),
        Stage(
            "statement compile (_compile_w_cache)",
            (code_pattern(elements.ClauseElement._compile_w_cache),),
            parent=execute,
        ),
        Stage(
            "execution context + bind params (_init_compiled)",
            (code_pattern(default.DefaultExecutionContext._init_compiled),),
            parent=execute,
        ),
        Stage(
            "insertmanyvalues batching (_deliver_insertmanyvalues_batches)",
            (code_pattern(default.DefaultDialect._deliver_insertmanyvalues_batches),),
            parent=execute,
        ),
        Stage(
            dbapi,
            (code_pattern(dialect_cls.do_executemany), code_pattern(dialect_cls.do_execute)),
            parent=execute,
        ),
        *_driver_stages(db, dbapi),
    ]


def pg_copy_partition_stages(dialect_cls: type) -> list[Stage]:
    import psycopg
    from sqlalchemy.engine import base

    from core.db.write_v4.dask import _PartitionWriteCallable
    from core.db.write_v4.executors import pg

    insert = "PostgresWriteExecutor._insert_partition"
    by_insert = (code_pattern(pg.PostgresWriteExecutor._insert_partition),)
    copy_partition = "PostgresWriteExecutor._copy_partition"
    by_copy = (code_pattern(pg.PostgresWriteExecutor._copy_partition),)
    begin = "engine.begin() context (checkout, COMMIT, checkin)"
    convert = "build_copy_table (Arrow conversion per column)"
    # ``Cursor.copy`` is a context-manager generator: it starts COPY and finishes it on exit.
    cursor_copy = "psycopg Cursor.copy context (COPY start + finish)"
    return [
        Stage(PARTITION_ROOT, (code_pattern(_PartitionWriteCallable.__call__),)),
        Stage(insert, by_insert, parent=PARTITION_ROOT),
        *_align_stages(insert, by_insert),
        Stage(copy_partition, by_copy, by_insert, insert),
        Stage(begin, (code_pattern(base.Engine.begin),), parent=copy_partition),
        Stage("Engine.connect (pool checkout)", (code_pattern(base.Engine.connect),), parent=begin),
        Stage("COMMIT (dialect.do_commit)", (code_pattern(dialect_cls.do_commit),), parent=begin),
        Stage(
            "Connection.close (pool checkin)", (code_pattern(base.Connection.close),), parent=begin
        ),
        Stage(convert, (code_pattern(pg.build_copy_table),), by_copy, copy_partition),
        Stage(
            "float8_numeric_text (float -> numeric, %.15g)",
            (code_pattern(pg.float8_numeric_text),),
            parent=convert,
        ),
        Stage(
            "iter_csv_buffers (pyarrow.csv.write_csv)",
            (code_pattern(pg.iter_csv_buffers),),
            by_copy,
            copy_partition,
        ),
        Stage(cursor_copy, (code_pattern(psycopg.Cursor.copy),), parent=copy_partition),
        Stage(
            "psycopg Copy.write (send CSV buffers)",
            (code_pattern(psycopg.Copy.write),),
            by_copy,
            copy_partition,
        ),
        Stage(
            "psycopg Copy.finish (end of COPY, server result)",
            (code_pattern(psycopg.Copy.finish),),
            parent=cursor_copy,
        ),
    ]


def mssql_fast_partition_stages(dialect_cls: type) -> list[Stage]:
    from sqlalchemy.engine import base

    from core.db.write_v4.dask import _PartitionWriteCallable
    from core.db.write_v4.executors import mssql

    executor = mssql.MssqlWriteExecutor
    insert = "MssqlWriteExecutor._insert_partition"
    by_insert = (code_pattern(executor._insert_partition),)
    fast = "MssqlWriteExecutor._fast_insert (row tuples + calls)"
    by_fast = (code_pattern(executor._fast_insert),)
    begin = "engine.begin() context (checkout, COMMIT, checkin)"
    by_begin = (code_pattern(base.Engine.begin),)
    batch = "MssqlWriteExecutor._execute_batch (setinputsizes + executemany)"
    return [
        Stage(PARTITION_ROOT, (code_pattern(_PartitionWriteCallable.__call__),)),
        Stage(insert, by_insert, parent=PARTITION_ROOT),
        *_align_stages(insert, by_insert),
        Stage(
            "catalog lookup (MssqlWriteExecutor._target)",
            (code_pattern(executor._target),),
            (code_pattern(executor._usable_target),),
            insert,
        ),
        Stage(
            "build_mssql_params (per-column conversion)",
            (code_pattern(mssql.build_mssql_params),),
            by_insert,
            insert,
        ),
        Stage(fast, by_fast, by_insert, insert),
        Stage(begin, by_begin, parent=fast),
        Stage(
            "Engine.connect (pool checkout)", (code_pattern(base.Engine.connect),), by_begin, begin
        ),
        Stage("COMMIT (dialect.do_commit)", (code_pattern(dialect_cls.do_commit),), parent=begin),
        Stage(
            "Connection.close (pool checkin)", (code_pattern(base.Connection.close),), parent=begin
        ),
        Stage(batch, (code_pattern(executor._execute_batch),), by_fast, fast),
        Stage(
            "pyodbc Cursor.executemany (native: parameter arrays + TDS + wait)",
            (builtin_pattern("<method 'executemany' of 'pyodbc.Cursor' objects>"),),
            parent=batch,
        ),
    ]


def mysql_bulk_partition_stages(dialect_cls: type) -> list[Stage]:
    from sqlalchemy.engine import base

    from core.db.write_v4.dask import _PartitionWriteCallable
    from core.db.write_v4.executors import mysql

    executor = mysql.MysqlWriteExecutor
    insert = "MysqlWriteExecutor._insert_partition"
    by_insert = (code_pattern(executor._insert_partition),)
    build = "build_mysql_columns (per-column values)"
    bulk = "MysqlWriteExecutor._bulk_insert (row tuples + calls)"
    by_bulk = (code_pattern(executor._bulk_insert),)
    begin = "engine.begin() context (checkout, COMMIT, checkin)"
    by_begin = (code_pattern(base.Engine.begin),)
    batch = "MysqlWriteExecutor._execute_batch (cursor.executemany)"
    return [
        Stage(PARTITION_ROOT, (code_pattern(_PartitionWriteCallable.__call__),)),
        Stage(insert, by_insert, parent=PARTITION_ROOT),
        *_align_stages(insert, by_insert),
        Stage(
            "catalog lookup (MysqlWriteExecutor._target)",
            (code_pattern(executor._target),),
            (code_pattern(executor._usable_target),),
            insert,
        ),
        Stage(build, (code_pattern(mysql.build_mysql_columns),), by_insert, insert),
        Stage(
            "timestamp_text (datetime64 -> str(Timestamp))",
            (code_pattern(mysql.timestamp_text),),
            parent=build,
        ),
        Stage(bulk, by_bulk, by_insert, insert),
        Stage(begin, by_begin, parent=bulk),
        Stage(
            "Engine.connect (pool checkout)", (code_pattern(base.Engine.connect),), by_begin, begin
        ),
        Stage("COMMIT (dialect.do_commit)", (code_pattern(dialect_cls.do_commit),), parent=begin),
        Stage(
            "Connection.close (pool checkin)", (code_pattern(base.Connection.close),), parent=begin
        ),
        Stage(batch, (code_pattern(executor._execute_batch),), by_bulk, bulk),
        *_driver_stages("mysql", batch),
    ]


def clickhouse_partition_stages() -> list[Stage]:
    import pandas as pd
    from clickhouse_connect.driver import (
        client as ch_client,
        compression,
        httpclient,
        insert,
        query,
        transform,
    )
    from urllib3 import connection as urllib3_connection

    from core.db.write_v4.dask import _PartitionWriteCallable
    from core.db.write_v4.executors import ch as ch_executor

    executor = ch_executor.ClickHouseWriteExecutor
    insert_partition = "ClickHouseWriteExecutor._insert_partition"
    by_insert = (code_pattern(executor._insert_partition),)
    normalize = "ClickHouseWriteExecutor._normalize_partition"
    by_normalize = (code_pattern(executor._normalize_partition),)
    prepare = "_prepare_column_data (Native path)"
    by_prepare = (code_pattern(executor._prepare_column_data),)
    acquire = "pool.acquire() context"
    insert_arrow = "clickhouse_connect Client.insert_arrow"
    client_insert = "clickhouse_connect Client.insert"
    data_insert = "HttpClient.data_insert"
    raw = "HttpClient._raw_request (HTTP POST)"
    body = "body generator chunk_gen (serialize + compress)"
    datetime_value = "_normalize_datetime_value (per value)"
    by_datetime = (code_pattern(executor._normalize_datetime_value),)
    string_value = "_normalize_string_value (per value)"
    return [
        Stage(PARTITION_ROOT, (code_pattern(_PartitionWriteCallable.__call__),)),
        Stage(insert_partition, by_insert, parent=PARTITION_ROOT),
        Stage(normalize, by_normalize, by_insert, insert_partition),
        *_align_stages(normalize, by_normalize),
        Stage(
            "DataFrame.copy",
            (code_pattern(pd.DataFrame.copy),),
            by_normalize,
            normalize,
        ),
        Stage(
            "_build_column_meta",
            (code_pattern(executor._build_column_meta),),
            by_insert,
            insert_partition,
        ),
        Stage(
            "iloc[start:stop] chunk slicing",
            (code_pattern(pd.core.indexing._iLocIndexer.__getitem__),),
            by_insert,
            insert_partition,
        ),
        Stage(prepare, by_prepare, by_insert, insert_partition),
        Stage(datetime_value, by_datetime, by_prepare, prepare),
        Stage(
            "_is_missing (datetime)",
            (code_pattern(executor._is_missing),),
            by_datetime,
            datetime_value,
        ),
        Stage(
            "_is_datetime_seconds_type",
            (code_pattern(executor._is_datetime_seconds_type),),
            by_datetime,
            datetime_value,
        ),
        Stage(string_value, (code_pattern(executor._normalize_string_value),), by_prepare, prepare),
        Stage(
            "_is_missing (string)",
            (code_pattern(executor._is_missing),),
            (code_pattern(executor._normalize_string_value),),
            string_value,
        ),
        Stage(
            "Series.where(notna, None) (object columns)",
            (code_pattern(pd.Series.where),),
            by_prepare,
            prepare,
        ),
        Stage("Series.notna", (code_pattern(pd.Series.notna),), by_prepare, prepare),
        Stage("Series.tolist", (code_pattern(pd.Series.tolist),), by_prepare, prepare),
        Stage(
            acquire,
            (code_pattern(ch_executor._ClickHouseClientPool.acquire),),
            parent=insert_partition,
        ),
        Stage(
            "_create_client (get_client, once per write)",
            (code_pattern(ch_executor._ClickHouseClientPool._create_client),),
            parent=acquire,
        ),
        Stage(
            "_build_arrow_table (Arrow path)",
            (code_pattern(executor._build_arrow_table),),
            by_insert,
            insert_partition,
        ),
        Stage(
            insert_arrow,
            (code_pattern(ch_client.Client.insert_arrow),),
            by_insert,
            insert_partition,
        ),
        Stage(
            "arrow_buffer (Arrow IPC + compression)",
            (code_pattern(query.arrow_buffer),),
            parent=insert_arrow,
        ),
        Stage(
            "HttpClient.raw_insert (HTTP POST, Arrow path)",
            (code_pattern(httpclient.HttpClient.raw_insert),),
            parent=insert_arrow,
        ),
        Stage(client_insert, (code_pattern(ch_client.Client.insert),), by_insert, insert_partition),
        Stage(
            "create_insert_context (type-name parsing)",
            (code_pattern(ch_client.Client.create_insert_context),),
            parent=client_insert,
        ),
        Stage(
            data_insert, (code_pattern(httpclient.HttpClient.data_insert),), parent=client_insert
        ),
        Stage(
            raw,
            (code_pattern(httpclient.HttpClient._raw_request),),
            (code_pattern(httpclient.HttpClient.data_insert),),
            data_insert,
        ),
        Stage(
            body,
            (nested_code_pattern(transform.NativeTransform.build_insert, "chunk_gen"),),
            parent=raw,
        ),
        Stage(
            "InsertContext.next_block",
            (code_pattern(insert.InsertContext.next_block),),
            parent=body,
        ),
        Stage(
            "lz4 compress_block",
            (code_pattern(compression.Lz4Compressor.compress_block),),
            parent=body,
        ),
        Stage(
            "HTTP response wait (urllib3 getresponse; all partition requests incl. get_client)",
            (code_pattern(urllib3_connection.HTTPConnection.getresponse),),
            parent=raw,
            subtract=False,
        ),
    ]


# ---------------------------------------------------------------------------------------------
# Profile run and pstats output
# ---------------------------------------------------------------------------------------------


class _StatsHolder:
    """Minimal ``create_stats``/``stats`` object accepted by ``pstats.Stats``."""

    def __init__(self, stats: StatsDict) -> None:
        self.stats = dict(stats)

    def create_stats(self) -> None:
        return None


def _path_prefixes() -> list[tuple[str, str]]:
    prefixes = [
        (sysconfig.get_paths()["purelib"] + os.sep, "site-packages/"),
        (str(REPO_ROOT) + os.sep, ""),
        (sysconfig.get_paths()["stdlib"] + os.sep, "stdlib/"),
    ]
    return sorted(prefixes, key=lambda item: -len(item[0]))


def shorten(text: str) -> str:
    for prefix, replacement in _path_prefixes():
        text = text.replace(prefix, replacement)
    return re.sub(r"(?<=[\w.])\\(?=[\w.])", "/", text)


def _pstats_text(stats: StatsDict, sort: str, limit: int) -> str:
    buffer = io.StringIO()
    pstats.Stats(_StatsHolder(stats), stream=buffer).sort_stats(sort).print_stats(limit)
    return shorten(buffer.getvalue())


def _top_functions(stats: StatsDict, limit: int) -> list[dict]:
    ranked = sorted(stats.items(), key=lambda item: -item[1][2])[:limit]
    return [
        {
            "function": shorten(func_label(key)),
            "ncalls": total,
            "tottime_s": tottime,
            "cumtime_s": cumtime,
        }
        for key, (_primitive, total, tottime, cumtime, _callers) in ranked
    ]


def _builtin_split(stats: StatsDict) -> dict[str, float]:
    native = sum(entry[2] for key, entry in stats.items() if key[0] == "~")
    python = sum(entry[2] for key, entry in stats.items() if key[0] != "~")
    return {"python_frames_tottime_s": python, "c_builtins_tottime_s": native}


def _profiled_run(ctx: _Context, out: Path) -> dict:
    from core.db.write_v4.executors.ch import ClickHouseWriteExecutor
    from core.db.write_v4.executors.mssql import MssqlWriteExecutor
    from core.db.write_v4.executors.mysql import MysqlWriteExecutor
    from core.db.write_v4.executors.pg import PostgresWriteExecutor

    profiler = cProfile.Profile()
    run, _clock, probe = _write_once(ctx, "cprofile", profiler=profiler)
    profiler.dump_stats(out / "profile.prof")
    full = profiler.stats
    if len(probe.snapshots) != 2:
        raise RuntimeError(f"expected one partition snapshot pair, got {len(probe.snapshots)}")
    partition = diff_stats(probe.snapshots[1], probe.snapshots[0])

    (out / "pstats_cumulative.txt").write_text(
        _pstats_text(full, "cumulative", PSTATS_TOP), "utf-8"
    )
    (out / "pstats_tottime.txt").write_text(_pstats_text(full, "tottime", PSTATS_TOP), "utf-8")
    (out / "pstats_partition_tottime.txt").write_text(
        _pstats_text(partition, "tottime", PSTATS_TOP), "utf-8"
    )
    (out / "pstats_partition_cumulative.txt").write_text(
        _pstats_text(partition, "cumulative", PSTATS_TOP), "utf-8"
    )

    if ctx.options.db == "clickhouse":
        executor_cls: type = ClickHouseWriteExecutor
        partition_stages = clickhouse_partition_stages()
    else:
        engine = _engine(ctx)
        try:
            dialect_cls = type(engine.dialect)
            executor_cls = _executor_cls(ctx.request, engine)
        finally:
            engine.dispose()
        if executor_cls is PostgresWriteExecutor:
            partition_stages = pg_copy_partition_stages(dialect_cls)
        elif executor_cls is MssqlWriteExecutor:
            partition_stages = mssql_fast_partition_stages(dialect_cls)
        elif executor_cls is MysqlWriteExecutor:
            partition_stages = mysql_bulk_partition_stages(dialect_cls)
        else:
            partition_stages = sql_partition_stages(ctx.options.db, dialect_cls)
    builtins = {key: entry for key, entry in partition.items() if key[0] == "~"}
    return {
        "run": asdict(run),
        "setup_stages": attribute_stages(full, setup_stages(executor_cls), rows=ctx.options.rows),
        "partition_stages": attribute_stages(partition, partition_stages, rows=ctx.options.rows),
        "top_tottime_partition": _top_functions(partition, SUMMARY_TOP),
        "top_builtins_partition": _top_functions(builtins, SUMMARY_TOP),
        "partition_split": _builtin_split(partition),
    }


# ---------------------------------------------------------------------------------------------
# Driver-only replay
# ---------------------------------------------------------------------------------------------


def _timed_replay(ctx: _Context, label: str, body: Callable[[Any], tuple[int, int]]) -> dict:
    """Recreates the table, runs ``body(engine)`` (returns calls, commits) and checks COUNT."""
    _recreate_table(ctx)
    engine = _engine(ctx)
    try:
        wall0, cpu0 = time.perf_counter(), time.process_time()
        calls, commits = body(engine)
        wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
        count = _count_rows(engine, ctx)
    finally:
        engine.dispose()
    _check_count(ctx, label, count)
    chunk = ctx.options.chunksize or "auto"
    seed._emit(f"[{ctx.options.db} c{chunk}] driver-only {label}: {wall:.3f} s")
    return {
        "variant": label,
        "calls": calls,
        "commits": commits,
        "wall_s": wall,
        "cpu_s": cpu,
        "rows_per_s": ctx.options.rows / wall if wall > 0 else None,
        "count": count,
    }


def _replay_dbapi(ops: Sequence[tuple]) -> Callable[[Any], tuple[int, int]]:
    def body(engine: Any) -> tuple[int, int]:
        raw = engine.raw_connection()
        calls = commits = 0
        copy_context = copy = None
        try:
            cursor = raw.cursor()
            for kind, statement, parameters in ops:
                if kind == "copy_data":
                    copy.write(parameters)
                    continue
                if copy_context is not None:
                    copy_context.__exit__(None, None, None)
                    copy_context = copy = None
                if kind == "copy":
                    copy_context = cursor.copy(statement)
                    copy = copy_context.__enter__()
                    calls += 1
                elif kind == "executemany":
                    cursor.executemany(statement, parameters)
                    calls += 1
                elif kind == "bulk_executemany":
                    attributes, rows = parameters
                    for name, value in attributes.items():
                        if name == "input_sizes":
                            cursor.setinputsizes(value)
                        else:
                            setattr(cursor, name, value)
                    cursor.executemany(statement, rows)
                    calls += 1
                elif kind == "execute":
                    cursor.execute(statement, parameters)
                    calls += 1
                else:
                    raw.commit()
                    commits += 1
            if copy_context is not None:
                copy_context.__exit__(None, None, None)
            cursor.close()
        finally:
            raw.close()
        return calls, commits

    return body


def _mssql_fast_executemany(
    ops: Sequence[tuple], column_count: int
) -> Callable[[Any], tuple[int, int]]:
    """pyodbc ``fast_executemany`` with the same values, one executemany + commit per chunk."""
    inserts = [op for op in ops if op[0] != "commit"]
    statement = inserts[0][1]
    head = statement[: statement.upper().index(" VALUES ")]
    single = f"{head} VALUES ({', '.join('?' for _ in range(column_count))})"
    chunks: list[list[tuple]] = [[]]
    for kind, _statement, parameters in ops:
        if kind == "commit":
            chunks.append([])
            continue
        flat = list(parameters)
        chunks[-1].extend(
            tuple(flat[start : start + column_count]) for start in range(0, len(flat), column_count)
        )
    chunks = [chunk for chunk in chunks if chunk]

    def body(engine: Any) -> tuple[int, int]:
        raw = engine.raw_connection()
        try:
            cursor = raw.cursor()
            cursor.fast_executemany = True
            for chunk in chunks:
                cursor.executemany(single, chunk)
                raw.commit()
            cursor.close()
        finally:
            raw.close()
        return len(chunks), len(chunks)

    return body


def _replay_clickhouse(calls: Sequence[tuple]) -> Callable[[Any], tuple[int, int]]:
    def body(engine: Any) -> tuple[int, int]:
        from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client

        client = create_clickhouse_client(
            {**build_clickhouse_client_kwargs(engine), "compress": True}
        )
        try:
            for method, args, kwargs in calls:
                getattr(client, method)(*args, **kwargs)
        finally:
            client.close()
        return len(calls), 0

    return body


_ASYNC_SETTINGS = ("async_insert", "wait_for_async_insert")


def _driver_only(ctx: _Context, capture: list) -> list[dict]:
    if ctx.options.db == "clickhouse":
        methods = "/".join(sorted({f"client.{method}" for method, _, _ in capture})) or "insert"
        settings = capture[0][2].get("settings", {}) if capture else {}
        results = [
            _timed_replay(
                ctx, f"{methods} replay, same settings ({settings})", _replay_clickhouse(capture)
            )
        ]
        if any(key in settings for key in _ASYNC_SETTINGS):
            without_async = [
                (
                    method,
                    args,
                    {
                        **kwargs,
                        "settings": {
                            key: value
                            for key, value in kwargs["settings"].items()
                            if key not in _ASYNC_SETTINGS
                        },
                    },
                )
                for method, args, kwargs in capture
            ]
            results.append(
                _timed_replay(
                    ctx,
                    f"{methods} replay, without async_insert",
                    _replay_clickhouse(without_async),
                )
            )
        return results
    results = [
        _timed_replay(
            ctx, "DBAPI replay of the DVT calls (same SQL + params)", _replay_dbapi(capture)
        )
    ]
    # This variant re-sends the multi-VALUES parameters of the SQLAlchemy INSERT path.
    if ctx.options.db == "mssql" and any(op[0] in ("execute", "executemany") for op in capture):
        column_count = len(synthetic.column_names(ctx.options.schema))
        results.append(
            _timed_replay(
                ctx,
                "pyodbc fast_executemany, same values, 1 call + commit per chunk",
                _mssql_fast_executemany(capture, column_count),
            )
        )
    return results


# ---------------------------------------------------------------------------------------------
# Orchestration and reporting
# ---------------------------------------------------------------------------------------------


def _environment(ctx: _Context) -> dict:
    from importlib import metadata

    packages = {}
    for name in (
        "pandas",
        "numpy",
        "pyarrow",
        "dask",
        "SQLAlchemy",
        "psycopg",
        "psycopg-binary",
        "PyMySQL",
        "pyodbc",
        "clickhouse-connect",
        "clickhouse-sqlalchemy",
        "lz4",
        "urllib3",
    ):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    engine = _engine(ctx)
    try:
        url = engine.url.render_as_string(hide_password=True)
    finally:
        engine.dispose()
    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "packages": packages,
        "engine_url": url,
        "argv": sys.argv,
    }


def run_profile(options: ProfileOptions) -> dict:
    out = options.out
    out.mkdir(parents=True, exist_ok=True)
    ctx = _build_context(options)
    report: dict[str, Any] = {
        "options": {**asdict(options), "out": out.as_posix(), "password": "***"},
        "environment": _environment(ctx),
    }

    report["warmup"] = [asdict(_write_once(ctx, f"warmup{i}")[0]) for i in range(options.warmup)]
    plain: list[RunResult] = []
    probe: PartitionProbe | None = None
    for i in range(options.repeat):
        run, _clock, probe = _write_once(ctx, f"run{i}")
        plain.append(run)
    report["plain_runs"] = [asdict(run) for run in plain]
    report["plain_stats"] = _plain_stats(plain, options.rows)
    if probe is not None:
        report["partition_dtypes"] = probe.dtypes
        report["partition_index"] = probe.index_type

    capture: list = []
    installer = (
        _clickhouse_installer(capture)
        if options.db == "clickhouse"
        else _sql_installer(capture, ctx.request)
    )
    run, clock, _probe = _write_once(ctx, "instrumented", install=installer)
    report["instrumented"] = {
        "run": asdict(run),
        "stages": instrumented_rows(clock.totals, rows=options.rows),
    }
    column_count = len(synthetic.column_names(options.schema))
    if options.db == "clickhouse":
        report["instrumented"]["insert_calls"] = len(capture)
        report["instrumented"]["insert_shape"] = _clickhouse_shape(capture)
    else:
        report["instrumented"]["dbapi_shape"] = _dbapi_shape(capture, column_count)
        copy_shape = _copy_shape(capture)
        if copy_shape:
            report["instrumented"]["copy_shape"] = copy_shape
    engine = _engine(ctx)
    try:
        report["align_substeps"] = _align_substeps(ctx, engine)
    finally:
        engine.dispose()

    report["cprofile"] = _profiled_run(ctx, out)
    report["driver_only"] = _driver_only(ctx, capture)

    (out / "report.json").write_text(json.dumps(report, indent=2, default=str), "utf-8")
    (out / "summary.md").write_text(render_summary(report), "utf-8")
    seed._emit(f"artifacts: {out.as_posix()}/summary.md")
    return report


def _clickhouse_shape(capture: Sequence[tuple]) -> dict:
    if not capture:
        return {}
    method, first_args, first = capture[0]
    if method == "insert_arrow":
        # ch.py calls client.insert_arrow(table, arrow_table, settings=...).
        tables = [args[1] for _, args, _ in capture]
        return {
            "method": method,
            "calls": len(capture),
            "rows": sum(table.num_rows for table in tables),
            "settings": first.get("settings"),
            "value_types": [str(field.type) for field in first_args[1].schema],
            "container_types": ["pyarrow.Table"],
        }
    return {
        "method": method,
        "calls": len(capture),
        "rows": sum(len(kwargs["data"][0]) for _, _, kwargs in capture),
        "column_type_names": first["column_type_names"],
        "settings": first["settings"],
        "value_types": [
            type(column[0]).__name__ if len(column) else None for column in first["data"]
        ],
        "container_types": [type(column).__name__ for column in first["data"]],
    }


def _plain_stats(runs: Sequence[RunResult], rows: int) -> dict:
    result: dict[str, dict[str, float]] = {}
    for metric in ("write_wall_s", "write_cpu_s", "partition_wall_s", "partition_cpu_s"):
        values = [getattr(run, metric) for run in runs]
        result[metric] = {"min": min(values), "median": statistics.median(values)}
    for scope in ("write", "partition"):
        wall = result[f"{scope}_wall_s"]
        result[f"{scope}_rows_per_s"] = {
            "best": rows / wall["min"],
            "median": rows / wall["median"],
        }
    return result


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}".replace(",", " ")


def _md_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def render_summary(report: Mapping[str, Any]) -> str:
    options = report["options"]
    env = report["environment"]
    rows = options["rows"]
    stats = report["plain_stats"]
    partition_median = stats["partition_wall_s"]["median"]
    lines = [
        f"# write_v4 profile: {options['db']}, {rows} rows, "
        f"chunksize {options['chunksize'] or 'auto'}",
        "",
        f"- Command: `{' '.join(env['argv'])}`",
        f"- Engine: `{env['engine_url']}`; table `{options['table']}` (recreated per run)",
        f"- Python {env['python']} on {env['platform']}, {env['cpu_count']} CPUs; "
        + ", ".join(f"{name} {version}" for name, version in env["packages"].items()),
        f"- Partition dtypes ({report.get('partition_index', '?')}): "
        + ", ".join(
            f"{name}={dtype}" for name, dtype in report.get("partition_dtypes", {}).items()
        ),
        "- One thread: `write_workers=1` -> `compute(scheduler='sync')`; numbers are per core.",
        "",
        "## 1. Plain runs (no profiler)",
        "",
    ]
    table_rows = [
        [
            run["label"],
            _fmt(run["write_wall_s"]),
            _fmt(run["write_cpu_s"]),
            _fmt(run["partition_wall_s"]),
            _fmt(run["partition_cpu_s"]),
            _fmt_rate(rows / run["write_wall_s"]),
            _fmt_rate(rows / run["partition_wall_s"]),
        ]
        for run in report["plain_runs"]
    ]
    for agg in ("min", "median"):
        table_rows.append(
            [
                f"**{agg}**",
                _fmt(stats["write_wall_s"][agg]),
                _fmt(stats["write_cpu_s"][agg]),
                _fmt(stats["partition_wall_s"][agg]),
                _fmt(stats["partition_cpu_s"][agg]),
                _fmt_rate(rows / stats["write_wall_s"][agg]),
                _fmt_rate(rows / stats["partition_wall_s"][agg]),
            ]
        )
    lines.append(
        _md_table(
            [
                "run",
                "write wall s",
                "write CPU s",
                "partition wall s",
                "partition CPU s",
                "rows/s write",
                "rows/s partition",
            ],
            table_rows,
        )
    )
    blocked = stats["partition_wall_s"]["median"] - stats["partition_cpu_s"]["median"]
    lines += [
        "",
        f"Partition median: wall {_fmt(partition_median)} s, CPU "
        f"{_fmt(stats['partition_cpu_s']['median'])} s -> blocked (wall - CPU, waiting on "
        f"network/server) {_fmt(blocked)} s = {100 * blocked / partition_median:.1f}% of wall.",
        "Setup outside the partition (plan, reflect, first connect, dask graph) = write - partition.",
        "",
        "## 2. Instrumented stage timers (no profiler, one run)",
        "",
        "Wall from `perf_counter`, CPU from `thread_time` (15.6 ms ticks on Windows); "
        "`self` = stage minus timed children.",
        "",
    ]
    inst = report["instrumented"]
    lines.append(
        _md_table(
            [
                "stage",
                "calls",
                "wall s",
                "CPU s",
                "wall-CPU s",
                "self wall s",
                "% partition",
                "rows/s if only cost",
            ],
            [
                [
                    "· " * row["depth"] + row["stage"],
                    str(row["calls"]),
                    _fmt(row["wall_s"]),
                    _fmt(row["cpu_s"]),
                    _fmt(row["blocked_s"]),
                    _fmt(row["self_wall_s"]),
                    _fmt(row["pct_of_root"], 1),
                    _fmt_rate(row["rows_per_s"]),
                ]
                for row in inst["stages"]
            ],
        )
    )
    if inst.get("dbapi_shape"):
        lines += ["", "DBAPI calls made by the DVT path:", ""]
        for shape in inst["dbapi_shape"]:
            lines.append(
                f"- `{shape['kind']}` x{shape['calls']}, {shape['rows']} rows, max "
                f"{shape['max_rows_per_call']} rows/call, statement {shape['statement_chars']} chars: "
                f"`{shape['statement_head']}...`; value types: {', '.join(shape['value_types'])}"
            )
    if inst.get("copy_shape"):
        shape = inst["copy_shape"]
        lines += [
            "",
            f"COPY statements: {shape['statements']}, CSV buffers {shape['buffers']} "
            f"({shape['bytes']} bytes, max {shape['max_buffer_bytes']}): "
            f"`{shape['statement_head']}`",
        ]
    if "insert_shape" in inst:
        shape = inst["insert_shape"]
        lines += [
            "",
            f"client.{shape.get('method')} calls: {shape.get('calls')}, rows {shape.get('rows')}, "
            "settings "
            f"`{shape.get('settings')}`; column containers {shape.get('container_types')}; "
            f"value types {shape.get('value_types')}",
        ]
    lines += [
        "",
        "### align_partition_to_table sub-steps (replica of normalize.py:190-258, median)",
        "",
        _md_table(
            ["step", "wall s", "CPU s", "rows/s if only cost"],
            [
                [
                    step["step"],
                    _fmt(step["wall_s"]),
                    _fmt(step["cpu_s"]),
                    _fmt_rate(rows / step["wall_s"] if step["wall_s"] > 0 else None),
                ]
                for step in report["align_substeps"]
            ],
        ),
    ]
    profile = report["cprofile"]
    profiled_partition = profile["run"]["partition_wall_s"]
    lines += [
        "",
        "## 3. cProfile (one run)",
        "",
        f"Profiled write {_fmt(profile['run']['write_wall_s'])} s, partition "
        f"{_fmt(profiled_partition)} s = {profiled_partition / partition_median:.2f}x the plain "
        "median partition (profiler overhead, larger for Python-heavy stages).",
        "Exclusive = cumulative - child stages; caller-restricted stages use pstats caller edges. "
        "Partition stages come from the snapshot diff (partition only).",
        "",
        "### Setup (whole write)",
        "",
        _stage_table(profile["setup_stages"], "% of write"),
        "",
        "### Partition stage tree",
        "",
        _stage_table(profile["partition_stages"], "% of partition"),
    ]
    split = profile["partition_split"]
    total = split["python_frames_tottime_s"] + split["c_builtins_tottime_s"]
    lines += [
        "",
        f"Partition tottime: Python frames {_fmt(split['python_frames_tottime_s'])} s "
        f"({100 * split['python_frames_tottime_s'] / total:.1f}%), C builtins/extensions "
        f"{_fmt(split['c_builtins_tottime_s'])} s ({100 * split['c_builtins_tottime_s'] / total:.1f}%).",
        "",
        f"### Top-{SUMMARY_TOP} tottime (partition)",
        "",
        _function_table(profile["top_tottime_partition"]),
        "",
        f"### Top-{SUMMARY_TOP} C builtins by tottime (partition)",
        "",
        _function_table(profile["top_builtins_partition"]),
        "",
        "## 4. Driver only (replay of the captured calls, no DVT/SQLAlchemy Python)",
        "",
        _md_table(
            [
                "variant",
                "calls",
                "commits",
                "wall s",
                "CPU s",
                "wall-CPU s",
                "rows/s",
                "% of DVT partition wall",
            ],
            [
                [
                    item["variant"],
                    str(item["calls"]),
                    str(item["commits"]),
                    _fmt(item["wall_s"]),
                    _fmt(item["cpu_s"]),
                    _fmt(item["wall_s"] - item["cpu_s"]),
                    _fmt_rate(item["rows_per_s"]),
                    _fmt(100 * item["wall_s"] / partition_median, 1),
                ]
                for item in report["driver_only"]
            ],
        ),
        "",
        _dvt_side_line(report["driver_only"][0], partition_median),
        "",
        "Files: `profile.prof`, `pstats_cumulative.txt`, `pstats_tottime.txt` (whole write), "
        "`pstats_partition_*.txt` (partition window), `report.json`.",
        "",
    ]
    return "\n".join(lines)


def _dvt_side_line(replay: Mapping[str, Any], partition_median: float) -> str:
    dvt_side = partition_median - replay["wall_s"]
    return (
        f"DVT side (normalize + to_dict/column prep + SQLAlchemy + loop) ~ partition median - "
        f"replay = {_fmt(partition_median)} - {_fmt(replay['wall_s'])} = {_fmt(dvt_side)} s "
        f"({100 * dvt_side / partition_median:.1f}% of the partition); driver + server "
        f"{100 * replay['wall_s'] / partition_median:.1f}%."
    )


def _stage_table(stage_rows: Sequence[Mapping[str, Any]], pct_header: str) -> str:
    return _md_table(
        ["stage", "calls", "cumulative s", "exclusive s", pct_header, "rows/s if only cost"],
        [
            [
                "· " * row["depth"] + row["stage"],
                str(row["calls"]),
                _fmt(row["cumulative_s"]),
                _fmt(row["exclusive_s"]),
                _fmt(row["pct_of_root"], 1),
                _fmt_rate(row["rows_per_s"]),
            ]
            for row in stage_rows
            if row["calls"]
        ],
    )


def _function_table(functions: Sequence[Mapping[str, Any]]) -> str:
    return _md_table(
        ["function", "ncalls", "tottime s", "cumtime s"],
        [
            [
                f"`{item['function']}`",
                str(item["ncalls"]),
                _fmt(item["tottime_s"]),
                _fmt(item["cumtime_s"]),
            ]
            for item in functions
        ],
    )


def _non_negative_int(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    run_profile(parse_args(argv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
