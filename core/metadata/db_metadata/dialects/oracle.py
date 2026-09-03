import sqlalchemy as sa

from core.types import DBMetadata

from core.metadata.db_metadata.helpers import _rows_to_db_tables, build_schema_db_metadata


def load_oracle_metadata(engine: sa.Engine) -> DBMetadata:
    """Загрузка метаданных Oracle для текущего пользователя с фильтрацией системных объектов."""
    with engine.connect() as conn:
        schema_rows = conn.execute(sa.text("""
            SELECT USER AS schema_name
            FROM dual
        """)).mappings().all()
        rows = conn.execute(sa.text("""
            SELECT
                USER AS database_name,
                USER AS table_schema,
                tc.table_name AS table_name,
                tc.column_name AS column_name,
                tc.data_type || 
                    CASE 
                        WHEN tc.data_type IN ('VARCHAR2', 'CHAR', 'NVARCHAR2', 'NCHAR') 
                            AND tc.char_length IS NOT NULL 
                            THEN '(' || tc.char_length || ')'
                        WHEN tc.data_type = 'NUMBER' 
                            AND tc.data_precision IS NOT NULL 
                            AND tc.data_scale IS NOT NULL 
                            THEN '(' || tc.data_precision || ',' || tc.data_scale || ')'
                        WHEN tc.data_type = 'NUMBER' 
                            AND tc.data_precision IS NOT NULL 
                            THEN '(' || tc.data_precision || ')'
                        ELSE ''
                    END AS data_type,
                tc.nullable AS is_nullable,
                NULL AS udt_name,
                CASE 
                    WHEN EXISTS (SELECT 1 FROM user_tables t WHERE t.table_name = tc.table_name) 
                    THEN 'BASE TABLE'
                    WHEN EXISTS (SELECT 1 FROM user_views v WHERE v.view_name = tc.table_name)
                    THEN 'VIEW'
                    ELSE 'UNKNOWN'
                END AS table_type,
                NULL AS enum_values
            FROM user_tab_columns tc
            WHERE tc.table_name IN (
                -- Фильтрация по имени таблицы
                SELECT object_name 
                FROM user_objects 
                WHERE object_type IN ('TABLE', 'VIEW')
                  -- Исключаем таблицы, созданные Oracle автоматически
                  AND NOT REGEXP_LIKE(object_name, '^(AQ\\$_|MDRT\\$|MLOG\\$|RUPD\\$|DEF\\$|SYS_|USER_|ALL_|DBA_|LOG|HELP|MVIEW|OL\\$|PRODUCT_PRIVS|REDO|REPL|ROLLING\\$|SCHEDULER)')
                  AND object_name NOT LIKE 'BIN$%'  -- Корзина
                  AND generated = 'N'  -- Не сгенерированные системой
            )
            ORDER BY tc.table_name, tc.column_id
        """)).fetchall()

    return build_schema_db_metadata(
        schema_names=[row["schema_name"] for row in schema_rows],
        tables=_rows_to_db_tables(rows=rows, dialect=engine.dialect.name),
        database_name=engine.url.database,
    )
