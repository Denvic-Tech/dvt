import sqlalchemy as sa
import sqlalchemy.ext.asyncio as asa

from core.types import DBMetadata

from .helpers import _rows_to_db_tables, build_database_db_metadata


async def load_clickhouse_metadata(engine: asa.AsyncEngine) -> DBMetadata:
    async with engine.connect() as conn:
        database_result = await conn.execute(sa.text("""
            SELECT name AS database_name
            FROM system.databases
            WHERE name NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
            ORDER BY name;
        """))
        database_rows = database_result.mappings().all()
        result = await conn.execute(sa.text("""
            SELECT
                c.database AS database_name,
                NULL AS table_schema,
                c.table AS table_name,
                c.name AS column_name,
                -- Извлекаем базовый тип данных, если это Nullable или Enum
                if(startsWith(c.type, 'Nullable'), substring(c.type, 10, length(type) - 10), c.type) AS data_type,
                startsWith(c.type, 'Nullable') AS is_nullable,
                NULL AS udt_name, -- В ClickHouse нет аналога udt_name
                CASE
                    WHEN t.engine = 'View' THEN 'VIEW'
                    WHEN t.engine = 'MaterializedView' THEN 'MATERIALIZED_VIEW'
                    ELSE 'BASE_TABLE'
                END AS table_type,
                -- Извлекаем значения для Enum
                if(
                    position(c.type, 'Enum') > 0,
                    arrayStringConcat(
                        arrayMap(
                            x -> trim(BOTH '''' FROM trim(BOTH ' ' FROM splitByChar('=', x)[1])),
                            splitByChar(',', extract(c.type, 'Enum\\d*\\((.*)\\)'))
                        ),
                        ','
                    ),
                    NULL
                ) AS enum_values
            FROM system.columns c
            JOIN system.tables t 
                ON c.database = t.database 
                AND c.table = t.name
            WHERE c.database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
            ORDER BY c.database, c.table;
        """))
        rows = result.fetchall()
    return build_database_db_metadata(
        dialect="clickhouse",
        database_names=[row["database_name"] for row in database_rows],
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )
