"""SQLite engine whose DB-API cursor treats ``%`` like a format/pyformat driver (pymysql).

``cursor.execute(sql, params)`` applies ``sql % params`` whenever a parameter collection is
given, so SQL text with ``%`` breaks exactly as it does on psycopg or pymysql unless it reaches
the driver without parameters. Every call is recorded as ``(sql, params)``.
"""

from __future__ import annotations

import sqlite3

import sqlalchemy as sa


class _PercentFormatCursor:
    def __init__(self, cursor: sqlite3.Cursor, calls: list[tuple[str, object]]) -> None:
        self._cursor = cursor
        self._calls = calls

    def execute(self, sql: str, params: object = None):
        self._calls.append((sql, params))
        if params is not None:
            sql = sql % tuple(params)
        return self._cursor.execute(sql)

    def __getattr__(self, name: str):
        return getattr(self._cursor, name)


class _PercentFormatConnection:
    def __init__(self, database: str, calls: list[tuple[str, object]]) -> None:
        self._connection = sqlite3.connect(database)
        self._calls = calls

    def cursor(self) -> _PercentFormatCursor:
        return _PercentFormatCursor(self._connection.cursor(), self._calls)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


def percent_format_sqlite_engine(database: str, calls: list[tuple[str, object]]) -> sa.Engine:
    """Engine over the SQLite ``database`` (a file path or ``:memory:``)."""
    return sa.create_engine("sqlite://", creator=lambda: _PercentFormatConnection(database, calls))
