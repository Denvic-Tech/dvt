from typing import Optional

import sqlalchemy as sa
from dask import dataframe as dd
from pydantic import BaseModel, Field
from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from core.db.connect.sqlalchemy_url import split_backend_and_driver, with_database
from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.resolver import resolve_executor, resolve_planner
from core.metadata import get_df_metadata, load_db_table_metadata
from core.types import DataFrameMetadata

from src.logger import logger
from src.models.time_zone import TimeZone
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.node_typing import IO
from src.node_dsl.runtime.connections import (
    resolve_sql_connection_url,
    resolve_sql_dialect_name,
)
from src.node_dsl.types import NodeMetadata
from src.node_dsl.variables import is_unresolved_value

import config


def _convert_url_driver(url: URL, *, is_async: bool) -> URL:  # TODO: вынести в shared/предметную область  # noqa: PLR0911
    backend, driver = split_backend_and_driver(url)

    if is_async:
        if backend == "postgresql":
            # psycopg уже умеет async, asyncpg тоже async
            new_driver = driver if driver in {"asyncpg", "psycopg"} else "asyncpg"
            return url.set(drivername=f"{backend}+{new_driver}")

        if backend in {"mysql", "mariadb"}:
            new_driver = driver if driver in {"asyncmy", "aiomysql"} else "asyncmy"
            return url.set(drivername=f"{backend}+{new_driver}")

        if backend in {"mssql", "sqlserver"}:
            new_driver = driver if driver == "aioodbc" else "aioodbc"
            # drivername должен быть mssql+...
            return url.set(drivername=f"mssql+{new_driver}")

        if backend == "sqlite":
            return url.set(drivername="sqlite+aiosqlite")

        if backend == "oracle":
            # Для oracle+oracledb create_async_engine сам выбирает async dialect.
            # oracle+oracledb_async тоже допустим, но не обязателен.
            if driver in {None, "oracledb", "oracledb_async"}:
                return url.set(drivername="oracle+oracledb")
            if driver == "cx_oracle":
                raise ValueError(
                    "Async Oracle engine requires python-oracledb. "
                    "URL with 'oracle+cx_oracle' cannot be converted to async automatically."
                )
            return url.set(drivername="oracle+oracledb")

        if backend == "clickhouse":
            # third-party dialect logic
            if driver == "asynch":
                return url
            # если драйвер не указан, clickhouse-sqlalchemy считает http дефолтом
            return url.set(drivername="clickhouse+asynch")

        raise NotImplementedError(
            f"Async engine conversion is not implemented for dialect '{backend}'"
        )

    # sync mode
    if backend == "postgresql":
        if driver == "asyncpg":
            return url.set(drivername="postgresql+psycopg2")
        if driver == "psycopg":
            return url.set(drivername="postgresql+psycopg")
        return url

    if backend in {"mysql", "mariadb"}:
        if driver in {"asyncmy", "aiomysql"}:
            return url.set(drivername=f"{backend}+pymysql")
        return url

    if backend in {"mssql", "sqlserver"}:
        if driver == "aioodbc":
            return url.set(drivername="mssql+pyodbc")
        return url

    if backend == "sqlite":
        if driver == "aiosqlite":
            return url.set(drivername="sqlite+pysqlite")
        return url.set(drivername="sqlite+pysqlite") if driver is None else url

    if backend == "oracle":
        # sync oracle+oracledb валиден как есть
        if driver == "oracledb_async":
            return url.set(drivername="oracle+oracledb")
        return url

    if backend == "clickhouse":
        if driver == "asynch":
            return url.set(drivername="clickhouse+http")
        return url

    return url


class SystemVariables(BaseModel):
    source_table_name: str = Field(..., description="Source table name")
    source_schema_name: str | None = Field(..., description="Source schema name")
    source_db_name: str | None = Field(..., description="Source database name")


class ReadTableFromDBV3(DFOutputBaseNode):
    TITLE = "Read Table DB V3"
    EMOJI = "📋"
    CATEGORY = "Extraction"
    SYSTEM_VARIABLES_MODEL = SystemVariables
    METADATA_VARIABLE_PREPASS_INPUTS = frozenset({"table_name", "database_name", "schema_name"})
    TTL_CACHE: int | None = InputField(default=0, description="Время жизни кеша", min_value=0)

    connection: SqlConnectionRecord | Engine = InputField()
    table_name: str = InputField()
    database_name: str | None = InputField()
    schema_name: str | None = InputField()
    columns: list[IO.COLUMN_NAME] | None = InputField(
        description=(
            "Explicit non-empty columns list to read. Pass every column returned by the table "
            "catalog to read the whole table; do not use null to represent 'all columns' in a "
            "persisted graph."
        )
    )
    limit: int | None = InputField(min_value=1, max_value=1000000)
    time_zone: TimeZone | None = InputField()
    partition_col: Optional[IO.COLUMN_NAME] = InputField(
        description=(
            "Required for deterministic read_v3 execution. Use the exact raw catalog column "
            "name without SQL quotes or backticks; choose a stable non-null scalar column."
        )
    )
    partition_grouping: Optional[IO.DICT] = InputField(
        description=(
            "Optional custom partition grouping. Configure it only when column type, cardinality, "
            "and data distribution justify a non-default range/hash/grouping strategy."
        )
    )
    npartitions: int | None = InputField(min_value=1)
    max_rows_per_partition: int | None = InputField(min_value=1)

    output: dd.DataFrame = OutputField()

    def _metadata_target_fields_unresolved(self) -> list[str]:
        unresolved_fields: list[str] = []
        for field_name in ("table_name", "database_name", "schema_name"):
            value = getattr(self, field_name, None)
            if is_unresolved_value(value):
                unresolved_fields.append(field_name)
        return unresolved_fields

    def _can_emit_system_variables(self) -> bool:
        return not self._metadata_target_fields_unresolved()

    def get_dialect_name_for_sql_code_metadata(self) -> str | None:
        return resolve_sql_dialect_name(self.connection)

    def create_new_connection(self, is_async: bool = False) -> Engine | AsyncEngine:
        current = self.connection
        if isinstance(current, AsyncEngine):
            base_url = current.url
        else:
            base_url = resolve_sql_connection_url(current)
            if isinstance(base_url, str):
                base_url = sa.make_url(base_url)
        new_url = with_database(base_url, self.database_name)
        new_url = _convert_url_driver(new_url, is_async=is_async)

        if is_async:
            return create_async_engine(new_url)

        return create_engine(new_url)

    def process(self):
        engine = self.create_new_connection()

        planner = resolve_planner(mode="table")
        plan = planner.build_plan(
            engine=engine,
            table_name=self.table_name,
            schema=self.schema_name,
            columns=self.columns,
            partition_col=self.partition_col,
            partition_grouping=self.partition_grouping,
            npartitions=self.npartitions,
            limit=self.limit,
            max_rows_per_partition=self.max_rows_per_partition,
            min_rows_per_partition=config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
            target_partition_mem_mb=config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
            partitioning_overhead_coef=config.DASK_PARTITIONING.OVERHEAD_COEF,
            max_partitions=config.DASK_PARTITIONING.MAX_PARTITIONS,
            datetime_precision=self.execution_settings.datetime_precision,
        )
        executor = resolve_executor(engine)
        self.output = frame_from_executor(executor, plan)
        self.emit_system_variables(SystemVariables(
            source_table_name=self.table_name,
            source_schema_name=self.schema_name,
            source_db_name=self.database_name,
        ))

    async def process_metadata(self) -> None:
        metadata = await self.resolve_metadata()
        output_metadata = metadata.get("output")
        if not isinstance(output_metadata, DataFrameMetadata):
            raise TypeError("ReadTableFromDBV3 expected DataFrameMetadata for output")
        self.output = self.build_empty_ddf_from_metadata(output_metadata)
        if self._can_emit_system_variables():
            self.emit_system_variables(SystemVariables(
                source_table_name=self.table_name,
                source_schema_name=self.schema_name,
                source_db_name=self.database_name,
            ))

    def infer_metadata(self) -> NodeMetadata:
        if isinstance(self.output, dd.DataFrame):
            return {"output": get_df_metadata(self.output)}

        unresolved_fields = self._metadata_target_fields_unresolved()
        if unresolved_fields:
            logger.warning(
                "ReadTableFromDBV3 metadata is unavailable because target fields are unresolved: {}",
                unresolved_fields,
            )
            return {"output": DataFrameMetadata(columns=[])}

        engine = self.create_new_connection()
        try:
            table = load_db_table_metadata(
                engine,
                table_name=self.table_name,
                schema_name=self.schema_name,
                database_name=self.database_name,
            )
            dialect = engine.dialect.name.lower()
            normalized_columns = []
            for column in table.columns:
                if dialect == "postgresql":
                    index = bool(column.index or column.primary_key)
                elif dialect == "sqlite":
                    index = bool(column.index)
                else:
                    index = False
                normalized_columns.append(column.model_copy(update={"index": index}))

            columns = (
                [column for column in normalized_columns if column.name in self.columns]
                if self.columns
                else normalized_columns
            )
            return {"output": DataFrameMetadata(columns=columns)}
        except ValueError as exc:
            raise ValueError("No matched table from engine") from exc
        finally:
            engine.dispose()
