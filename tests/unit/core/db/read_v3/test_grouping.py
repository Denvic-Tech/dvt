from __future__ import annotations

import pandas as pd

from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.grouping.models import ValueKind as GroupingValueKind
from core.db.read_v3.partitioning.grouping import V3GroupingHelper


def test_value_counts_expr_groups_by_derived_column_alias(monkeypatch) -> None:
    helper = V3GroupingHelper(
        engine=object(),  # type: ignore[arg-type]
        dialect=SqliteDialect(),
        relation_sql="FROM user_query",
        cte_prefix_sql=None,
        value_kind=GroupingValueKind.STRING,
    )
    executed_sql: list[str] = []

    def fake_query_df(sql: str) -> pd.DataFrame:
        executed_sql.append(sql)
        if len(executed_sql) == 1:
            return pd.DataFrame({"v": ["o"], "cnt": [1]})
        return pd.DataFrame({"cnt": [0]})

    monkeypatch.setattr(helper, "_query_df", fake_query_df)

    result = helper.value_counts_expr('substr("table_code", 1, 1)', max_groups=4)

    assert result == [("o", 1)]
    assert executed_sql[0] == (
        'SELECT v, count(*) AS cnt '
        'FROM (SELECT substr("table_code", 1, 1) AS v FROM user_query) '
        "__dvt_group_values WHERE v IS NOT NULL "
        "GROUP BY v ORDER BY cnt DESC LIMIT 4 OFFSET 0"
    )
