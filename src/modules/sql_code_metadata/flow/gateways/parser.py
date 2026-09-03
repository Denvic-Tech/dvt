from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...domain import SQLStatementMetadata


@dataclass(frozen=True)
class ParsedSQLStatement:
    """Содержит raw expression и его каноническое statement metadata."""

    expression: Any
    metadata: SQLStatementMetadata
    sql: str


@dataclass(frozen=True)
class ParsedSQLCode:
    """Содержит результат AST-разбора всего SQL-кода."""

    statements: tuple[ParsedSQLStatement, ...]
    dialect_name: str | None = None


class SQLParserGateway(Protocol):
    """Описывает контракт AST-парсера SQL."""

    def parse_sql(self, *, sql: str, dialect_name: str | None = None) -> ParsedSQLCode:
        """Разбирает SQL и возвращает metadata для каждого top-level statement."""
