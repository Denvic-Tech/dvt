"""Row count of one table read from DBMS system catalogs, never by scanning the table."""

import sqlalchemy as sa

# dialect -> (query, whether the catalog value is exact rather than a planner estimate)
_QUERIES: dict[str, tuple[str, bool]] = {
    # reltuples is refreshed by ANALYZE/autovacuum; -1 means "never analyzed" (PG14+).
    # A partitioned parent keeps no statistics of its own, so its leaf partitions are summed.
    "postgresql": (
        """
        WITH RECURSIVE target AS (
            SELECT c.oid, c.relkind, c.reltuples
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = COALESCE(CAST(:schema AS TEXT), current_schema())
              AND c.relname = CAST(:name AS TEXT)
              AND c.relkind IN ('r', 'm', 'p')
        ), tree AS (
            SELECT oid, relkind, reltuples FROM target
            UNION ALL
            SELECT c.oid, c.relkind, c.reltuples
            FROM tree t
            JOIN pg_catalog.pg_inherits i ON i.inhparent = t.oid
            JOIN pg_catalog.pg_class c ON c.oid = i.inhrelid
            WHERE t.relkind = 'p'
        )
        SELECT CASE WHEN bool_or(reltuples < 0) THEN NULL
                    ELSE CAST(sum(reltuples) AS BIGINT) END AS row_count
        FROM tree
        WHERE relkind <> 'p'
        """,
        False,
    ),
    "mysql": (
        """
        SELECT TABLE_ROWS AS row_count
        FROM information_schema.tables
        WHERE TABLE_SCHEMA = COALESCE(:schema, :database, DATABASE())
          AND TABLE_NAME = :name
          AND TABLE_TYPE = 'BASE TABLE'
        """,
        False,
    ),
    # sys.partitions needs no VIEW DATABASE STATE; Microsoft documents rows as approximate.
    "mssql": (
        """
        SELECT SUM(p.rows) AS row_count
        FROM sys.objects o
        JOIN sys.schemas s ON s.schema_id = o.schema_id
        JOIN sys.partitions p ON p.object_id = o.object_id AND p.index_id IN (0, 1)
        WHERE s.name = COALESCE(:schema, SCHEMA_NAME())
          AND o.name = :name
          AND o.type = 'U'
        """,
        False,
    ),
    # num_rows is NULL until optimizer statistics are gathered.
    "oracle": (
        """
        SELECT num_rows AS "row_count"
        FROM all_tables
        WHERE owner = COALESCE(:schema, SYS_CONTEXT('USERENV', 'CURRENT_SCHEMA'))
          AND table_name = :name
        """,
        False,
    ),
    # total_rows is exact where the engine tracks it (MergeTree family, Memory, Log) else NULL.
    "clickhouse": (
        """
        SELECT total_rows AS row_count
        FROM system.tables
        WHERE database = coalesce(:schema, :database, currentDatabase())
          AND name = :name
        """,
        True,
    ),
}


def table_row_count_statement(dialect: str) -> tuple[sa.TextClause, bool] | None:
    """Return the catalog query (binds: name, schema, database) and its exactness flag."""
    dialect = {"mariadb": "mysql", "sqlserver": "mssql"}.get(dialect, dialect)
    entry = _QUERIES.get(dialect)
    if entry is None:
        return None
    query, exact = entry
    return sa.text(query), exact
