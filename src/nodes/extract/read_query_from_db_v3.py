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

import config


class ReadQueryFromDBV3(
    DFOutputBaseNode,
    SQLCodeInputFieldMixin,
):
    TITLE = "Read Query DB V3"
    EMOJI = "🔍"
    CATEGORY = "Extraction"
    METADATA_VARIABLE_PREPASS_INPUTS = frozenset({"query"})
    SQL_VALIDATION_POLICY = SQLValidationPolicy(
        allow_multiple_statements=False,
        require_single_result_statement=True,
        allowed_statement_types={"select", "with", "set_operation"},
    )

    connection: SqlConnectionRecord | Engine = InputField()
    partition_col: str | None = InputField(
        description=(
            "Required. Must be an exact scalar column exposed by the query result. Choose a "
            "stable, preferably non-null and indexed numeric/datetime column without SQL quotes."
        )
    )
    partition_grouping: dict[str, Any] | None = InputField(
        description="Custom grouping spec for partitioned reads."
    )
    npartitions: int | None = InputField(min_value=1)
    limit: int | None = InputField(min_value=1, max_value=1000000)
    max_rows_per_partition: int | None = InputField(min_value=1)

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
        )
        executor = resolve_executor(engine)
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
