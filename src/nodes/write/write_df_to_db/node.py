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
    ICON_KEY = "write-to-db"
    EMOJI = "✍️"
    CATEGORY = "Writing"
    OUTPUT_NODE = True
    TAGS = ["Deprecated"]

    connection: Engine = InputField(
        agent_description=(
            "Legacy connection input retained for saved graphs. This node always raises a "
            "deprecation error in both full and metadata execution; migrate to a supported writer "
            "using a real SQL connection object."
        ),
    )
    database_name: Optional[str] = InputField(
        agent_description=(
            "Legacy destination-database setting. It is not executed because this node is retired. "
            "During migration, verify the actual database in the saved connection's catalog before "
            "transferring the value."
        ),
    )
    df: dd.DataFrame = InputField(
        agent_description=(
            "Legacy DataFrame input. This node cannot write it; migrate the edge to a supported "
            "writer and validate source dtypes and names against the existing target."
        ),
    )
    table_name: str = InputField(
        agent_description=(
            "Legacy destination-table name. Execution always fails before writing. Resolve the "
            "intended table in the live catalog and map it explicitly when migrating to a "
            "supported writer."
        ),
    )
    schema_name: Optional[str] = InputField(
        agent_description=(
            "Legacy destination-schema setting. Confirm the target dialect's namespace conventions "
            "during migration; this retired node does not perform schema resolution or creation."
        ),
    )
    chunksize: Optional[int] = InputField(
        agent_description=(
            "Legacy insertion batch setting, retained only for compatibility with saved "
            "configurations. It has no runtime effect here. Reassess batching from row width and "
            "driver limits in the replacement writer."
        ),
        default=1000, min_value=1, max_value=1_000_000,
    )
    index_col: IO.COLUMN_NAME = InputField(
        agent_description=(
            "Legacy index-column setting. Inspect whether the intended business key is a DataFrame "
            "column or index when migrating; do not blindly copy this setting into a different "
            "writer's contract."
        ),
    )
    write_mode: Literal["append", "truncate", "recreate"] = InputField(
        agent_description=(
            "Legacy write-intent setting. No mode can make this retired node execute. Preserve the "
            "intended append/replacement semantics when migrating, and verify the replacement "
            "writer's supported modes and target requirements."
        ),
        default="append",
        description="Mode for writing to the table: 'truncate' truncates the table, 'append' adds data, 'recreate' drops and creates the table again.",
    )
    min_batch_rows: Optional[int] = InputField(
        agent_description=(
            "Legacy batch threshold with no effect because execution is disabled. Do not transfer "
            "it blindly; the replacement writer may use a different batching and partition model."
        ),
        default=5000, min_value=1, max_value=100000,
    )
    use_clickhouse_connect_driver: Optional[bool] = InputField(
        agent_description=(
            "Legacy driver-selection flag with no effect because execution is disabled. Use a "
            "supported writer's connection and dialect handling when migrating instead of assuming "
            "this flag is still available."
        ),
        default=True,
    )
    create_table_sql: Optional[str] = InputField(
        agent_description=(
            "Legacy custom table-creation SQL retained in old configurations. This node never "
            "executes it. During migration, review the DDL separately and create the intended "
            "target explicitly; current writers may require a pre-existing table."
        ),
        default=None,
    )

    async def process(self):
        raise RuntimeError(f"Нода устарела и будет удалена, пожалуйста, используйте ноду 'Write DataFrame To DB V3'")

    async def process_metadata(self):
        raise RuntimeError(f"Нода устарела и будет удалена, пожалуйста, используйте ноду 'Write DataFrame To DB V3'")
