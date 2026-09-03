from typing import Optional

from sqlalchemy import MetaData, Engine, Table


def build_table_from_remote_table(
        table_name: str,
        engine: Engine,
        schema: Optional[str] = None,
        extend_existing: bool = True,
) -> Table:
    metadata = MetaData(schema=schema)
    return Table(
        table_name,
        metadata,
        autoload_with=engine,
        extend_existing=extend_existing,
        schema=schema
    )
