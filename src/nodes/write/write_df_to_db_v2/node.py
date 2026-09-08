from dataclasses import dataclass
from typing import Literal, Optional

from dask import dataframe as dd
from sqlalchemy import Engine, Table

from src.node_dsl import BaseNode, InputField
from src.node_dsl.node_typing import IO


@dataclass
class WriteContext:
    """Подготовленный контекст записи без выполнения DDL/DML."""

    mode: Literal["append", "truncate"]
    resolved_table_name: str
    table_exists: bool
    table: Table | None


@dataclass
class ExecutionPlan:
    """План выполнения операций записи для выбранного режима."""

    should_drop: bool
    should_create: bool
    use_temp_replace: bool
    should_insert: bool


class WriteDataFrameToDBV2(BaseNode):
    TITLE = "Write DataFrame To DB V2"
    EMOJI = "✍️"
    CATEGORY = "Writing"
    OUTPUT_NODE = True
    TAGS = ["Deprecated"]

    connection: Engine = InputField()
    database_name: Optional[str] = InputField()
    df: dd.DataFrame = InputField()
    table_name: str = InputField()
    schema_name: Optional[str] = InputField()
    chunksize: Optional[int] = InputField(default=1000, min_value=1, max_value=1_000_000)
    index_col: IO.COLUMN_NAME = InputField()
    write_mode: Literal["append", "truncate"] = InputField(
        default="append",
        description="Mode for writing to the table: 'truncate' truncates the table, 'append' adds data",
    )
    min_batch_rows: Optional[int] = InputField(default=5000, min_value=1, max_value=100000)
    use_clickhouse_connect_driver: Optional[bool] = InputField(default=True)

    async def process(self):
        raise RuntimeError(f"Нода устарела, пожалуйста, используйте ноду 'Write DataFrame To DB V3'")

    async def process_metadata(self):
        raise RuntimeError(f"Нода устарела, пожалуйста, используйте ноду 'Write DataFrame To DB V3'")