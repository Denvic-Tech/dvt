from __future__ import annotations

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel, ParseError, SqlglotError, TokenError

from core.db.ddl.parse import get_sqlglot_dialect

from ..domain import SQLCodeMetadataError, SQLStatementCategory, SQLStatementMetadata, SQLValidationError
from ..flow.gateways import ParsedSQLCode, ParsedSQLStatement, SQLParserGateway


class SQLGlotParserGateway(SQLParserGateway):
    """Разбирает SQL через sqlglot и строит statement metadata."""

    SYNTAX_ERROR_MESSAGE = "SQL contains syntax errors."
    _DDL_STATEMENT_TYPES = frozenset({"ALTER", "CREATE", "DROP", "RENAME", "TRUNCATE"})
    _DATA_MUTATING_STATEMENT_TYPES = frozenset({"DELETE", "INSERT", "MERGE", "UPDATE"})
    _EXECUTION_STATEMENT_TYPES = frozenset({"CALL", "COMMAND", "EXEC", "EXECUTE"})

    def parse_sql(self, *, sql: str, dialect_name: str | None = None) -> ParsedSQLCode:
        resolved_dialect = self._resolve_dialect_name(dialect_name)
        expressions = self._parse_sql(sql=sql, resolved_dialect=resolved_dialect)
        statements = tuple(
            ParsedSQLStatement(
                expression=expression,
                metadata=self._classify_statement(expression),
                sql=self._render_expression_sql(expression=expression, resolved_dialect=resolved_dialect),
            )
            for expression in expressions
        )
        return ParsedSQLCode(statements=statements, dialect_name=resolved_dialect)

    def _parse_sql(self, *, sql: str, resolved_dialect: str | None) -> list[exp.Expression]:
        parse_kwargs = {"error_level": ErrorLevel.RAISE}

        try:
            if resolved_dialect is None:
                expressions = parse(sql, **parse_kwargs)
            else:
                expressions = parse(sql, read=resolved_dialect, **parse_kwargs)
        except (ParseError, SqlglotError, TokenError) as exc:
            raise SQLValidationError(self.SYNTAX_ERROR_MESSAGE) from exc

        self._raise_on_unexpected_command_fallback(sql=sql, expressions=expressions)
        return expressions

    def _resolve_dialect_name(self, dialect_name: str | None) -> str | None:
        if dialect_name is None:
            return None

        normalized_name = dialect_name.strip().lower()
        if not normalized_name:
            return None

        return get_sqlglot_dialect(normalized_name)

    def _render_expression_sql(self, *, expression: exp.Expression, resolved_dialect: str | None) -> str:
        try:
            if resolved_dialect is None:
                return expression.sql()
            return expression.sql(dialect=resolved_dialect)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise SQLCodeMetadataError("Failed to render SQL statement after parsing.") from exc

    def _raise_on_unexpected_command_fallback(
        self,
        *,
        sql: str,
        expressions: list[exp.Expression],
    ) -> None:
        normalized_sql = sql.lstrip()
        if not normalized_sql:
            return

        first_token = normalized_sql.split(maxsplit=1)[0].upper()
        structured_statement_types = (
            self._DDL_STATEMENT_TYPES
            | self._DATA_MUTATING_STATEMENT_TYPES
            | frozenset({"SELECT", "WITH"})
        )
        if first_token not in structured_statement_types:
            return

        if any((expression.key or "").upper() == "COMMAND" for expression in expressions):
            raise SQLValidationError(self.SYNTAX_ERROR_MESSAGE)

    def _classify_statement(self, expression: exp.Expression) -> SQLStatementMetadata:
        statement_type = self._resolve_statement_type(expression)
        is_query_expression = isinstance(expression, exp.Query)
        return SQLStatementMetadata(
            statement_type=statement_type,
            category=self._resolve_category(expression=expression, statement_type=statement_type),
            returns_data=self._returns_data(expression),
            is_query_expression=is_query_expression,
        )

    def _resolve_statement_type(self, expression: exp.Expression) -> str:
        if isinstance(expression, exp.Query):
            return "SELECT"

        return (expression.key or expression.__class__.__name__).upper()

    def _resolve_category(self, *, expression: exp.Expression, statement_type: str) -> SQLStatementCategory:
        if isinstance(expression, exp.Query):
            return "read_only"
        if statement_type in self._DATA_MUTATING_STATEMENT_TYPES:
            return "data_mutating"
        if statement_type in self._DDL_STATEMENT_TYPES:
            return "ddl"
        if statement_type in self._EXECUTION_STATEMENT_TYPES:
            return "execution"
        return "unknown"

    def _returns_data(self, expression: exp.Expression) -> bool:
        if isinstance(expression, exp.Query):
            return True

        returning = expression.args.get("returning")
        if returning is None:
            return False

        expressions = returning.args.get("expressions") or []
        return bool(expressions or returning.args.get("into"))
