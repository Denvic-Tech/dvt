from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

import numpy as np
import pandas as pd
from sqlalchemy.engine import Connection, CursorResult, Engine

from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client

# float64 represents every integer below this magnitude exactly.
_FLOAT64_EXACT_INT_LIMIT = 2**53


def execute_literal_sql(connection: Connection, sql: str) -> CursorResult:
    """Run SQL text exactly as written, for every SQLAlchemy dialect.

    ``exec_driver_sql`` without parameters still hands the DB-API an empty parameter collection,
    and drivers with the format/pyformat paramstyle (psycopg, psycopg2, pymysql and both
    clickhouse-sqlalchemy cursors, http and native) then parse ``%`` as a placeholder:
    ``LIKE 'A%'`` and ``a % b`` fail, ``'%%'`` turns into ``'%'`` and ``'%s'`` becomes a bind
    marker. ``no_parameters`` calls ``cursor.execute(sql)`` with no parameter collection, so the
    text means what it means in psql or the mysql client. qmark and named drivers (sqlite3,
    pyodbc, oracledb) never treat ``%`` specially. clickhouse-sqlalchemy has no
    ``do_execute_no_params`` of its own, so per-statement execution options (``settings``,
    ``stream_results``, external tables) do not reach its cursor on this path.
    """
    return connection.exec_driver_sql(sql, execution_options={"no_parameters": True})


def _normalize_type_repr(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, type):
        return value.__name__
    if hasattr(value, "name"):
        return str(getattr(value, "name"))
    return str(value)


class ReadV3SqlRunner(ABC):
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @abstractmethod
    def query_df(self, sql: str) -> pd.DataFrame:
        raise NotImplementedError

    def describe_query_columns(self, raw_query: str) -> list[tuple[str, str]]:
        return []


def _restore_exact_integers(df: pd.DataFrame, rows: Sequence[Sequence[object]]) -> None:
    """Rebuild as ``Int64`` the integer columns that inference turned into lossy float64.

    ``pd.DataFrame(rows)`` infers Python ints next to ``None`` as float64, which rounds values
    of magnitude 2**53 and above. Only a float64 column holding such a value is looked at again;
    it becomes ``Int64`` when every non-NULL value is exactly ``int`` and fits int64. Every other
    column stays as inferred. Columns are addressed by position (names may repeat).
    """
    for position, dtype in enumerate(df.dtypes):
        if dtype != np.dtype("float64"):
            continue
        if not np.any(np.abs(df.iloc[:, position].to_numpy()) >= _FLOAT64_EXACT_INT_LIMIT):
            continue
        values = [row[position] for row in rows]
        if not all(value is None or type(value) is int for value in values):
            continue
        try:
            exact = pd.array(values, dtype="Int64")
        except (TypeError, ValueError, OverflowError):
            continue
        df.isetitem(position, exact)


class SqlAlchemyReadV3SqlRunner(ReadV3SqlRunner):
    def __init__(self, engine: Engine, *, exact_integers: bool = False) -> None:
        """``exact_integers`` keeps 64-bit integers next to NULL exact (``Int64``) instead of
        float64-rounded; the read executor's segment runner asks for it, other callers keep the
        plain inferred frame."""
        super().__init__(engine)
        self.exact_integers = exact_integers

    def query_df(self, sql: str) -> pd.DataFrame:
        with self.engine.connect() as conn:
            result = execute_literal_sql(conn, sql)
            if not result.returns_rows:
                return pd.DataFrame()
            columns = list(result.keys())
            rows = result.fetchall()
        df = pd.DataFrame(rows, columns=columns)
        if self.exact_integers:
            _restore_exact_integers(df, rows)
        return df


class ClickHouseReadV3SqlRunner(ReadV3SqlRunner):
    def __init__(self, engine: Engine) -> None:
        super().__init__(engine)
        self._client_kwargs = build_clickhouse_client_kwargs(engine)

    def query_df(self, sql: str) -> pd.DataFrame:
        client = create_clickhouse_client(self._client_kwargs)
        try:
            return client.query_df(sql)
        finally:
            client.close()

    def describe_query_columns(self, raw_query: str) -> list[tuple[str, str]]:
        describe_df = self.query_df(f"DESCRIBE TABLE ({raw_query})")
        if describe_df.empty:
            return []
        return [
            (str(row.get("name", "")), _normalize_type_repr(row.get("type")))
            for _, row in describe_df.iterrows()
            if str(row.get("name", "")).strip()
        ]


def resolve_sql_runner(engine: Engine, *, exact_integers: bool = False) -> ReadV3SqlRunner:
    """``exact_integers`` applies to the SQLAlchemy runner; the ClickHouse client keeps its
    own dtypes."""
    dialect_name = (engine.dialect.name or "").lower()
    if "clickhouse" in dialect_name:
        return ClickHouseReadV3SqlRunner(engine)
    return SqlAlchemyReadV3SqlRunner(engine, exact_integers=exact_integers)


def read_sql_df(engine: Engine, sql: str) -> pd.DataFrame:
    return resolve_sql_runner(engine).query_df(sql)

