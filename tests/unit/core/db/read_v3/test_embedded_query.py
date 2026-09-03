from __future__ import annotations

import pytest

from core.db.read_v3.embedded_query import build_read_v3_query_embedding


def test_build_read_v3_query_embedding_wraps_plain_mssql_select() -> None:
    query_embedding = build_read_v3_query_embedding(
        "SELECT [id] FROM [dbo].[events] ORDER BY [created_at]",
        dialect_name="mssql",
    )

    assert query_embedding.embedded_query_sql == (
        "SELECT [id] FROM [dbo].[events] ORDER BY [created_at] OFFSET 0 ROWS"
    )
    assert query_embedding.cte_prefix_sql == (
        "WITH user_query AS (SELECT [id] FROM [dbo].[events] "
        "ORDER BY [created_at] OFFSET 0 ROWS)"
    )
    assert query_embedding.relation_sql == "FROM user_query"


def test_build_read_v3_query_embedding_lifts_top_level_mssql_cte() -> None:
    query_embedding = build_read_v3_query_embedding(
        (
            "WITH seeded AS ("
            "SELECT TOP 12 [id], [category] FROM [dbo].[events] ORDER BY [id]"
            ") "
            "SELECT [id], [category] FROM seeded"
        ),
        dialect_name="mssql",
    )

    assert query_embedding.embedded_query_sql == "SELECT [id], [category] FROM seeded"
    assert query_embedding.cte_prefix_sql.startswith("WITH seeded AS (SELECT TOP 12 [id]")
    assert "FROM [dbo].[events] ORDER BY [id])" in query_embedding.cte_prefix_sql
    assert "user_query AS (SELECT [id] AS [id], [category] AS [category] FROM seeded)" in (
        query_embedding.cte_prefix_sql
    )
    assert query_embedding.relation_sql == "FROM user_query"


def test_build_read_v3_query_embedding_rejects_mssql_batch_scripts() -> None:
    with pytest.raises(
        ValueError,
        match="supports a single SELECT query or top-level WITH \\.\\.\\. SELECT",
    ):
        build_read_v3_query_embedding(
            "DECLARE @id INT = 1; SELECT @id AS id",
            dialect_name="mssql",
        )
