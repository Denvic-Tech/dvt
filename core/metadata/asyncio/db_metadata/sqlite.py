from typing import Optional

import sqlalchemy as sa
import sqlalchemy.ext.asyncio as asa

from core.types import DBTableType, DBTable, DBColumn, DataType, DBMetadata


def _quote_sqlite_ident(value: str) -> str:
    # SQLite identifiers экранируются двойными кавычками
    return '"' + value.replace('"', '""') + '"'


def _normalize_sqlite_type(type_name: Optional[str]) -> str:
    return (type_name or "").strip().upper()


def _sqlite_decltype_to_python(type_name: Optional[str]) -> type:
    """
    SQLite type affinity mapping.
    При желании можно заменить на более точный mapper.
    """
    t = _normalize_sqlite_type(type_name)

    if "INT" in t:
        return int
    if any(x in t for x in ("CHAR", "CLOB", "TEXT", "VARCHAR")):
        return str
    if "BLOB" in t or t == "":
        return bytes
    if any(x in t for x in ("REAL", "FLOA", "DOUB")):
        return float
    if any(x in t for x in ("NUMERIC", "DECIMAL", "BOOLEAN", "DATE", "DATETIME")):
        # тут можно выбрать Decimal / bool / str / datetime в зависимости от твоей модели
        return str

    return str


async def _get_sqlite_schemas(conn: asa.AsyncConnection) -> list[str]:
    rows = (
        await conn.execute(sa.text("PRAGMA database_list"))
    ).mappings().all()

    # PRAGMA database_list -> seq, name, file
    return [row["name"] for row in rows]


async def _get_sqlite_tables_and_views(
    conn: asa.AsyncConnection,
    schema_name: str,
) -> list[tuple[str, DBTableType]]:
    schema = _quote_sqlite_ident(schema_name)

    rows = (
        await conn.execute(
            sa.text(f"""
                SELECT name, type
                FROM {schema}.sqlite_master
                WHERE type IN ('table', 'view')
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
        )
    ).mappings().all()

    result: list[tuple[str, DBTableType]] = []
    for row in rows:
        obj_type = DBTableType.VIEW if row["type"] == "view" else DBTableType.BASE_TABLE
        result.append((row["name"], obj_type))
    return result


async def _get_sqlite_temp_objects(
    conn: asa.AsyncConnection,
) -> list[tuple[str, DBTableType]]:
    rows = (
        await conn.execute(
            sa.text("""
                SELECT name, type
                FROM sqlite_temp_master
                WHERE type IN ('table', 'view')
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """)
        )
    ).mappings().all()

    return [(row["name"], DBTableType.TEMPORARY) for row in rows]


async def _get_sqlite_table_columns(
    conn: asa.AsyncConnection,
    schema_name: str,
    table_name: str,
) -> list[dict]:
    schema = _quote_sqlite_ident(schema_name)
    table = _quote_sqlite_ident(table_name)

    rows = (
        await conn.execute(sa.text(f"PRAGMA {schema}.table_info({table})"))
    ).mappings().all()

    # table_info -> cid, name, type, notnull, dflt_value, pk
    return list(rows)


async def _get_sqlite_indexes(
    conn: asa.AsyncConnection,
    schema_name: str,
    table_name: str,
) -> dict[str, list[str]]:
    schema = _quote_sqlite_ident(schema_name)
    table = _quote_sqlite_ident(table_name)

    index_rows = (
        await conn.execute(sa.text(f"PRAGMA {schema}.index_list({table})"))
    ).mappings().all()

    # Вернем mapping: column_name -> [index_name, ...]
    column_to_indexes: dict[str, list[str]] = {}

    for index_row in index_rows:
        index_name = index_row["name"]
        if not index_name:
            continue

        index_ident = _quote_sqlite_ident(index_name)
        index_info_rows = (
            await conn.execute(sa.text(f"PRAGMA {schema}.index_info({index_ident})"))
        ).mappings().all()

        for col_row in index_info_rows:
            col_name = col_row["name"]
            if not col_name:
                continue
            column_to_indexes.setdefault(col_name, []).append(index_name)

    return column_to_indexes


async def _load_sqlite_table_async(
    conn: asa.AsyncConnection,
    table_name: str,
    database_name: Optional[str],
    schema_name: Optional[str],
    table_type: DBTableType,
) -> DBTable:
    columns_info = await _get_sqlite_table_columns(conn, schema_name or "main", table_name)

    column_to_indexes: dict[str, list[str]] = {}
    if table_type != DBTableType.VIEW:
        column_to_indexes = await _get_sqlite_indexes(conn, schema_name or "main", table_name)

    columns: list[DBColumn] = []

    for column in columns_info:
        col_name = column["name"]
        decl_type = column["type"]
        index_names = column_to_indexes.get(col_name, [])

        # Можно использовать свой mapper, если он умеет работать с SQLite decltype строкой
        py_type = _sqlite_decltype_to_python(decl_type)

        columns.append(
            DBColumn(
                name=col_name,
                dtype=DataType.from_type(py_type),
                nullable=not bool(column["notnull"]),
                index=bool(index_names),
                indexes=index_names or None,
                primary_key=bool(column["pk"]),
            )
        )

    return DBTable(
        schema_name=None if schema_name in (None, "main") else schema_name,
        database_name=database_name,
        name=table_name,
        columns=columns,
        type=table_type,
    )


async def load_sqlite_metadata(engine: asa.AsyncEngine) -> DBMetadata:
    database_name = engine.url.database
    tables: list[DBTable] = []

    async with engine.connect() as conn:
        schema_names = await _get_sqlite_schemas(conn)

        for schema_name in schema_names:
            objects = await _get_sqlite_tables_and_views(conn, schema_name)
            for object_name, table_type in objects:
                tables.append(
                    await _load_sqlite_table_async(
                        conn=conn,
                        table_name=object_name,
                        database_name=database_name,
                        schema_name=schema_name,
                        table_type=table_type,
                    )
                )

        temp_objects = await _get_sqlite_temp_objects(conn)
        for object_name, table_type in temp_objects:
            tables.append(
                await _load_sqlite_table_async(
                    conn=conn,
                    table_name=object_name,
                    database_name=database_name,
                    schema_name="temp",
                    table_type=table_type,
                )
            )

    return DBMetadata(
        dialect="sqlite",
        tables=tables,
        database_name=database_name,
        connection_string=engine.url.render_as_string(),
    )
