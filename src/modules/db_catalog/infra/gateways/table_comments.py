"""One bounded comment query per catalog page, without reflecting every table."""

import sqlalchemy as sa


def table_comments_statement(dialect: str) -> sa.TextClause | None:
    queries = {
        "postgresql": """
            SELECT c.relname AS name, obj_description(c.oid, 'pg_class') AS comment
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = COALESCE(:schema, current_schema())
              AND c.relname IN :names
        """,
        "mysql": """
            SELECT TABLE_NAME AS name,
                   CASE WHEN TABLE_TYPE = 'BASE TABLE' THEN TABLE_COMMENT END AS comment
            FROM information_schema.tables
            WHERE TABLE_SCHEMA = COALESCE(:schema, :database, DATABASE())
              AND TABLE_NAME IN :names
        """,
        "mssql": """
            SELECT o.name AS name, CAST(ep.value AS NVARCHAR(max)) AS comment
            FROM sys.objects o
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            LEFT JOIN sys.extended_properties ep
              ON ep.class = 1 AND ep.major_id = o.object_id
             AND ep.minor_id = 0 AND ep.name = 'MS_Description'
            WHERE s.name = COALESCE(:schema, SCHEMA_NAME()) AND o.name IN :names
        """,
        "oracle": """
            SELECT table_name AS "name", comments AS "comment"
            FROM all_tab_comments
            WHERE owner = COALESCE(:schema, SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA'))
              AND table_name IN :names
        """,
        "clickhouse": """
            SELECT name, comment FROM system.tables
            WHERE database = coalesce(:schema, :database, currentDatabase())
              AND name IN :names
        """,
    }
    dialect = {"mariadb": "mysql", "sqlserver": "mssql"}.get(dialect, dialect)
    query = queries.get(dialect)
    if query is None:
        return None
    return sa.text(query).bindparams(sa.bindparam("names", expanding=True))
