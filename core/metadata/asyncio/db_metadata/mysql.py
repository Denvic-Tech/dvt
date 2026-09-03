import sqlalchemy as sa
import sqlalchemy.ext.asyncio as asa

from core.types import DBMetadata

from .helpers import _rows_to_db_tables, build_schema_db_metadata


async def load_mysql_metadata(engine: asa.AsyncEngine) -> DBMetadata:
    async with engine.connect() as conn:
        schema_result = await conn.execute(sa.text("""
            SELECT SCHEMA_NAME AS schema_name
            FROM information_schema.schemata
            WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            ORDER BY SCHEMA_NAME;
        """))
        schema_rows = schema_result.mappings().all()
        result = await conn.execute(sa.text("""
            SELECT
                c.TABLE_SCHEMA AS database_name,
                c.TABLE_SCHEMA AS table_schema,
                c.TABLE_NAME AS table_name,
                c.COLUMN_NAME AS column_name,
                c.DATA_TYPE AS data_type,
                c.IS_NULLABLE AS is_nullable,
                NULL AS udt_name, -- В MySQL нет прямого аналога udt_name для ENUM
                t.TABLE_TYPE AS table_type,
                CASE
                    WHEN c.DATA_TYPE IN ('enum', 'set')
                    THEN REPLACE(
                            SUBSTRING(c.COLUMN_TYPE, LOCATE('(', c.COLUMN_TYPE) + 1, LOCATE(')', c.COLUMN_TYPE) - LOCATE('(', c.COLUMN_TYPE) - 1),
                            '''', '' -- Убираем одинарные кавычки
                        )
                    ELSE NULL
                END AS enum_values
            FROM information_schema.columns c
            JOIN information_schema.tables t
                ON c.TABLE_SCHEMA = t.TABLE_SCHEMA
                AND c.TABLE_NAME = t.TABLE_NAME
            WHERE c.TABLE_SCHEMA NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
            ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME;
        """))
        rows = result.fetchall()
    return build_schema_db_metadata(
        dialect="mysql",
        schema_names=[row["schema_name"] for row in schema_rows],
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )
