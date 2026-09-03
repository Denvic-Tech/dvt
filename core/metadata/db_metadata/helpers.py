import traceback
import warnings
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.sql import sqltypes

from core.mapper import sa2py_types, sql2sa_types
from core.types import (
    DataType,
    DBColumn,
    DBDatabase,
    DBMetadata,
    DBSchema,
    DBTable,
    DBTableType,
)
from core.types.db_table import DBDialect


def get_sa_type_for_dialect(dialect: str, sql_type: str, **kwargs: Any) -> sqltypes.TypeEngine:  # noqa: PLR0911
    """
    Диспетчер для получения типа SQLAlchemy на основе диалекта и строки типа SQL.
    """
    dialect = dialect.lower()
    try:
        if dialect == "postgresql":
            return sql2sa_types.get_pg_sa_type(sql_type, **kwargs)
        if dialect in ("mysql", "mariadb"):
            return sql2sa_types.get_mysql_sa_type(sql_type, **kwargs)
        if dialect in ("mssql", "sqlserver"):
            return sql2sa_types.get_mssql_sa_type(sql_type, **kwargs)
        if dialect == "clickhouse":
            return sql2sa_types.get_ch_sa_type(sql_type, **kwargs)
        if dialect == "sqlite":
            return sql2sa_types.get_sqlite_sa_type(sql_type, **kwargs)
        if dialect == "oracle":
            return sql2sa_types.get_oracle_sa_type(sql_type, **kwargs)
        warnings.warn(
            f"Unsupported dialect '{dialect}'. Returning Text type as fallback.",
            UserWarning,
        )
        return sa.sql.sqltypes.Text()
    except Exception as ex:
        traceback.print_exc()
        warnings.warn(
            f"Failed to get SQLAlchemy type for '{sql_type}' in dialect '{dialect}': {ex}",
            UserWarning,
        )
        return sa.sql.sqltypes.Text()


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if hasattr(row, key):
        return getattr(row, key)
    if isinstance(row, Mapping):
        return row.get(key, default)
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping.get(key, default)
    return default


def _normalize_indexes(indexes: str | None) -> list[str] | None:
    if not indexes:
        return None
    return [idx.strip() for idx in indexes.split(",") if idx.strip()]


def _row_to_db_column(row: Any, dialect: str) -> DBColumn:
    type_kwargs = {}
    enum_values = _row_get(row, "enum_values")
    udt_name = _row_get(row, "udt_name")
    if enum_values:
        type_kwargs["enum_values"] = enum_values
    if udt_name:
        type_kwargs["udt_name"] = udt_name

    sa_type = get_sa_type_for_dialect(dialect, _row_get(row, "data_type"), **type_kwargs)
    py_type = sa2py_types.get_py_type(sa_type)
    dtype = DataType.from_type(py_type)

    is_nullable_val = _row_get(row, "is_nullable")
    if isinstance(is_nullable_val, str):
        nullable = is_nullable_val.upper() == "YES"
    else:
        nullable = bool(is_nullable_val)

    index_list = _normalize_indexes(_row_get(row, "indexes"))
    return DBColumn(
        name=_row_get(row, "column_name"),
        dtype=dtype,
        nullable=nullable,
        index=bool(index_list),
        indexes=index_list,
        primary_key=_row_get(row, "is_primary_key", False),
    )


def _sort_tables(tables: Sequence[DBTable]) -> list[DBTable]:
    return sorted(
        tables,
        key=lambda table: (
            table.database_name or "",
            table.schema_name or "",
            table.name,
        ),
    )


def _rows_to_db_tables(rows: Sequence[Any], dialect: DBDialect) -> list[DBTable]:
    tables_data: dict[tuple[str | None, str | None, str], dict[str, Any]] = defaultdict(
        lambda: {
            "columns": [],
            "schema": None,
            "database": None,
            "type": None,
        }
    )

    for row in rows:
        table_key = (
            _row_get(row, "database_name"),
            _row_get(row, "table_schema"),
            _row_get(row, "table_name"),
        )
        if table_key[2] is None:
            continue

        table_data = tables_data[table_key]
        if table_data["schema"] is None and table_data["database"] is None:
            table_data["schema"] = _row_get(row, "table_schema")
            table_data["database"] = _row_get(row, "database_name")
            table_data["type"] = DBTableType.from_string(_row_get(row, "table_type", "UNKNOWN"))

        table_data["columns"].append(_row_to_db_column(row, dialect))

    db_tables = [
        DBTable(
            schema_name=schema,
            database_name=database,
            name=name,
            columns=data["columns"],
            type=data["type"] or DBTableType.UNKNOWN,
        )
        for (database, schema, name), data in tables_data.items()
    ]
    return _sort_tables(db_tables)


def build_flat_db_metadata(
    *,
    dialect: DBDialect,
    tables: Sequence[DBTable],
    database_name: str | None = None,
    connection_string: str | None = None,
) -> DBMetadata:
    return DBMetadata(
        dialect=dialect,
        tables=_sort_tables(tables),
        database_name=database_name,
        connection_string=connection_string,
    )


def build_schema_db_metadata(
    *,
    dialect: DBDialect,
    schema_names: Sequence[str],
    tables: Sequence[DBTable],
    database_name: str | None = None,
    connection_string: str | None = None,
) -> DBMetadata:
    tables_by_schema: dict[str, list[DBTable]] = defaultdict(list)
    schema_database_names: dict[str, str | None] = {}

    for table in tables:
        if table.schema_name is None:
            continue
        tables_by_schema[table.schema_name].append(table)
        schema_database_names.setdefault(table.schema_name, table.database_name)

    all_schema_names = set(schema_names)
    all_schema_names.update(table.schema_name for table in tables if table.schema_name is not None)

    schemas = [
        DBSchema(
            name=schema_name,
            database_name=schema_database_names.get(schema_name),
            tables=_sort_tables(tables_by_schema.get(schema_name, [])),
        )
        for schema_name in sorted(all_schema_names)
    ]
    return DBMetadata(
        dialect=dialect,
        schemas=schemas,
        database_name=database_name,
        connection_string=connection_string,
    )


def build_database_db_metadata(
    *,
    dialect: DBDialect,
    database_names: Sequence[str],
    tables: Sequence[DBTable],
    database_name: str | None = None,
    connection_string: str | None = None,
) -> DBMetadata:
    tables_by_database: dict[str, list[DBTable]] = defaultdict(list)
    for table in tables:
        if table.database_name is None:
            continue
        tables_by_database[table.database_name].append(table)

    all_database_names = set(database_names)
    all_database_names.update(
        table.database_name for table in tables if table.database_name is not None
    )

    databases = [
        DBDatabase(
            name=db_name,
            tables=_sort_tables(tables_by_database.get(db_name, [])),
        )
        for db_name in sorted(all_database_names)
    ]
    return DBMetadata(
        dialect=dialect,
        databases=databases,
        database_name=database_name,
        connection_string=connection_string,
    )


def build_database_schema_db_metadata(
    *,
    dialect: DBDialect,
    database_names: Sequence[str],
    schema_names_by_database: Mapping[str, Sequence[str]],
    tables: Sequence[DBTable],
    database_name: str | None = None,
    connection_string: str | None = None,
) -> DBMetadata:
    tables_by_database_schema: dict[tuple[str, str], list[DBTable]] = defaultdict(list)
    for table in tables:
        if table.database_name is None or table.schema_name is None:
            continue
        tables_by_database_schema[(table.database_name, table.schema_name)].append(table)

    all_database_names = set(database_names)
    all_database_names.update(
        table.database_name for table in tables if table.database_name is not None
    )

    databases: list[DBDatabase] = []
    for db_name in sorted(all_database_names):
        schema_names = set(schema_names_by_database.get(db_name, []))
        schema_names.update(
            table.schema_name
            for table in tables
            if table.database_name == db_name and table.schema_name is not None
        )
        schemas = [
            DBSchema(
                name=schema_name,
                database_name=db_name,
                tables=_sort_tables(tables_by_database_schema.get((db_name, schema_name), [])),
            )
            for schema_name in sorted(schema_names)
        ]
        databases.append(DBDatabase(name=db_name, schemas=schemas))

    return DBMetadata(
        dialect=dialect,
        databases=databases,
        database_name=database_name,
        connection_string=connection_string,
    )


def _rows_to_db_metadata(
    dialect: DBDialect,
    rows: Sequence[Any],
    database_name: str | None = None,
    connection_string: str | None = None,
) -> DBMetadata:
    return build_flat_db_metadata(
        dialect=dialect,
        tables=_rows_to_db_tables(rows, dialect),
        database_name=database_name,
        connection_string=connection_string,
    )
