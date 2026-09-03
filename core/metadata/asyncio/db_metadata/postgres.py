import sqlalchemy as sa
import sqlalchemy.ext.asyncio as asa

from core.types import DBMetadata

from .helpers import _rows_to_db_tables, build_database_schema_db_metadata


async def load_postgresql_metadata(engine: asa.AsyncEngine) -> DBMetadata:
    async with engine.connect() as conn:
        schema_result = await conn.execute(sa.text("""
            SELECT
                current_database() AS database_name,
                schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema', 'pg_catalog')
            ORDER BY schema_name;
        """))
        schema_rows = schema_result.mappings().all()
        result = await conn.execute(sa.text("""
            SELECT
                current_database() AS database_name,
                c.table_schema, 
                c.table_name, 
                c.column_name, 
                c.data_type, 
                c.is_nullable,
                c.udt_name,
                t.table_type,
                pg_enum_info.enum_values,

                -- Список индексов, в которых участвует колонка
                COALESCE(
                    string_agg(DISTINCT idx.index_name || ' [' || idx.index_type || ']', ', '),
                    ''
                ) AS indexes,

                -- Флаг: колонка является частью PRIMARY KEY
                CASE 
                    WHEN EXISTS (
                        SELECT 1
                        FROM pg_constraint con
                        JOIN pg_class tb ON con.conrelid = tb.oid
                        JOIN pg_attribute att ON att.attrelid = tb.oid 
                                              AND att.attnum = ANY(con.conkey)
                        WHERE con.contype = 'p'
                          AND tb.relname = c.table_name
                          AND att.attname = c.column_name
                          AND tb.relnamespace = (
                              SELECT oid FROM pg_namespace WHERE nspname = c.table_schema
                          )
                    ) THEN true
                    ELSE false
                END AS is_primary_key

            FROM information_schema.columns c
            JOIN information_schema.tables t 
                ON c.table_schema = t.table_schema 
                AND c.table_name = t.table_name

            LEFT JOIN (
                SELECT 
                    n.nspname AS enum_schema,
                    t.typname AS enum_name,
                    string_agg(e.enumlabel, ',') AS enum_values
                FROM pg_type t
                JOIN pg_enum e ON t.oid = e.enumtypid
                JOIN pg_namespace n ON n.oid = t.typnamespace
                GROUP BY n.nspname, t.typname
            ) AS pg_enum_info
                ON c.udt_name = pg_enum_info.enum_name
                AND c.table_schema = pg_enum_info.enum_schema

            -- Индексы
            LEFT JOIN (
                SELECT
                    ns.nspname AS schema_name,
                    tb.relname AS table_name,
                    att.attname AS column_name,
                    idx.relname AS index_name,
                    am.amname AS index_type
                FROM pg_class tb
                JOIN pg_index ix ON tb.oid = ix.indrelid
                JOIN pg_class idx ON idx.oid = ix.indexrelid
                JOIN pg_am am ON idx.relam = am.oid
                JOIN pg_attribute att 
                    ON att.attrelid = tb.oid 
                   AND att.attnum = ANY(ix.indkey)
                JOIN pg_namespace ns ON ns.oid = tb.relnamespace
            ) AS idx
                ON idx.schema_name = c.table_schema
               AND idx.table_name = c.table_name
               AND idx.column_name = c.column_name

            WHERE c.table_schema NOT IN ('information_schema', 'pg_catalog')
            GROUP BY 
                c.table_schema, c.table_name, c.column_name,
                c.data_type, c.is_nullable, c.udt_name, t.table_type, pg_enum_info.enum_values
            ORDER BY c.table_schema, c.table_name;
        """))

        rows = result.fetchall()

    database_names = sorted({row["database_name"] for row in schema_rows if row["database_name"]})
    if not database_names and engine.url.database:
        database_names = [engine.url.database]
    schema_names_by_database = {
        db_name: [row["schema_name"] for row in schema_rows if row["database_name"] == db_name]
        for db_name in database_names
    }
    return build_database_schema_db_metadata(
        dialect="postgresql",
        database_names=database_names,
        schema_names_by_database=schema_names_by_database,
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )
