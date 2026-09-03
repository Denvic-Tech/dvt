from typing import Literal, Optional

from dask import dataframe as dd
from sqlalchemy import Engine

from src.node_dsl import BaseNode, InputField
from src.node_dsl.node_typing import IO


DIALECT_SA_TO_SG = {
    "postgresql": "postgres",
    "mssql": "tsql",
    "sqlserver": "tsql",
}


class WriteDataFrameToDB(BaseNode):
    TITLE = "Write DataFrame To DB"
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
    write_mode: Literal["append", "truncate", "recreate"] = InputField(
        default="append",
        description="Mode for writing to the table: 'truncate' truncates the table, 'append' adds data, 'recreate' drops and creates the table again.",
    )
    min_batch_rows: Optional[int] = InputField(default=5000, min_value=1, max_value=100000)
    use_clickhouse_connect_driver: Optional[bool] = InputField(default=True)
    create_table_sql: Optional[str] = InputField(default=None)

    async def process(self):
        raise RuntimeError(f"Нода устарела и будет удалена, пожалуйста, используйте ноду 'Write DataFrame To DB V3'")

    async def process_metadata(self):
        raise RuntimeError(f"Нода устарела и будет удалена, пожалуйста, используйте ноду 'Write DataFrame To DB V3'")
