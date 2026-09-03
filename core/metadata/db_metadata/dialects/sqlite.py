from typing import Optional

import sqlalchemy as sa

from core.mapper import sa2py_types
from core.types import DBTableType, DBTable, DBColumn, DataType, DBMetadata


def _load_sqlite_table(
        inspector: sa.Inspector,
        table_name: str,
        database_name: Optional[str],
        schema_name: Optional[str],
        table_type: DBTableType,
) -> DBTable:
    columns = []
    primary_keys = set(
        inspector.get_pk_constraint(table_name, schema=schema_name).get("constrained_columns") or []
    )
    indexes = []

    if table_type != DBTableType.VIEW:
        indexes = inspector.get_indexes(table_name, schema=schema_name)

    for column in inspector.get_columns(table_name, schema=schema_name):
        index_names = [
            index["name"]
            for index in indexes
            if index.get("name") and column["name"] in (index.get("column_names") or [])
        ]
        py_type = sa2py_types.get_py_type(column["type"])
        columns.append(
            DBColumn(
                name=column["name"],
                dtype=DataType.from_type(py_type),
                nullable=bool(column.get("nullable", True)),
                index=bool(index_names),
                indexes=index_names or None,
                primary_key=column["name"] in primary_keys,
            )
        )

    return DBTable(
        schema_name=None if schema_name in (None, "main") else schema_name,
        database_name=database_name,
        name=table_name,
        columns=columns,
        type=table_type,
    )


def load_sqlite_metadata(engine: sa.Engine) -> DBMetadata:
    inspector = sa.inspect(engine)
    database_name = engine.url.database
    tables = []

    for schema_name in inspector.get_schema_names():
        for table_name in inspector.get_table_names(schema=schema_name):
            tables.append(
                _load_sqlite_table(
                    inspector=inspector,
                    table_name=table_name,
                    database_name=database_name,
                    schema_name=schema_name,
                    table_type=DBTableType.BASE_TABLE,
                )
            )
        for view_name in inspector.get_view_names(schema=schema_name):
            tables.append(
                _load_sqlite_table(
                    inspector=inspector,
                    table_name=view_name,
                    database_name=database_name,
                    schema_name=schema_name,
                    table_type=DBTableType.VIEW,
                )
            )

    for table_name in inspector.get_temp_table_names():
        tables.append(
            _load_sqlite_table(
                inspector=inspector,
                table_name=table_name,
                database_name=database_name,
                schema_name="temp",
                table_type=DBTableType.TEMPORARY,
            )
        )
    for view_name in inspector.get_temp_view_names():
        tables.append(
            _load_sqlite_table(
                inspector=inspector,
                table_name=view_name,
                database_name=database_name,
                schema_name="temp",
                table_type=DBTableType.TEMPORARY,
            )
        )

    return DBMetadata(
        dialect="sqlite",
        tables=tables,
        database_name=database_name,
        connection_string=engine.url.render_as_string(),
    )
