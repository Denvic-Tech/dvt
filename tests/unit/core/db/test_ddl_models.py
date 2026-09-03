from __future__ import annotations

import pytest

from core.db.ddl import ClickHouseEngineSpec


def test_clickhouse_engine_spec_requires_replica_args_for_replicated_engine() -> None:
    with pytest.raises(ValueError, match="table_path is required"):
        ClickHouseEngineSpec(engine_name="ReplicatedMergeTree")


def test_clickhouse_engine_spec_requires_sign_column_for_collapsing_engine() -> None:
    with pytest.raises(ValueError, match="sign_column is required"):
        ClickHouseEngineSpec(engine_name="CollapsingMergeTree")


def test_clickhouse_engine_spec_rejects_summing_columns_for_non_summing_engine() -> None:
    with pytest.raises(ValueError, match="summing_columns is allowed only"):
        ClickHouseEngineSpec(engine_name="MergeTree", summing_columns=["amount"])


def test_clickhouse_engine_spec_accepts_replacing_engine_with_version() -> None:
    spec = ClickHouseEngineSpec(
        engine_name="ReplacingMergeTree",
        version_column="version_id",
        order_by=["id"],
    )

    assert spec.version_column == "version_id"
