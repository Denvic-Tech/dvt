from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd
from sqlalchemy.engine import Engine

from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client


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


class SqlAlchemyReadV3SqlRunner(ReadV3SqlRunner):
    def query_df(self, sql: str) -> pd.DataFrame:
        with self.engine.connect() as conn:
            result = conn.exec_driver_sql(sql)
            if not result.returns_rows:
                return pd.DataFrame()
            columns = list(result.keys())
            rows = result.fetchall()
        return pd.DataFrame(rows, columns=columns)


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


def resolve_sql_runner(engine: Engine) -> ReadV3SqlRunner:
    dialect_name = (engine.dialect.name or "").lower()
    if "clickhouse" in dialect_name:
        return ClickHouseReadV3SqlRunner(engine)
    return SqlAlchemyReadV3SqlRunner(engine)


def read_sql_df(engine: Engine, sql: str) -> pd.DataFrame:
    return resolve_sql_runner(engine).query_df(sql)

