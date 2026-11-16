from typing import Any

from dask import dataframe as dd
from sqlalchemy import Engine

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.query_metadata import describe_query_columns
from core.db.read_v3.resolver import resolve_executor, resolve_planner
from core.types import Column, DataFrameMetadata, DataType

from src.logger import logger
from src.modules.sql_code_metadata import SQLValidationPolicy
from src.node_dsl import DFOutputBaseNode, InputField, OutputField
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.node_mixins.sql import SQLCodeInputFieldMixin
from src.node_dsl.runtime.connections import resolve_sql_dialect_name, resolve_sql_engine
from src.node_dsl.types import NodeMetadata
from src.node_dsl.variables import is_unresolved_value
from src.nodes.extract._shared.read_concurrency import resolve_read_concurrency

import config


class ReadQueryFromDBV3(
    DFOutputBaseNode,
    SQLCodeInputFieldMixin,
):
    TITLE = "Read Query DB V3"
    ICON_KEY = "query-from-db"
    EMOJI = "🔍"
    CATEGORY = "Extraction"
    METADATA_VARIABLE_PREPASS_INPUTS = frozenset({"query"})
    SQL_VALIDATION_POLICY = SQLValidationPolicy(
        allow_multiple_statements=False,
        require_single_result_statement=True,
        allowed_statement_types={"select", "with", "set_operation"},
    )

    connection: SqlConnectionRecord | Engine = InputField(
        agent_description=(
            "Connect a DB_CONNECTION object by an edge. Choose this reader only when source-side "
            "SQL cannot reasonably be expressed by a table reader and specialized transforms; "
            "explain the reason in the node comment and follow the query README."
        ),
    )
    partition_col: str | None = InputField(
        description="Required column of the query result used for partitioning.",
        agent_description=(
            "Use an exact scalar column exposed by the query result, without SQL quotes. Profile "
            "its type, nulls, cardinality and skew with suggest_read_partitioning (sql_code) and "
            "do not choose a column it excludes; prefer a stable non-null key. Do not assume a "
            "base-table key remains unique or even present after the query's joins and aggregation."
        ),
    )
    partition_grouping: dict[str, Any] | None = InputField(
        description="Custom grouping spec for partitioned reads.",
        agent_description=(
            "Assess the query result size, row width and key distribution, not just base-table "
            "statistics; suggest_read_partitioning ranks ready values. Omit for automatic "
            "range/hash. Use documented formats only; custom groups can override the target "
            "partition count. Record the decision in the node comment."
        ),
    )
    npartitions: int | None = InputField(
        min_value=1,
        agent_description=(
            "Omit for automatic sizing. Fix 1 only after verifying a small narrow result and "
            "considering growth; custom groups or explicit hash buckets may define more segments."
        ),
    )
    limit: int | None = InputField(
        min_value=1, max_value=1000000,
        agent_description=(
            "Omit for full results. Set only when a limited read is intended; do not silently "
            "truncate a business report to speed up execution."
        ),
    )
    max_rows_per_partition: int | None = InputField(
        min_value=1,
        agent_description=(
            "Custom partition_grouping groups above this row ceiling are split into key-hash "
            "sub-segments of about 80% of it. Planning fails before reading when an oversized "
            "group cannot be split (null group, single key value, partition limit). Hashing "
            "cannot spread one key value repeated more often than the ceiling inside a prefix, "
            "period or range group, and range/hash segments are not split: on ClickHouse planning "
            "fails when one key value or the null group exceeds the ceiling, other sources fail "
            "while reading. Check key skew before selecting a limit and review available "
            "execution diagnostics."
        ),
    )
    max_concurrent_queries: int | None = InputField(
        default=None,
        min_value=1,
        description="Partition queries of this reader running at once; omit for the default.",
        agent_description=(
            "Normally omit: the instance applies a per-database-type default that protects the "
            "source and avoids driver thread contention. Set only after measuring this source: "
            "more queries can speed up server-bound sources but slow GIL-bound drivers such as "
            "psycopg or pyodbc and load the source. Each partition runs the query separately, "
            "so this also bounds concurrent evaluations of the query. It limits this reader only "
            "and does not change partitioning, rows read or the downstream thread pool."
        ),
    )

    output: dd.DataFrame = OutputField()

    _METADATA_SAMPLE_ROWS = 1000

    def _get_engine(self) -> Engine:
        return resolve_sql_engine(self.connection)

    def get_dialect_name_for_sql_code_metadata(self) -> str | None:
        return resolve_sql_dialect_name(self.connection)

    def process(self):
        raw_query = self.sql_code.strip().rstrip(";")
        engine = self._get_engine()
        planner = resolve_planner(mode="query")
        plan = planner.build_plan(
            engine=engine,
            query=raw_query,
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
            key_skew_check=config.DASK_PARTITIONING.READ_V3_KEY_SKEW_CHECK,
        )
        executor = resolve_executor(
            engine,
            max_concurrent_queries=resolve_read_concurrency(self.max_concurrent_queries, engine),
        )
        self.output = frame_from_executor(executor, plan)

    async def process_metadata(self) -> None:
        metadata = await self.resolve_metadata()
        output_metadata = metadata.get("output")
        
        if not isinstance(output_metadata, DataFrameMetadata):
            raise TypeError(f"{self.__class__.__name__} node expected {DataFrameMetadata.__class__.__name__} for output")
        
        self.output = self.build_empty_ddf_from_metadata(output_metadata)

    def infer_metadata(self) -> NodeMetadata:
        if not isinstance(self.sql_code, str) or is_unresolved_value(self.sql_code):
            logger.warning(
                "ReadQueryFromDBV3 metadata is unavailable because query is unresolved: {}",
                getattr(self.sql_code, "reason", "query is not a string"),
            )
            return {"output": DataFrameMetadata(columns=[])}

        raw_query = self.sql_code.strip().rstrip(";")
        if not raw_query:
            logger.warning("ReadQueryFromDBV3 metadata is unavailable because query is empty.")
            return {"output": DataFrameMetadata(columns=[])}
        described_columns = describe_query_columns(self._get_engine(), raw_query)
        if not described_columns:
            return {"output": DataFrameMetadata(columns=[])}

        columns_meta = []
        for column_name, type_repr in described_columns:
            columns_meta.append(
                Column(
                    name=str(column_name),
                    dtype=DataType.from_type(str(type_repr).lower()),
                    nullable=True,
                    index=False,
                )
            )

        return {"output": DataFrameMetadata(columns=columns_meta)}
