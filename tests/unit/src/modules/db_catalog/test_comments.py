import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogCacheEntry,
    CatalogColumn,
    CatalogOperation,
    CatalogRequest,
    CatalogResult,
    CatalogTableDetails,
    CatalogTableKind,
    CatalogTableSummary,
)
from src.modules.db_catalog.domain.policies import build_cache_key
from src.modules.db_catalog.infra.gateways.sqlalchemy_catalog import SQLAlchemyCatalogSource
from src.modules.db_catalog.infra.gateways.table_comments import table_comments_statement
from src.modules.db_catalog.infra.mappers import dump_cache_entry, load_cache_entry


def _source():
    return SQLAlchemyCatalogSource(
        connect_timeout_seconds=5,
        query_timeout_seconds=5,
        request_timeout_seconds=10,
        max_concurrency=1,
    )


def _connection(dialect="postgresql"):
    return AuthorizedCatalogConnection(
        id="c",
        revision="r",
        dialect=dialect,
        configured_database="db",
        connection_url="sqlite://",
    )


def test_cache_round_trip_preserves_table_list_and_column_comments():
    now = datetime.now(UTC)
    entry = CatalogCacheEntry(
        result=CatalogResult(
            items=(CatalogTableSummary(name="t", kind=CatalogTableKind.TABLE, comment="Таблица"),),
            table=CatalogTableDetails(
                name="t",
                kind=CatalogTableKind.TABLE,
                comment="Таблица",
                columns=(CatalogColumn(name="x", ordinal=1, dtype="INT", comment="  Поле\n  "),),
            ),
        ),
        catalog_version="r:0",
        loaded_at=now,
        expires_at=now + timedelta(seconds=60),
    )
    assert load_cache_entry(dump_cache_entry(entry)) == entry
    raw = json.loads(dump_cache_entry(entry))
    raw["version"] = 1
    with pytest.raises(ValueError, match="version"):
        load_cache_entry(json.dumps(raw).encode())
    assert build_cache_key(
        _connection(), CatalogRequest(operation=CatalogOperation.TABLES), 0
    ).startswith("dvt:db-catalog:v2:")


@pytest.mark.parametrize(
    "dialect",
    [
        "postgresql",
        "mysql",
        "mariadb",
        "mssql",
        "sqlserver",
        "oracle",
        "clickhouse",
    ],
)
def test_comment_query_binds_identifiers_as_values(dialect):
    statement = table_comments_statement(dialect)
    sql = str(statement)
    assert ":schema" in sql
    assert "names" in sql
    bound = statement.params(names=["a'quote", "MixedCase"], schema="A'B", database="db")
    # Values are passed separately, including expanding IN parameters.
    assert "a'quote" not in str(bound)
    assert "A'B" not in str(bound)
    assert bound.compile().params["names"] == ["a'quote", "MixedCase"]


def test_sqlite_has_no_comment_query():
    assert table_comments_statement("sqlite") is None


def test_catalog_page_fetches_comments_once_for_returned_rows(monkeypatch):
    source = _source()
    engine = Mock()
    engine.dialect = SimpleNamespace(supports_comments=True)
    first = Mock()
    first.execute.return_value.mappings.return_value = [
        {"name": "alpha", "kind": "BASE TABLE"},
        {"name": "beta", "kind": "VIEW"},
        {"name": "gamma", "kind": "BASE TABLE"},
    ]
    second = Mock()
    second.execute.return_value.mappings.return_value = [
        {"name": "beta", "comment": "Представление"},
        {"name": "alpha", "comment": "Таблица"},
    ]
    from unittest.mock import MagicMock

    contexts = [MagicMock(), MagicMock()]
    contexts[0].__enter__.return_value = first
    contexts[1].__enter__.return_value = second
    engine.connect.side_effect = contexts
    monkeypatch.setattr(source, "_apply_session_deadline", lambda *args: None)
    result = source._fetch_page(
        engine,
        _connection(),
        CatalogRequest(
            operation=CatalogOperation.TABLES,
            schema_name="analytics",
            limit=2,
        ),
    )
    assert [(item.name, item.comment) for item in result.items] == [
        ("alpha", "Таблица"),
        ("beta", "Представление"),
    ]
    assert result.next_cursor is not None
    assert engine.connect.call_count == 2
    second.execute.assert_called_once()
    assert second.execute.call_args.args[1] == {
        "names": ["alpha", "beta"],
        "schema": "analytics",
        "database": "db",
    }


def test_comment_query_failure_preserves_page(monkeypatch):
    source = _source()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE alpha (id INTEGER)")
    # Force a separate unsupported system-catalog query against real SQLite.
    monkeypatch.setattr(engine.dialect, "supports_comments", True)
    monkeypatch.setattr(source, "_apply_session_deadline", lambda *args: None)
    monkeypatch.setattr(
        source,
        "_build_page_query",
        lambda *args: (
            "SELECT 'alpha' AS name, 'BASE TABLE' AS kind",
            {},
        ),
    )
    result = source._fetch_page(
        engine,
        _connection(),
        CatalogRequest(
            operation=CatalogOperation.TABLES,
        ),
    )
    assert len(result.items) == 1
    assert result.items[0].name == "alpha"
    assert result.items[0].comment is None
    engine.dispose()
