"""Lossless, dialect-specific changes to existing column nullability."""

from contextlib import contextmanager

import sqlalchemy as sa
from sqlglot import Dialect
from sqlglot.tokens import TokenType

NULLABLE_DIALECTS = frozenset({"postgresql", "mysql", "mariadb", "mssql", "oracle", "clickhouse"})


def mysql_nullable_definition(definition: str, nullable: bool) -> str:
    """Edit only top-level NULL/NOT NULL and an incompatible DEFAULT NULL."""
    tokens = Dialect.get_or_raise("mysql").tokenize(definition)
    depth = 0
    edits: list[tuple[int, int, str]] = []
    null_clauses = 0
    for i, token in enumerate(tokens):
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and token.token_type == TokenType.NULL:
            previous = tokens[i - 1] if i else None
            if previous is not None and previous.token_type == TokenType.DEFAULT:
                if not nullable:
                    edits.append((previous.start, token.end + 1, ""))
                continue
            start = token.start
            if previous is not None and previous.token_type == TokenType.NOT:
                start = previous.start
            edits.append((start, token.end + 1, "NULL" if nullable else "NOT NULL"))
            null_clauses += 1
    if depth != 0 or null_clauses > 1:
        raise ValueError("Unable to preserve the MySQL column nullability definition.")
    for start, end, replacement in reversed(edits):
        definition = definition[:start] + replacement + definition[end:]
    if not null_clauses:
        definition += " NULL" if nullable else " NOT NULL"
    return definition.strip()


def clickhouse_nullable_type(original: str, nullable: bool) -> str:
    """Keep the exact native type, including precision, enum labels and timezone."""
    if original.startswith("LowCardinality(") and original.endswith(")"):
        return "LowCardinality(" + clickhouse_nullable_type(original[15:-1], nullable) + ")"
    base = original[9:-1] if original.startswith("Nullable(") and original.endswith(")") else original
    if nullable and base.split("(", 1)[0] in {
        "Array", "Tuple", "Map", "Nested", "AggregateFunction", "SimpleAggregateFunction",
        "Object", "JSON", "Variant", "Dynamic",
    }:
        raise ValueError(f"Nullable is not supported for ClickHouse type {base!r}.")
    return f"Nullable({base})" if nullable else base


def load_clickhouse_column_types(engine: sa.Engine, table: sa.Table) -> dict[str, dict]:
    # Reflection in clickhouse-sqlalchemy can lose native type details and does
    # not expose ALIAS/MATERIALIZED. Read authoritative definitions instead.
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text(
                "SELECT name, type, default_kind FROM system.columns "
                "WHERE database = coalesce(:database, currentDatabase()) AND table = :table"
            ),
            {"database": table.schema or engine.url.database, "table": table.name},
        ).mappings()
        return {row["name"]: dict(row) for row in rows}


def build_column_nullable_sql(
    *,
    dialect: sa.engine.Dialect,
    table: sa.Table,
    column: sa.Column,
    nullable: bool,
    mysql_definition: str | None = None,
    clickhouse_definition: dict | None = None,
) -> list[str]:
    name = dialect.name
    if name not in NULLABLE_DIALECTS:
        raise ValueError(f"Changing column nullable is not supported for {name}.")
    if nullable == column.nullable:
        return []
    if column.info.get("computed") or (
        nullable and ("identity" in column.info or column.info.get("autoincrement") is True)
    ):
        raise ValueError(f"Changing nullable is not supported for generated column {column.name!r}.")
    preparer = dialect.identifier_preparer
    full_table = preparer.format_table(table)
    column_name = preparer.quote(column.name)
    if preparer._double_percents:
        full_table = full_table.replace("%%", "%")
        column_name = column_name.replace("%%", "%")
    prefix = f"ALTER TABLE {full_table}"
    null_sql = "NULL" if nullable else "NOT NULL"
    if name == "postgresql":
        return [f"{prefix} ALTER COLUMN {column_name} {'DROP' if nullable else 'SET'} NOT NULL"]
    if name == "oracle":
        return [f"{prefix} MODIFY ({column_name} {null_sql})"]
    if name == "mssql":
        # Use the reflected native SQLAlchemy type, including its collation.
        type_sql = column.type.compile(dialect=dialect)
        if preparer._double_percents:
            type_sql = type_sql.replace("%%", "%")
        return [f"{prefix} ALTER COLUMN {column_name} {type_sql} {null_sql}"]
    if name in {"mysql", "mariadb"}:
        if mysql_definition is None:
            raise ValueError("SHOW CREATE TABLE is required to preserve MySQL column attributes.")
        definition = mysql_nullable_definition(mysql_definition, nullable)
        return [f"{prefix} MODIFY COLUMN {definition}"]
    if not clickhouse_definition:
        raise ValueError(f"Unable to read the native ClickHouse type of {column.name!r}.")
    if clickhouse_definition["default_kind"] in {"ALIAS", "MATERIALIZED"}:
        raise ValueError(f"Changing nullable is not supported for generated column {column.name!r}.")
    type_sql = clickhouse_nullable_type(clickhouse_definition["type"], nullable)
    return [f"{prefix} MODIFY COLUMN {column_name} {type_sql}"]


@contextmanager
def mysql_strict_mode(connection: sa.Connection, *, enabled: bool):
    """Do not allow ALTER to silently replace NULLs, even on non-strict servers."""
    if not enabled:
        yield
        return
    previous = connection.execute(sa.text("SELECT @@SESSION.sql_mode")).scalar_one()
    modes = {mode for mode in previous.split(",") if mode}
    if "STRICT_ALL_TABLES" in modes:
        yield
        return
    connection.execute(
        sa.text("SET SESSION sql_mode = :mode"),
        {"mode": ",".join(sorted(modes | {"STRICT_ALL_TABLES"}))},
    )
    try:
        yield
    finally:
        try:
            connection.execute(sa.text("SET SESSION sql_mode = :mode"), {"mode": previous})
        except Exception:
            # A connection with changed session settings must not reenter the pool.
            connection.invalidate()
            raise
