"""Dialect-aware column comments and lossless execution of generated DDL."""

from __future__ import annotations

import sqlalchemy as sa
from sqlglot import Dialect
from sqlglot.tokens import TokenType

from core.metadata.db_metadata.comments import normalize_comment

COMMENT_DIALECTS = frozenset({"postgresql", "mysql", "mariadb", "mssql", "oracle", "clickhouse"})


def column_comments_supported(dialect: sa.engine.Dialect) -> bool:
    return dialect.name in COMMENT_DIALECTS and dialect.supports_comments


def require_column_comments(dialect: sa.engine.Dialect) -> None:
    if not column_comments_supported(dialect):
        raise ValueError(f"Column comments are not supported for {dialect.name}.")


def compile_ddl(statement, dialect: sa.engine.Dialect) -> str:
    """Return display/execution SQL, without DBAPI percent escaping."""
    sql = str(statement.compile(dialect=dialect)).strip()
    if dialect.identifier_preparer._double_percents:
        sql = sql.replace("%%", "%")
    return sql


def execute_ddl_sql(connection: sa.Connection, sql: str) -> sa.CursorResult:
    # DDL preserves ':name' in literals (unlike text()) and handles DBAPI percent
    # escaping. Escape its template interpolation first.
    return connection.execute(sa.DDL(sql.replace("%", "%%")))


def _literal(value: str, dialect: sa.engine.Dialect) -> str:
    sql = str(
        sa.literal(value, type_=sa.Unicode()).compile(
            dialect=dialect, compile_kwargs={"literal_binds": True}
        )
    )
    return sql.replace("%%", "%") if dialect.identifier_preparer._double_percents else sql


def _tokenize(sql: str, dialect_name: str):
    name = {"postgresql": "postgres", "mssql": "tsql", "mariadb": "mysql"}.get(
        dialect_name, dialect_name
    )
    return Dialect.get_or_raise(name).tokenize(sql)


def split_ddl_statements(sql: str, dialect_name: str) -> list[str]:
    """Split generated DDL without splitting semicolons inside SQL literals."""
    tokens = _tokenize(sql, dialect_name)
    statements: list[str] = []
    start = 0
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            statement = sql[start : token.start].strip()
            if statement:
                statements.append(statement)
            start = token.end + 1
    remainder = sql[start:].strip()
    if remainder:
        statements.append(remainder)
    return statements


def mysql_column_definition(create_sql: str, column_name: str) -> str:
    """Extract a SHOW CREATE column verbatim, including vendor-specific attributes."""
    tokens = _tokenize(create_sql, "mysql")
    opening = next(
        (i for i, token in enumerate(tokens) if token.token_type == TokenType.L_PAREN),
        None,
    )
    if opening is None:
        raise ValueError("Unable to read the original MySQL column definition.")
    depth = 1
    first = opening + 1
    for i in range(first, len(tokens)):
        token = tokens[i]
        boundary = depth == 1 and token.token_type in {TokenType.COMMA, TokenType.R_PAREN}
        if boundary:
            head = tokens[first] if first < i else None
            if (
                head is not None
                and head.token_type == TokenType.IDENTIFIER
                and head.text == column_name
            ):
                return create_sql[head.start : token.start].strip()
            first = i + 1
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
            if depth == 0:
                break
    raise ValueError(f"Unable to preserve the original definition of column {column_name!r}.")


def mysql_comment_definition(
    definition: str, comment: str | None, dialect: sa.engine.Dialect
) -> str:
    tokens = _tokenize(definition, "mysql")
    depth = 0
    comment_span: tuple[int, int] | None = None
    for i, token in enumerate(tokens):
        if token.token_type == TokenType.L_PAREN:
            depth += 1
        elif token.token_type == TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and token.token_type == TokenType.COMMENT:
            if comment_span is not None or i + 1 >= len(tokens):
                raise ValueError("Ambiguous MySQL column COMMENT definition.")
            value = tokens[i + 1]
            if value.token_type != TokenType.STRING:
                raise ValueError("Unable to preserve the MySQL column COMMENT definition.")
            comment_span = (token.start, value.end + 1)
    replacement = "COMMENT " + _literal(comment or "", dialect)
    if comment_span is None:
        return definition + " " + replacement
    start, end = comment_span
    return definition[:start] + replacement + definition[end:]


def build_column_comment_sql(
    *,
    dialect: sa.engine.Dialect,
    table: sa.Table,
    column: sa.Column,
    comment: str | None,
    current_comment: str | None = None,
    mysql_create_sql: str | None = None,
) -> list[str]:
    require_column_comments(dialect)
    comment = normalize_comment(comment)
    if comment == normalize_comment(current_comment):
        return []
    preparer = dialect.identifier_preparer
    # preparer output is already DBAPI-escaped for mysql/pyformat.
    full_table = preparer.format_table(table)
    column_name = preparer.quote(column.name)
    if preparer._double_percents:
        full_table, column_name = full_table.replace("%%", "%"), column_name.replace("%%", "%")
    name = dialect.name
    if name in {"postgresql", "oracle"}:
        value = (
            _literal(comment, dialect)
            if comment is not None
            else ("NULL" if name == "postgresql" else "''")
        )
        return [f"COMMENT ON COLUMN {full_table}.{column_name} IS {value}"]
    if name == "clickhouse":
        return [
            f"ALTER TABLE {full_table} COMMENT COLUMN {column_name} {_literal(comment or '', dialect)}"
        ]
    if name in {"mysql", "mariadb"}:
        if mysql_create_sql is None:
            raise ValueError("SHOW CREATE TABLE is required to preserve MySQL column attributes.")
        definition = mysql_column_definition(mysql_create_sql, column.name)
        definition = mysql_comment_definition(definition, comment, dialect)
        return [f"ALTER TABLE {full_table} MODIFY COLUMN {definition}"]
    schema = table.schema or dialect.default_schema_name or "dbo"
    target = (
        f"@level0type=N'SCHEMA', @level0name={_literal(schema, dialect)}, "
        f"@level1type=N'TABLE', @level1name={_literal(table.name, dialect)}, "
        f"@level2type=N'COLUMN', @level2name={_literal(column.name, dialect)}"
    )
    if comment is None:
        return [f"EXEC sys.sp_dropextendedproperty @name=N'MS_Description', {target}"]
    operation = "update" if current_comment is not None else "add"
    return [
        f"EXEC sys.sp_{operation}extendedproperty @name=N'MS_Description', "
        f"@value={_literal(comment, dialect)}, {target}"
    ]


def separate_create_comment_sql(table: sa.Table, dialect: sa.engine.Dialect) -> list[str]:
    columns = [column for column in table.columns if normalize_comment(column.comment) is not None]
    if not columns:
        return []
    require_column_comments(dialect)
    if dialect.inline_comments:
        return []
    return [
        sql
        for column in columns
        for sql in build_column_comment_sql(
            dialect=dialect, table=table, column=column, comment=column.comment
        )
    ]
