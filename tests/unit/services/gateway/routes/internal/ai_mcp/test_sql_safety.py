import pytest

from services.gateway.routes.internal.ai_mcp.data import _parse_readonly_sql
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH rows AS (SELECT 1 AS value) SELECT value FROM rows",
        "EXPLAIN SELECT * FROM public.events",
    ],
)
def test_readonly_sql_accepts_queries(sql: str) -> None:
    parsed, _ = _parse_readonly_sql(sql, "postgres")
    assert parsed == sql


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1; DELETE FROM events",
        "UPDATE events SET value = 1",
        "DELETE FROM events",
        "SELECT * INTO copied_events FROM events",
        "COPY events TO '/tmp/events.csv'",
        "CALL refresh_events()",
        "SELECT * FROM events FOR UPDATE",
        "EXPLAIN ANALYZE SELECT * FROM events",
        "EXPLAIN (ANALYZE TRUE) SELECT * FROM events",
        "WITH removed AS (DELETE FROM events RETURNING *) SELECT * FROM removed",
    ],
)
def test_readonly_sql_rejects_mutation_and_execution_attacks(sql: str) -> None:
    with pytest.raises(AIMCPHTTPError) as raised:
        _parse_readonly_sql(sql, "postgres")
    assert raised.value.detail["code"] == "UNSAFE_SQL"
