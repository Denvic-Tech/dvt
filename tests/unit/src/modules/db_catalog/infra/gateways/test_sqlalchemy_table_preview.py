import asyncio
import json
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
import sqlalchemy as sa
from clickhouse_sqlalchemy.drivers.http.base import ClickHouseDialect_http
from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogTableNotFoundError,
    CatalogTablePreviewRequest,
)
from src.modules.db_catalog.infra.gateways.sqlalchemy_catalog import (
    SQLAlchemyCatalogSource,
    _normalize_preview_value,
    _preview_payload_size,
)


def _source(**overrides) -> SQLAlchemyCatalogSource:
    options = {
        "connect_timeout_seconds": 5,
        "query_timeout_seconds": 30,
        "request_timeout_seconds": 40,
        "max_concurrency": 16,
    }
    options.update(overrides)
    return SQLAlchemyCatalogSource(**options)


def _connection(path) -> AuthorizedCatalogConnection:
    return AuthorizedCatalogConnection(
        id="conn",
        revision="revision",
        dialect="sqlite",
        configured_database=str(path),
        connection_url=sa.URL.create(
            "sqlite+pysqlite",
            database=str(path),
        ).render_as_string(hide_password=False),
    )


def test_sqlite_table_preview_preserves_column_order_and_limits_rows(tmp_path):
    path = tmp_path / "preview.sqlite"
    engine = sa.create_engine(f"sqlite:///{path}")
    metadata = sa.MetaData()
    table = sa.Table(
        "odd table",
        metadata,
        sa.Column("row id", sa.Integer()),
        sa.Column("payload", sa.String()),
        sa.Column("binary value", sa.LargeBinary()),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [
                {"row id": index, "payload": f"value-{index}", "binary value": b"abc"}
                for index in range(51)
            ],
        )
    engine.dispose()

    result = asyncio.run(
        _source().fetch_preview(
            _connection(path),
            CatalogTablePreviewRequest(table_name="odd table"),
        )
    )

    assert [column.name for column in result.columns] == [
        "row id",
        "payload",
        "binary value",
    ]
    assert [column.dtype for column in result.columns] == ["INT", "STRING", "UNKNOWN"]
    assert len(result.rows) == 50
    assert all(len(row) == len(result.columns) for row in result.rows)
    assert {row[0] for row in result.rows}.issubset(set(range(51)))
    assert {row[2] for row in result.rows} == {"<binary:3 bytes>"}
    assert result.truncated is True


def test_sqlite_view_preview_and_missing_table(tmp_path):
    path = tmp_path / "view.sqlite"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE base_table (id INTEGER, value TEXT)")
        connection.exec_driver_sql("INSERT INTO base_table VALUES (1, 'one')")
        connection.exec_driver_sql("CREATE VIEW preview_view AS SELECT value FROM base_table")
    engine.dispose()

    source = _source()
    result = asyncio.run(
        source.fetch_preview(
            _connection(path),
            CatalogTablePreviewRequest(table_name="preview_view"),
        )
    )

    assert [column.name for column in result.columns] == ["value"]
    assert result.rows == (("one",),)
    with pytest.raises(CatalogTableNotFoundError):
        asyncio.run(
            source.fetch_preview(
                _connection(path),
                CatalogTablePreviewRequest(table_name="missing"),
            )
        )


def test_preview_value_normalization_is_json_safe_and_bounded():
    identifier = UUID("4cfde903-857b-4ea3-8588-bb59f15a3d1c")

    assert _normalize_preview_value(Decimal("1.20"), 64) == ("1.20", False)
    assert _normalize_preview_value(date(2026, 8, 28), 64) == ("2026-08-28", False)
    assert _normalize_preview_value(identifier, 64) == (str(identifier), False)
    assert _normalize_preview_value({"a": [1]}, 64) == ('{"a":[1]}', False)
    assert _normalize_preview_value(b"abc", 64) == ("<binary:3 bytes>", True)
    assert _normalize_preview_value("abcd", 3) == ("ab…", True)
    assert _normalize_preview_value(float("inf"), 64) == ("inf", False)


def test_preview_stops_at_complete_row_when_response_budget_is_reached(tmp_path):
    path = tmp_path / "budget.sqlite"
    engine = sa.create_engine(f"sqlite:///{path}")
    metadata = sa.MetaData()
    table = sa.Table(
        "large_values",
        metadata,
        sa.Column("id", sa.Integer()),
        sa.Column("payload", sa.String()),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            [{"id": index, "payload": "x" * 100} for index in range(10)],
        )
    engine.dispose()

    source = _source(preview_cell_max_chars=32, preview_max_response_bytes=180)
    result = asyncio.run(
        source.fetch_preview(
            _connection(path),
            CatalogTablePreviewRequest(table_name="large_values"),
        )
    )

    assert result.truncated is True
    assert 0 < len(result.rows) < 10
    assert all(len(row) == 2 for row in result.rows)
    assert _preview_payload_size(result) <= 180
    json.dumps([list(row) for row in result.rows], allow_nan=False)


@pytest.mark.parametrize(
    "dialect",
    [
        postgresql.dialect(),
        mysql.dialect(),
        mssql.dialect(),
        oracle.dialect(),
        sqlite.dialect(),
        ClickHouseDialect_http(),
    ],
)
def test_preview_statement_compiles_with_identifier_quoting_and_fixed_limit(dialect):
    table = sa.table("odd table", sa.column("select"))

    statement = _source()._build_preview_statement(table)
    compiled = str(statement.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))

    assert "odd table" in compiled
    assert "select" in compiled
    assert "51" in compiled
