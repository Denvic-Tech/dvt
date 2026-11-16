import asyncio
from typing import ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy import Engine

from services.task_benchmarking import synthetic
from services.task_benchmarking.metrics import record_metric

from src.logger import logger
from src.node_dsl import InputField, SignalOutputBaseNode, SqlConnectionRecord
from src.node_dsl.runtime.connections import resolve_sql_engine

# SQLAlchemy dialect name -> synthetic.py DDL dialect.
_DDL_DIALECTS: dict[str, str] = {
    "postgresql": "postgres",
    "clickhouse": "clickhouse",
    "mssql": "mssql",
    "mysql": "mysql",
    "mariadb": "mysql",
}


class BenchmarkEnsureTable(SignalOutputBaseNode):
    """Creates (or recreates) a synthetic-schema table before a benchmark write.

    Connect ``signal_out`` to the writer's ``signal_in`` so the table exists before writing.
    The database itself must already exist.
    """

    TITLE = "Benchmark Ensure Table"
    CATEGORY = "Benchmark"
    TAGS: ClassVar[list[str]] = ["Testing"]
    VISIBLE = False
    CACHABLE = False

    connection: SqlConnectionRecord | Engine = InputField(description="Target connection.")
    table_name: str = InputField(description="Target table name.")
    db_schema: str | None = InputField(
        default=None,
        description="Schema (postgres/mssql) or database (clickhouse/mysql) of the table.",
    )
    schema: Literal["wide_mixed", "numeric", "wide_text"] = InputField(
        default="wide_mixed",
        description="Synthetic column set of the table.",
    )
    on_exists: Literal["recreate", "keep"] = InputField(
        default="recreate",
        description="recreate drops and creates an existing table; keep leaves it unchanged.",
    )

    def _ensure_table(self) -> str:
        engine = resolve_sql_engine(self.connection)
        try:
            dialect = _DDL_DIALECTS.get(engine.dialect.name)
            if dialect is None:
                raise ValueError(f"Unsupported dialect for benchmark DDL: {engine.dialect.name}")
            exists = sa.inspect(engine).has_table(self.table_name, schema=self.db_schema)
            if exists and self.on_exists == "keep":
                return "kept"
            statements = synthetic.create_table_sql(
                self.schema, dialect, self.table_name, self.db_schema
            )
            if exists:
                drop = synthetic.drop_table_sql(dialect, self.table_name, self.db_schema)
                statements.insert(0, drop)
            with engine.begin() as conn:
                for statement in statements:
                    conn.exec_driver_sql(statement)
            return "recreated" if exists else "created"
        finally:
            if engine is not self.connection:
                engine.dispose()

    async def process(self) -> None:
        action = await asyncio.to_thread(self._ensure_table)
        logger.info("Benchmark table {}: {}", self.table_name, action)
        record_metric(self.node_id, "table_action", action)
