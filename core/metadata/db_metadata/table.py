from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa

from core.mapper import sa2py_types
from core.types import DBColumn, DBTable, DBTableType, DataType


def _safe_inspector_collection(
    loader,
    table_name: str,
    *,
    schema_name: str | None,
) -> list[Mapping[str, Any]]:
    try:
        return list(loader(table_name, schema=schema_name) or [])
    except NotImplementedError:
        return []


def load_db_table_metadata(
    engine: sa.Engine,
    *,
    table_name: str,
    schema_name: str | None = None,
    database_name: str | None = None,
) -> DBTable:
    # Load one table without scanning metadata for the whole database.
    inspector = sa.inspect(engine)
    if not inspector.has_table(table_name, schema=schema_name):
        full_table_name = f'{schema_name}.{table_name}' if schema_name else table_name
        raise ValueError(f'Table {full_table_name!r} does not exist.')

    try:
        primary_key = inspector.get_pk_constraint(table_name, schema=schema_name) or {}
    except NotImplementedError:
        primary_key = {}
    primary_key_columns = set(primary_key.get('constrained_columns') or [])
    indexes = _safe_inspector_collection(
        inspector.get_indexes,
        table_name,
        schema_name=schema_name,
    )

    columns: list[DBColumn] = []
    for column_info in inspector.get_columns(table_name, schema=schema_name):
        column_name = column_info['name']
        index_names = [
            str(index['name'])
            for index in indexes
            if index.get('name')
            and column_name in (index.get('column_names') or [])
        ]
        column_type = column_info.get('type') or sa.NullType()
        columns.append(
            DBColumn(
                name=column_name,
                dtype=DataType.from_type(sa2py_types.get_py_type(column_type)),
                nullable=bool(column_info.get('nullable', True)),
                index=bool(index_names),
                indexes=index_names or None,
                primary_key=column_name in primary_key_columns,
            )
        )

    return DBTable(
        database_name=database_name,
        schema_name=schema_name,
        name=table_name,
        columns=columns,
        type=DBTableType.BASE_TABLE,
    )
