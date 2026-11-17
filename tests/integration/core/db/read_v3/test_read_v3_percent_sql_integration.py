"""User SQL with ``%`` in query mode on drivers with the format/pyformat paramstyle."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.integration.fixtures.percent_sql import (
    PERCENT_ROWS,
    percent_name,
)

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config

pytestmark = pytest.mark.docker_required

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


# The SQL text means what it means in psql or the mysql client: '%%' is two percent signs.
PERCENT_QUERIES: dict[str, tuple[str, Callable[[int], bool]]] = {
    "like_prefix": ("SELECT id, name FROM {table} WHERE name LIKE 'A%'", lambda i: i % 4 in (0, 1)),
    "doubled_percent_literal": (
        "SELECT id, name FROM {table} WHERE LEFT(name, 2) = '%%'",
        lambda i: i % 4 == 3,
    ),
    "modulo_operator": ("SELECT id, name FROM {table} WHERE id % 3 = 0", lambda i: i % 3 == 0),
}


@pytest.mark.parametrize("grouping", [{"mode": "range"}, {"mode": "hash"}], ids=["range", "hash"])
@pytest.mark.parametrize("case", list(PERCENT_QUERIES))
def test_query_mode_keeps_percent_signs_of_user_sql(percent_table, case, grouping) -> None:
    engine, table_name = percent_table
    sql_template, selected = PERCENT_QUERIES[case]
    plan = resolve_planner(mode="query").build_plan(
        engine=engine,
        query=sql_template.format(table=table_name),
        partition_col="id",
        partition_grouping=grouping,
        npartitions=4,
        **STRICT_PARTITIONING_KWARGS,
    )

    result = frame_from_executor(resolve_executor(engine), plan).compute(scheduler="sync")

    expected_ids = [row_id for row_id in range(1, PERCENT_ROWS + 1) if selected(row_id)]
    assert plan.segment_count > 1
    assert sorted(result["id"].tolist()) == expected_ids
    assert sorted(result["name"].tolist()) == sorted(
        percent_name(row_id) for row_id in expected_ids
    )
