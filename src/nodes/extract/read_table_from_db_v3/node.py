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
from core.types import DataFrameMetadata, DBTable

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
    ICON_KEY = "table-from-db"
    EMOJI = "📋"
    CATEGORY = "Extraction"
    SYSTEM_VARIABLES_MODEL = SystemVariables
    METADATA_VARIABLE_PREPASS_INPUTS = frozenset({"table_name", "database_name", "schema_name"})
    TTL_CACHE: int | None = InputField(
        default=0,
        min_value=0,
        description="Cache lifetime in seconds; 0 disables caching.",
        agent_description=(
            "Keep 0 when verifying current source data. Enable caching only when the requested "
            "freshness allows reuse; a cached result does not verify a fresh source read."
        ),
    )
    connection: SqlConnectionRecord | Engine = InputField(
        description="Database connection.",
        agent_description=(
            "Connect the DB_CONNECTION output of a compatible connection node by an edge. "
            "Do not supply a connection ID or connection_ref to this object port."
        ),
    )
    table_name: str = InputField(
        description="Name of the source table.",
        agent_description=(
            "Resolve the exact table through the connection catalog and get_database_table. "
            "Prefer this reader followed by specialized transforms for ordinary table extraction. "
            "Before configuring a new or changed source, follow the README profiling workflow; "
            "a downstream filter does not reduce the rows fetched by this reader."
        ),
    )
    database_name: str | None = InputField(
        description="Source database; omit to use the connection default.",
        agent_description=(
            "Use a database confirmed by the connection catalog. Do not infer it from a project "
            "name; omitting it uses the connection's database."
        ),
    )
    schema_name: str | None = InputField(
        description="Source schema, when supported by the database.",
        agent_description=(
            "Use the source catalog's schema where applicable. Do not invent a schema for "
            "dialects without schemas or assume every database uses public."
        ),
    )
    columns: list[IO.COLUMN_NAME] | None = InputField(
        description="Columns to read; select every column to read the whole table.",
        agent_description=(
            "Supply an explicit non-empty list of exact catalog column names. When no projection "
            "is requested, list every catalog column. Do not use null to represent all columns "
            "in a persisted graph. Assess the width of this selected projection when sizing reads."
        ),
    )
    limit: int | None = InputField(
        min_value=1,
        max_value=1000000,
        description="Maximum rows to read; omit to read without a row limit.",
        agent_description=(
            "Set only when the task explicitly permits a limited read. Do not silently limit a "
            "full report to make execution cheaper; a limited preview does not establish table size."
        ),
    )
    time_zone: TimeZone | None = InputField(
        description="Time zone; currently not applied by this reader.",
        agent_description=(
            "The current read path does not apply this parameter. Inspect source/output timezone "
            "semantics and use explicit downstream timezone transforms when required."
        ),
    )
    partition_col: Optional[IO.COLUMN_NAME] = InputField(  # noqa: UP045
        description="Column used to split table reading into partitions.",
        agent_description=(
            "Set explicitly in MCP graphs, including one-partition reads. Use the exact raw "
            "catalog column name without SQL quotes or backticks. Assess type, indexes, nulls, "
            "cardinality and skew before choosing a stable scalar key; prefer a non-null indexed "
            "key with enough distinct values. A primary key or date alone does not justify selection."
        ),
    )
    partition_grouping: Optional[IO.DICT] = InputField(  # noqa: UP045
        description="Read partitioning strategy; omit for automatic range/hash selection.",
        agent_description=(
            "Profile the actual read size, selected row width and key distribution before choosing. "
            "Omission deliberately selects automatic range/hash; it does not waive profiling. "
            "Use only grouping formats documented in the README. Range needs an orderable non-null "
            "key; hash does not split identical values or a large null group. For time grouping, "
            "measure rows per candidate period, especially the largest; a reporting month alone "
            "does not justify it. For a verified small read use npartitions=1 without custom groups "
            "or hash buckets. Record evidence, chosen key, strategy and count policy in the node "
            "comment. If profiling fails, record unknowns and prefer automatic sizing with a "
            "verified compatible key; do not claim optimality. Review available partition/memory "
            "diagnostics after execution. Grouping controls physical reads, not business aggregation."
        ),
    )
    npartitions: int | None = InputField(
        min_value=1,
        description="Target partition count; omit for automatic sizing.",
        agent_description=(
            "Normally omit for sizing from rows, selected row width and instance settings. "
            "Use 1 only for a verified small narrow read, for example about 1,000 ordinary rows; "
            "consider future growth for recurring reads. No universal row-count threshold proves "
            "multiple partitions are needed. A partition key is still required. Custom groups or "
            "explicit hash buckets determine segments independently; do not combine conflicting overrides."
        ),
    )
    max_rows_per_partition: int | None = InputField(
        min_value=1,
        description="Row ceiling per segment; exceeding it fails the read.",
        agent_description=(
            "This is a failure guard, not automatic splitting of oversized segments. Assess key "
            "skew before setting a ceiling; choose a better key or grouping when a segment is too large."
        ),
    )

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
        table = load_db_table_metadata(
            engine,
            table_name=self.table_name,
            schema_name=self.schema_name,
            database_name=self.database_name,
        )
        self._remember_source_comments(table)
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
        self._remember_source_comments(output_metadata)
        self.output = self.build_empty_ddf_from_metadata(output_metadata)
        if self._can_emit_system_variables():
            self.emit_system_variables(SystemVariables(
                source_table_name=self.table_name,
                source_schema_name=self.schema_name,
                source_db_name=self.database_name,
            ))

    def _remember_source_comments(self, metadata: DataFrameMetadata | DBTable) -> None:
        self._source_table_comment = metadata.comment
        self._source_column_comments = {
            column.name: column.comment for column in metadata.columns
        }

    def infer_metadata(self) -> NodeMetadata:
        if isinstance(self.output, dd.DataFrame):
            metadata = get_df_metadata(self.output)
            comments = getattr(self, "_source_column_comments", {})
            return {"output": metadata.model_copy(update={
                "comment": getattr(self, "_source_table_comment", None),
                "columns": [
                    column.model_copy(update={"comment": comments.get(column.name)})
                    for column in metadata.columns
                ],
            })}

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
            return {"output": DataFrameMetadata(columns=columns, comment=table.comment)}
        except ValueError as exc:
            raise ValueError("No matched table from engine") from exc
        finally:
            engine.dispose()
