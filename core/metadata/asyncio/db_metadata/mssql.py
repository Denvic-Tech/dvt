import sqlalchemy as sa
import sqlalchemy.ext.asyncio as asa

from core.types import DBMetadata

from .helpers import _rows_to_db_tables, build_database_schema_db_metadata


async def load_mssql_metadata(engine: asa.AsyncEngine) -> DBMetadata:
    async with engine.connect() as conn:
        schema_result = await conn.execute(sa.text("""
            SELECT
                DB_NAME() AS database_name,
                SCHEMA_NAME
            FROM INFORMATION_SCHEMA.SCHEMATA
            WHERE SCHEMA_NAME NOT IN ('guest', 'INFORMATION_SCHEMA', 'sys')
            ORDER BY SCHEMA_NAME;
        """))
        schema_rows = schema_result.mappings().all()
        result = await conn.execute(sa.text("""
            SELECT
                DB_NAME() AS database_name,
                t.TABLE_SCHEMA AS table_schema,
                t.TABLE_NAME AS table_name,
                c.COLUMN_NAME AS column_name,
                c.DATA_TYPE AS data_type,
                c.IS_NULLABLE AS is_nullable,
                c.DOMAIN_NAME AS udt_name, -- Показывает пользовательский тип данных, если он используется
                t.TABLE_TYPE AS table_type,
                NULL AS enum_values -- В MSSQL нет прямого аналога ENUM
            FROM INFORMATION_SCHEMA.COLUMNS c
            JOIN INFORMATION_SCHEMA.TABLES t
                ON c.TABLE_SCHEMA = t.TABLE_SCHEMA
                AND c.TABLE_NAME = t.TABLE_NAME
            WHERE t.TABLE_SCHEMA NOT IN ('guest', 'INFORMATION_SCHEMA', 'sys')
            ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME;
        """))
        rows = result.fetchall()
    database_names = sorted({row["database_name"] for row in schema_rows if row["database_name"]})
    if not database_names and engine.url.database:
        database_names = [engine.url.database]
    schema_names_by_database = {
        db_name: [row["SCHEMA_NAME"] for row in schema_rows if row["database_name"] == db_name]
        for db_name in database_names
    }
    return build_database_schema_db_metadata(
        dialect="mssql",
        database_names=database_names,
        schema_names_by_database=schema_names_by_database,
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )
